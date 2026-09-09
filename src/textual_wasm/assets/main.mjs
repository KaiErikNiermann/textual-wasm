/**
 * Boot Pyodide, hand it an `xterm.js` terminal, and run the Textual app against it.
 *
 * This is the half the Node probe cannot test. The probe proves the Python side works
 * under wasm32-emscripten; this proves the byte stream it produces is a real terminal
 * stream that a browser emulator renders correctly, cell widths included.
 *
 * The page's entire contract with Python is the four-member object below, which is what
 * `textual_wasm.browser.TerminalHost` declares.
 */


/**
 * Where Python packages are written into Pyodide's filesystem. A build writes both this
 * project and the application here, so neither has to be a wheel.
 */
const SITE_PACKAGES = "/lib/python3.14/site-packages";

/**
 * Everything the page needs to know about the app it is hosting, written by
 * `textual-wasm build`. Keeping it in a file rather than in this script means one page
 * serves every application, and a rebuild is a data change.
 */
const MANIFEST_URL = "./app.json";
const HOST_MODULE = "textual_wasm_host";

/*
 * The automation surface is published as `globalThis.textualWasm`, deliberately and not as a
 * debug hook: the browser half of the experiment is only worth anything if a machine can run
 * it, and a machine needs a fixed grid and a way to read the buffer back. The packaged
 * `browser-check.mjs` harness is its consumer, and `textual-wasm check` is what runs that.
 */

/**
 * A forced grid, from `?cols=&rows=`. Comparing this render against the native one requires
 * both to be the same size, and a browser window's size is not a number anyone chose.
 *
 * @returns {{ cols: number, rows: number } | null}
 */
function forcedGrid() {
  const parameters = new URLSearchParams(location.search);
  const cols = Number(parameters.get("cols"));
  const rows = Number(parameters.get("rows"));
  return Number.isSafeInteger(cols) && cols > 0 && Number.isSafeInteger(rows) && rows > 0
    ? { cols, rows }
    : null;
}

/**
 * Read the terminal's visible grid back as text.
 *
 * `buffer.active` is the alternate buffer while an app is running, which is the one Textual
 * draws into. Trailing blanks are trimmed here and again on the Python side, because
 * emulators disagree about whether an untouched cell is a space or nothing.
 *
 * @param {object} terminal
 * @returns {{ columns: number, rows: number, lines: string[] }}
 */
function readScreen(terminal) {
  const buffer = terminal.buffer.active;
  const lines = [];
  for (let row = 0; row < terminal.rows; row += 1) {
    const line = buffer.getLine(row);
    lines.push(line === undefined ? "" : line.translateToString(true));
  }
  return { columns: terminal.cols, rows: terminal.rows, lines };
}

const statusElement = document.querySelector("#status");

/**
 * Report progress. The state lands on a `data-state` attribute rather than a class,
 * because the stylesheet reads state the DOM already holds (PC-6).
 *
 * Optional: a custom page supplied with `--template` need not carry a status element, and a
 * missing one falls back to the console rather than throwing - a page that renders the app
 * perfectly should not fail because it declined to show a boot message.
 *
 * @param {"booting" | "ready" | "failed"} state
 * @param {string} message
 */
function setStatus(state, message) {
  if (statusElement === null) {
    console.info(`[textual-wasm] ${state}: ${message}`);
    return;
  }
  statusElement.dataset.state = state;
  statusElement.textContent = message;
}

/**
 * Resolve once the browser can measure a character cell.
 *
 * `FitAddon.fit()` divides the container by the cell size, so running it before the web
 * font has loaded and before the container has been laid out yields a 1-row grid - which
 * is not an error anywhere, just a terminal that renders one line of an app expecting 40.
 */
async function layoutSettled() {
  await document.fonts.ready;
  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

/**
 * Build the terminal and the object Python drives it through.
 *
 * @param {{Terminal: Function, FitAddon: Function}} deps the pinned runtime modules
 * @returns {{ terminal: object, host: object, fit: () => void }}
 */
function createTerminal({ Terminal, FitAddon }) {
  const styles = getComputedStyle(document.documentElement);
  const terminal = new Terminal({
    // Taken from the token table rather than restated, so the font that decides cell
    // widths has exactly one definition (PC-1).
    fontFamily: styles.getPropertyValue("--font-terminal").trim(),
    // Textual renders truecolor and expects to own the whole grid.
    allowProposedApi: true,
    convertEol: false,
    cursorBlink: false,
    theme: { background: styles.getPropertyValue("--color-terminal-bg").trim() },
  });
  const container = document.querySelector("#terminal");
  const fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);
  terminal.open(container);

  const forced = forcedGrid();
  if (forced === null) {
    // Observe the container rather than the window: the terminal's size is a fact about its
    // box, and a window listener misses every layout change that is not a window resize.
    new ResizeObserver(() => fitAddon.fit()).observe(container);
  }

  const host = {
    write: (data) => terminal.write(data),
    onData: (callback) => terminal.onData(callback),
    onResize: (callback) => terminal.onResize(({ cols, rows }) => callback(cols, rows)),
    get cols() {
      return terminal.cols;
    },
    get rows() {
      return terminal.rows;
    },
  };

  const fit = () => {
    if (forced === null) {
      fitAddon.fit();
    } else {
      terminal.resize(forced.cols, forced.rows);
    }
    // Part of the automation contract, not a debug aid: a harness checking that the grid
    // fits inside its frame has to know the sizing has happened, and the only alternative
    // signal - the terminal existing - is true a frame earlier, when it is still 80x24.
    container.dataset.fitted = "true";
  };

  return { terminal, host, fit };
}

