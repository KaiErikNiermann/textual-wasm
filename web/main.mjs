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

  // Observe the container rather than the window: the terminal's size is a fact about its
  // box, and a window listener misses every layout change that is not a window resize.
  new ResizeObserver(() => fitAddon.fit()).observe(container);

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

  return { terminal, host, fit: () => fitAddon.fit() };
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
  const { host, fit } = createTerminal();
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
  await start();
  setStatus("ready", "app exited cleanly");
}

try {
  await main();
} catch (error) {
  setStatus("failed", `failed: ${error}`);
  throw error;
}
