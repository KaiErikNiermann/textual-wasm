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

import { FitAddon } from "/vendor/addon-fit/lib/addon-fit.mjs";
import { Terminal } from "/vendor/xterm/lib/xterm.mjs";
import { loadPyodide } from "/vendor/pyodide/pyodide.mjs";

const PACKAGE_DIR = "/lib/python3.14/site-packages/textual_wasm";
const HOST_MODULE = "textual_wasm_host";

/*
 * The automation surface is published as `globalThis.textualWasmSpike`, deliberately and not
 * as a debug hook: the browser half of the experiment is only worth anything if a machine
 * can run it, and a machine needs a fixed grid and a way to read the buffer back.
 * `scripts/run-browser-check.mjs` is its only consumer.
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
 * @param {Terminal} terminal
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
 * @param {"booting" | "ready" | "failed"} state
 * @param {string} message
 */
function setStatus(state, message) {
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
 * @returns {{ terminal: Terminal, host: object, fit: () => void }}
 */
function createTerminal() {
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
  };

  return { terminal, host, fit };
}

/**
 * Write the project's own package into Pyodide's filesystem.
 *
 * Served straight from `src/` rather than installed as a wheel, so the browser
 * demonstrably runs the same files as the Node probe and an edit needs only a reload.
 *
 * @param {import("/vendor/pyodide/pyodide.mjs").PyodideInterface} pyodide
 */
async function installProjectPackage(pyodide) {
  const response = await fetch("/api/package");
  const sources = await response.json();
  pyodide.FS.mkdirTree(PACKAGE_DIR);
  for (const [name, source] of Object.entries(sources)) {
    pyodide.FS.writeFile(`${PACKAGE_DIR}/${name}`, source, { encoding: "utf8" });
  }
}

/**
 * @returns {Promise<string[]>} the pinned requirements, from the generated file.
 */
async function readRequirements() {
  const response = await fetch("/wasm-requirements.txt");
  const text = await response.text();
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));
}

async function main() {
  const { terminal, host, fit } = createTerminal();
  await layoutSettled();
  fit();

  setStatus("booting", "booting Pyodide…");
  const pyodide = await loadPyodide({ indexURL: "/vendor/pyodide/" });

  setStatus("booting", "installing Textual…");
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  await micropip.install(await readRequirements());
  await installProjectPackage(pyodide);

  // Registered before the driver is imported: `textual_wasm.browser` resolves the host at
  // import time and says so explicitly if the page skipped this.
  pyodide.registerJsModule(HOST_MODULE, host);

  setStatus("booting", "starting the app…");
  const entry = await fetch("/entry/browser_entry.py");
  await pyodide.runPythonAsync(await entry.text());

  setStatus("ready", `running ${host.cols}x${host.rows} — press 'a', then ctrl+q to quit`);

  const start = pyodide.globals.get("start");
  const finished = start();

  // Published only once the app is actually driving the terminal, so a harness that waits
  // for it cannot read a half-booted screen.
  // Publishing on the global object is the point here, not an accident: this is the
  // documented surface `scripts/run-browser-check.mjs` drives, and a harness in another
  // realm cannot reach a module-scoped binding.
  // eslint-disable-next-line unicorn/no-global-object-property-assignment
  globalThis.textualWasmSpike = {
    columns: host.cols,
    rows: host.rows,
    screen: () => readScreen(terminal),
    // xterm's supported "as if it came from the user" entry point, so this exercises the
    // same onData path a keystroke does rather than bypassing it.
    input: (data) => terminal.input(data),
    finished,
  };

  await finished;
  setStatus("ready", "app exited cleanly");
}

try {
  await main();
} catch (error) {
  setStatus("failed", `failed: ${error}`);
  throw error;
}
