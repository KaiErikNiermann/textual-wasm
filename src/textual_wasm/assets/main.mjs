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


import { boot, importPyodide, readManifest } from "./boot.mjs";

/**
 * Everything the page needs to know about the app it is hosting, written by
 * `textual-wasm build`. Keeping it in a file rather than in this script means one page
 * serves every application, and a rebuild is a data change.
 *
 * Resolved against this module's own URL, not the document's. That is what lets a build be
 * served from a subdirectory of someone else's site - `/terminal/main.mjs` finds
 * `/terminal/app.json` while the page itself lives at `/`. A document-relative path only
 * works when the build *is* the site.
 */
const MANIFEST_URL = new URL("app.json", import.meta.url);

/**
 * Used when the host page defines no `--font-terminal`. A real fixed-pitch stack, because
 * the font is what decides how wide a character cell is.
 */
const FALLBACK_TERMINAL_FONT = '"IBM Plex Mono", "DejaVu Sans Mono", ui-monospace, monospace';

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
    // widths has exactly one definition (PC-1) - but with a fallback, because a page that
    // embeds this build supplies its own stylesheet and need not know that token exists.
    // An empty fontFamily leaves xterm on its own default, and the font is what decides
    // cell widths, so silently accepting one is how a render goes subtly wrong.
    fontFamily: styles.getPropertyValue("--font-terminal").trim() || FALLBACK_TERMINAL_FONT,
    // Textual renders truecolor and expects to own the whole grid.
    allowProposedApi: true,
    convertEol: false,
    cursorBlink: false,
    theme: { background: styles.getPropertyValue("--color-terminal-bg").trim() || undefined },
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
 * Import the terminal emulator at the versions the build pinned, and its stylesheet.
 *
 * Dynamic rather than static imports because the URLs come from the manifest: a static
 * import would mean a second copy of every version number living in this file, and a copy
 * is a thing that drifts.
 *
 * Pyodide is deliberately absent. In worker mode it is loaded inside the worker, and
 * fetching a second copy here would download a runtime the page never runs.
 *
 * @param {object} manifest
 */
async function loadTerminalDependencies(manifest) {
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = manifest.xtermCssUrl;
  document.head.append(stylesheet);

  const [xterm, fit] = await Promise.all([
    import(manifest.xtermUrl),
    import(manifest.fitAddonUrl),
  ]);
  return { Terminal: xterm.Terminal, FitAddon: fit.FitAddon };
}

/**
 * Run the interpreter inside a Web Worker, with this thread keeping only the terminal.
 *
 * The worker satisfies exactly the same four-member host contract; it just satisfies it
 * over `postMessage` instead of by direct call. That is why nothing on the Python side
 * changes between the two modes, and why `globalThis.textualWasm` below is assembled the
 * same way for both - the automation surface reads this thread's `xterm.js` buffer, which
 * is where the output lands either way.
 *
 * @param {object} manifest
 * @param {object} host the terminal-backed host built by `createTerminal`
 * @returns {Promise<{finished: Promise<unknown>}>} resolves once the app is running. The
 *   exit promise is returned *wrapped*, because resolving a promise with a promise adopts
 *   it - `resolve(finished)` would make this wait for the application to exit rather than
 *   to start, which is a hang with no error attached to it.
 */
async function bootInWorker(manifest, host) {
  const worker = new Worker(new URL("worker.mjs", import.meta.url), { type: "module" });

  const {promise: running, resolve: onRunning, reject: onFailed} = Promise.withResolvers();
  // "Running" has to mean "has drawn", not "has been started". On the main thread those
  // coincide, because the driver's first writes happen synchronously inside the call that
  // starts the app; through a worker they are two messages with a gap between them, and a
  // harness that reads the grid in that gap sees a blank screen and calls it the render.
  // So the page waits for the interpreter to say it started *and* for the first output to
  // arrive. An app that exits without drawing anything resolves it too, so this cannot hang.
  let isStarted = false;
  let isDrawn = false;
  const settleIfReady = () => {
    if (isStarted && isDrawn) {
      onRunning({ finished });
    }
  };
  const {promise: finished, resolve: onExited, reject: onCrashed} = Promise.withResolvers();

  worker.addEventListener("message", ({ data }) => {
    switch (data.type) {
      case "write": {
        host.write(data.data);
        isDrawn = true;
        settleIfReady();
        break;
      }
      case "status": {
        setStatus(data.state, data.message);
        break;
      }
      case "running": {
        isStarted = true;
        settleIfReady();
        break;
      }
      case "exited": {
        isDrawn = true;
        settleIfReady();
        onExited();
        break;
      }
      case "crashed": {
        isDrawn = true;
        settleIfReady();
        onCrashed(new Error(data.error));
        break;
      }
      // The two capabilities a worker cannot perform itself, forwarded back to this thread
      // rather than failing: neither `window` nor `document` exists inside one.
      case "open-url": {
        open(data.url, data.newTab ? "_blank" : "_self");
        break;
      }
      case "deliver-file": {
        const anchor = document.createElement("a");
        anchor.href = data.href;
        anchor.download = data.filename;
        anchor.click();
        break;
      }
      default: {
        console.warn(`[textual-wasm] unknown message from worker: ${data.type}`);
      }
    }
  });
  // A worker that fails to load reports here and nowhere else; without this the page sits
  // on "starting Python…" forever with the real error only in the console.
  worker.addEventListener("error", (event) => {
    onFailed(new Error(event.message || "the worker failed to start"));
  });

  host.onData((data) => worker.postMessage({ type: "input", data }));
  host.onResize((cols, rows) => worker.postMessage({ type: "resize", cols, rows }));

  worker.postMessage({
    type: "start",
    manifest,
    cols: host.cols,
    rows: host.rows,
  });
  return running;
}

/**
 * Run the interpreter on this thread, which is the default.
 *
 * @param {object} manifest
 * @param {object} host
 * @returns {Promise<{finished: Promise<unknown>}>} wrapped for the same reason as above:
 *   returning a bare promise from an async function adopts it.
 */
async function bootHere(manifest, host) {
  const loadPyodide = await importPyodide(manifest);
  const { finished } = await boot({ manifest, host, loadPyodide, onStatus: setStatus });
  return { finished };
}

async function main() {
  const manifest = await readManifest(MANIFEST_URL);
  // The document is named after the application, not after this project. A page is a thing
  // people bookmark and put in a tab strip.
  if (manifest.title) {
    document.title = manifest.title;
  }

  const { terminal, host, fit } = createTerminal(await loadTerminalDependencies(manifest));
  await layoutSettled();
  fit();

  const { finished } = await (
    manifest.worker ? bootInWorker(manifest, host) : bootHere(manifest, host)
  );

  setStatus("ready", `running at ${host.cols}x${host.rows}`);

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
    worker: Boolean(manifest.worker),
  };

  // Attached rather than awaited, and that distinction is the whole embedding story: a
  // module whose top-level evaluation waits for the application to exit never finishes
  // evaluating, so `await import("./main.mjs")` from a host page hangs forever - which is
  // exactly what happened to the Svelte example. Said plainly on exit rather than left
  // blank, because a terminal app that has exited leaves its last frame on screen, which is
  // indistinguishable from one that has frozen.
  const onExit = () => setStatus("failed", "the application exited");
  const onCrash = (error) => setStatus("failed", `the application crashed: ${error}`);
  // eslint-disable-next-line unicorn/prefer-await -- awaiting here is precisely the bug
  finished.then(onExit).catch(onCrash);
}

try {
  await main();
} catch (error) {
  setStatus("failed", `failed: ${error}`);
  throw error;
}
