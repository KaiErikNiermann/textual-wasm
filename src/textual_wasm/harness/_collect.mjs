/**
 * When an app has finished drawing, and what it drew - defined once for every driver.
 *
 * Two harnesses read the same page through different automation stacks: Playwright for the
 * three engines, WebDriver for real Safari, which Playwright cannot drive. If each decided
 * for itself when the app was "ready", a disagreement between them would be a disagreement
 * about the harness, and the whole point of this comparison is that it is not.
 *
 * The only primitive required of a driver is `evaluate(source)`: run a JavaScript expression
 * in the page and return its value. That is the intersection of what every automation stack
 * offers, so expressions are built as source text rather than passed as functions.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

/**
 * Pyodide boot plus a Textual startup is seconds, not milliseconds - and on WebKit it is
 * tens of seconds, which is why this is generous rather than tight.
 */
export const READY_TIMEOUT_MS = 300_000;

/**
 * How long to keep waiting for the grid to stop changing, and how long a gap counts as
 * stopped. Two frames at Textual's default 60fps is ~33ms; 250 is generous enough that a
 * slow engine is not mistaken for a settled one.
 */
export const SETTLE_TIMEOUT_MS = 30_000;
export const SETTLE_INTERVAL_MS = 250;

const POLL_INTERVAL_MS = 250;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Poll an expression until it is truthy.
 *
 * @param {(source: string) => Promise<unknown>} evaluate
 * @param {string} source JavaScript expression
 * @param {string} description what is being waited for, for the failure message
 */
async function waitFor(evaluate, source, description) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await evaluate(source)) {
      return;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  throw new Error(`timed out waiting for ${description}`);
}

/**
 * Wait until the app's own text is on the grid.
 *
 * The same marker the terminal capture polls a tmux pane for, so "ready" means one thing
 * across every leg of the check rather than one thing per harness.
 *
 * @param {(source: string) => Promise<unknown>} evaluate
 * @param {string} marker
 */
export async function waitForMarker(evaluate, marker) {
  const wanted = JSON.stringify(marker);
  await waitFor(
    evaluate,
    `globalThis.textualWasm.screen().lines.some((line) => line.includes(${wanted}))`,
    `${wanted} to appear on the grid`,
  );
}

/**
 * Wait until the grid stops changing.
 *
 * A marker says the app *reached* a state, not that it has finished drawing it. Textual
 * composes in frames, and on a slower engine a later frame can still be in flight when the
 * marker's frame has landed - measured: WebKit had not yet painted the footer at the moment
 * Chromium had, and the row diff reported that as a rendering divergence between browsers.
 * It was a divergence in how fast they got there.
 *
 * Quiescence is the honest signal, and it degrades gracefully: an app that never settles
 * (a clock, an animation) simply uses the last reading, which is the same screen the
 * comparison would have taken anyway.
 *
 * @param {(source: string) => Promise<unknown>} evaluate
 */
export async function waitForStableGrid(evaluate) {
  let previous = null;
  const deadline = Date.now() + SETTLE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const current = await evaluate(String.raw`globalThis.textualWasm.screen().lines.join("\n")`);
    if (current === previous) {
      return;
    }
    previous = current;
    await sleep(SETTLE_INTERVAL_MS);
  }
}

/**
 * Drive the app to its settled state and read back what it rendered.
 *
 * @param {(source: string) => Promise<unknown>} evaluate
 * @param {object} config the run configuration
 * @returns {Promise<{runtime: object, screen: object}>}
 */
export async function collect(evaluate, config) {
  await waitFor(evaluate, "globalThis.textualWasm !== undefined", "the app to start driving the terminal");
  if (config.target.ready_marker) {
    await waitForMarker(evaluate, config.target.ready_marker);
  }
  if (config.target.keys) {
    // Through xterm's own "as if it came from the user" entry point, so this exercises the
    // same onData path a keystroke does rather than bypassing it.
    await evaluate(`globalThis.textualWasm.input(${JSON.stringify(config.target.keys)})`);
    await waitForMarker(evaluate, config.target.settled_marker);
  }
  await waitForStableGrid(evaluate);

  return evaluate(`({
    runtime: {
      user_agent: navigator.userAgent,
      device_pixel_ratio: devicePixelRatio,
      font_family: getComputedStyle(document.documentElement)
        .getPropertyValue("--font-terminal").trim(),
      shared_array_buffer: typeof SharedArrayBuffer !== "undefined",
      cross_origin_isolated: globalThis.crossOriginIsolated ?? null,
      jspi: typeof WebAssembly.Suspending === "function",
    },
    screen: globalThis.textualWasm.screen(),
  })`);
}

/**
 * Read the run configuration a harness was given.
 *
 * @param {string} script name, for the usage message
 * @returns {object}
 */
export function readConfig(script) {
  const file = process.argv[2];
  if (file === undefined) {
    throw new Error(`usage: node ${script} <config.json>`);
  }
  return JSON.parse(readFileSync(file, "utf8"));
}

/**
 * Load a Node package from wherever the caller's `node_modules` lives.
 *
 * A bare `import "playwright"` would resolve relative to *this* file, which is inside an
 * installed Python package and has no `node_modules` above it. `createRequire` rebases
 * resolution onto a directory the caller chose, so a harness ships with the package and
 * still finds the driver in the user's project.
 *
 * @param {string} resolveFrom directory containing `node_modules`
 * @param {string} name package to load
 */
export function loadFrom(resolveFrom, name) {
  return createRequire(path.join(resolveFrom, "noop.cjs"))(name);
}
