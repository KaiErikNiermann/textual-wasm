/**
 * The layers under an application, brought up one at a time, for attributing its cost.
 *
 * A number measured against the full page says what the page costs. It does not say whether
 * that cost is the browser, the interpreter, Textual, or this project's driver, and those
 * have different owners and different fixes. Each level here is one more layer than the one
 * before it, built from the same pieces the real page uses (`boot.mjs` is the shipped file),
 * so the difference between two adjacent levels is what the added layer costs:
 *
 * - `pyodide`: an interpreter, booted, running nothing.
 * - `textual`: the build's requirements installed and Textual imported, still running nothing.
 * - `tick`: the above plus one asyncio task waking every 50ms, which is exactly the timer
 *   `textual_wasm.driver` keeps while an app runs and nothing else of it.
 *
 * The application itself is the next level up, and is the real page rather than a copy.
 */

import { importPyodide, installPackages, installRequirements, readManifest } from "./boot.mjs";

/**
 * The driver's parser tick, isolated: the same interval, doing the same nothing.
 * `textual_wasm.driver._TICK_INTERVAL` is the value this restates.
 */
const TICK_SOURCE = `
import asyncio

async def _tick():
    while True:
        await asyncio.sleep(0.05)

_task = asyncio.ensure_future(_tick())
`;

const LEVELS = new Set(["pyodide", "textual", "tick"]);

/**
 * Bring the interpreter up to `level` and leave it there.
 *
 * @param {string} level one of `pyodide`, `textual`, `tick`
 * @param {string | URL} manifestUrl the build's `app.json`
 * @returns {Promise<void>} resolves once the level is reached
 */
export async function bringUp(level, manifestUrl) {
  if (!LEVELS.has(level)) {
    throw new Error(`unknown baseline level ${level}`);
  }
  const manifest = await readManifest(manifestUrl);
  const loadPyodide = await importPyodide(manifest);
  const pyodide = await loadPyodide({ indexURL: manifest.pyodideIndexUrl });
  // Kept reachable: a level that is garbage-collected away measures less than it claims.
  // eslint-disable-next-line unicorn/no-global-object-property-assignment
  globalThis.baselinePyodide = pyodide;
  if (level === "pyodide") {
    return;
  }
  await pyodide.loadPackage("micropip");
  // The page's own install, retry included, so a baseline fails no more often than the app.
  await installRequirements(pyodide, manifest.requirements);
  const sources = await fetch(manifest.sourcesUrl);
  installPackages(pyodide, await sources.json());
  await pyodide.runPythonAsync("import textual.app\nimport rich.console\n");
  if (level === "tick") {
    await pyodide.runPythonAsync(TICK_SOURCE);
  }
}