/**
 * Write Python sources into Pyodide's filesystem.
 *
 * Sources rather than wheels, so a development server can serve straight from disk and an
 * edit needs only a reload - and so the browser demonstrably runs the same files the other
 * runtimes do.
 *
 * @param {object} pyodide
 * @param {Record<string, Record<string, string>>} packages package name to {path: source}
 */
function installPackages(pyodide, packages) {
  for (const [name, files] of Object.entries(packages)) {
    for (const [relative, source] of Object.entries(files)) {
      const target = `${SITE_PACKAGES}/${name}/${relative}`;
      pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
      pyodide.FS.writeFile(target, source, { encoding: "utf8" });
    }
  }
}

/**
 * Import the runtime dependencies at the versions the build pinned.
 *
 * Dynamic rather than static imports because the URLs come from the manifest: a static
 * import would mean a second copy of every version number living in this file, and a copy
 * is a thing that drifts.
 *
 * @param {object} manifest
 */
async function loadDependencies(manifest) {
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = manifest.xtermCssUrl;
  document.head.append(stylesheet);

  const [xterm, fit, pyodide] = await Promise.all([
    import(manifest.xtermUrl),
    import(manifest.fitAddonUrl),
    import(`${manifest.pyodideIndexUrl}pyodide.mjs`),
  ]);
  return { Terminal: xterm.Terminal, FitAddon: fit.FitAddon, loadPyodide: pyodide.loadPyodide };
}

/**
 * @returns {Promise<object>} the build manifest.
 */
async function readManifest() {
  const response = await fetch(MANIFEST_URL);
  if (!response.ok) {
    throw new Error(`no ${MANIFEST_URL}; run \`textual-wasm build\` to produce one`);
  }
  return response.json();
}

async function main() {
  const manifest = await readManifest();
  // The document is named after the application, not after this project. A page is a thing
  // people bookmark and put in a tab strip.
  if (manifest.title) {
    document.title = manifest.title;
  }
  const dependencies = await loadDependencies(manifest);

  const { terminal, host, fit } = createTerminal(dependencies);
  await layoutSettled();
  fit();

  setStatus("booting", "starting Python…");
  const pyodide = await dependencies.loadPyodide({
    indexURL: manifest.pyodideIndexUrl,
    // COLUMNS and LINES because os.get_terminal_size() raises here and
    // shutil.get_terminal_size() falls back to 80x24 - a TUI would lay out for the wrong
    // grid without them. isatty likewise: a terminal app that believes it has no terminal
    // disables colour and line editing before it draws anything.
    env: { COLUMNS: String(host.cols), LINES: String(host.rows), TERM: "xterm-256color" },
  });
  pyodide.setStdin({ stdin: () => null, isatty: true });

  setStatus("booting", `installing ${manifest.requirements.length} package(s)…`);
  await pyodide.loadPackage("micropip");
  await pyodide.pyimport("micropip").install(manifest.requirements);
  const sources = await fetch(manifest.sourcesUrl);
  installPackages(pyodide, await sources.json());

  // Registered before the driver is imported: `textual_wasm.browser` resolves the host at
  // import time and says so explicitly if the page skipped this.
  pyodide.registerJsModule(HOST_MODULE, host);

  setStatus("booting", "starting the app…");
  const entry = await fetch(manifest.entryUrl);
  await pyodide.runPythonAsync(await entry.text());

  setStatus("ready", `running at ${host.cols}x${host.rows}`);

  const start = pyodide.globals.get("start");
  const finished = start(manifest.entry);

  // Published only once the app is actually driving the terminal, so a harness that waits
  // for it cannot read a half-booted screen.
  // Publishing on the global object is the point here, not an accident: this is the
  // documented surface the browser harness drives, and a harness in another realm cannot
  // reach a module-scoped binding.
  // eslint-disable-next-line unicorn/no-global-object-property-assignment
  globalThis.textualWasm = {
    columns: host.cols,
    rows: host.rows,
    screen: () => readScreen(terminal),
    // xterm's supported "as if it came from the user" entry point, so this exercises the
    // same onData path a keystroke does rather than bypassing it.
    input: (data) => terminal.input(data),
    finished,
  };

  await finished;
  // Said plainly rather than left blank: a terminal app that has exited leaves its last
  // frame on screen, which is indistinguishable from one that has frozen.
  setStatus("failed", "the application exited");
}

try {
  await main();
} catch (error) {
  setStatus("failed", `failed: ${error}`);
  throw error;
}
