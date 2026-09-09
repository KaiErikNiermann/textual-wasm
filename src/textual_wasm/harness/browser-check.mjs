/**
 * Render an app in a real browser at a fixed grid and emit the resulting screen as JSON.
 *
 * The Node probe settles the Python side; this settles the half it cannot reach. Textual's
 * output is a rendering instruction, and the open question in the feasibility study is
 * whether a browser terminal emulator executes it the way a terminal does - `xterm.js`'s
 * character-width table is not the one that produced the stream, nor the one `pyte` uses to
 * replay it.
 *
 * Emits `{ runtime, screen }` on stdout, the same `screen` shape a probe report carries, so
 * `textual-wasm compare-screens` can diff it against the terminal reference.
 *
 * Drives an already-installed Chrome through puppeteer-core rather than downloading one:
 * this runs against the browser the result is being claimed for.
 *
 * The page it visits was produced by a real `textual-wasm build` and is served by a real
 * `textual-wasm dev`, both started by the Python side. Checking something other than what
 * ships is how a harness comes to pass while the product is broken.
 */

import { access } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

/**
 * Pyodide boot plus a Textual startup is seconds, not milliseconds.
 */
const READY_TIMEOUT_MS = 120_000;

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/usr/bin/google-chrome-stable",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
];

/**
 * @returns {object} the run configuration, named by argv[2].
 */
function readConfig() {
  const file = process.argv[2];
  if (file === undefined) {
    throw new Error("usage: node browser-check.mjs <config.json>");
  }
  return JSON.parse(readFileSync(file, "utf8"));
}

/**
 * Load a Node package from wherever the caller's `node_modules` lives. See the sibling
 * harness for why a bare specifier cannot work from inside an installed Python package.
 *
 * @param {string} resolveFrom directory containing `node_modules`
 * @param {string} name package to load
 */
function loadFrom(resolveFrom, name) {
  return createRequire(path.join(resolveFrom, "noop.cjs"))(name);
}

/**
 * @param {string | undefined} configured
 * @returns {Promise<string>} path to an installed Chrome.
 */
async function findChrome(configured) {
  const candidates = [configured, ...CHROME_CANDIDATES].filter(Boolean);
  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  throw new Error(`no Chrome found; tried ${candidates.join(", ")}`);
}

/**
 * Wait until the app's own text is on the grid.
 *
 * The same marker the terminal capture polls a tmux pane for, so "ready" means one thing
 * across every leg of the check rather than one thing per harness.
 *
 * @param {import("puppeteer-core").Page} page
 * @param {string} marker
 */
async function waitForMarker(page, marker) {
  await page.waitForFunction(
    (wanted) => globalThis.textualWasm.screen().lines.some((line) => line.includes(wanted)),
    { timeout: READY_TIMEOUT_MS },
    marker,
  );
}

/**
 * @param {import("puppeteer-core").Page} page
 * @param {object} config
 * @returns {Promise<{runtime: object, screen: object}>}
 */
async function collect(page, config) {
  await page.waitForFunction("globalThis.textualWasm !== undefined", {
    timeout: READY_TIMEOUT_MS,
  });
  if (config.target.ready_marker) {
    await waitForMarker(page, config.target.ready_marker);
  }

  if (config.target.keys) {
    // Through xterm's own "as if it came from the user" entry point, so this exercises the
    // same onData path a keystroke does rather than bypassing it.
    await page.evaluate((keys) => globalThis.textualWasm.input(keys), config.target.keys);
    await waitForMarker(page, config.target.settled_marker);
  }

  return page.evaluate(() => ({
    runtime: {
      user_agent: navigator.userAgent,
      device_pixel_ratio: devicePixelRatio,
      font_family: getComputedStyle(document.documentElement)
        .getPropertyValue("--font-terminal")
        .trim(),
    },
    screen: globalThis.textualWasm.screen(),
  }));
}

/**
 * Watch every channel a browser reports failure on.
 *
 * Silence is part of the claim being made here, so it is checked rather than assumed - and
 * a console message for a failed request says only "404", with the URL on the response, so
 * without this the report names a problem nobody can act on.
 *
 * @param {import("puppeteer-core").Page} page
 * @returns {string[]} the accumulating failure list
 */
function watchForFailures(page) {
  const failures = [];
  page.on("pageerror", (error) => {
    failures.push(String(error));
  });
  page.on("console", (message) => {
    if (message.type() === "error") {
      failures.push(message.text());
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failures.push(`HTTP ${response.status()} ${response.url()}`);
    }
  });
  return failures;
}

/**
 * Check that the grid the page chose for itself fits inside its frame.
 *
 * A separate page load, without the forced-grid query parameters, because forcing a grid is
 * exactly what bypasses `FitAddon` - so every other assertion here runs on the one
 * configuration in which a sizing bug cannot appear. It did appear: the frame's padding and
 * border were counted as room for text, and the last two rows of every app - where Textual
 * draws its footer - were rendered outside the visible box.
 *
 * Pyodide is not waited for. The page sizes the terminal before it boots one.
 *
 * @param {import("puppeteer-core").Browser} browser
 * @param {string} url
 * @returns {Promise<number>} pixels by which the grid overflows its frame; <= 0 is correct.
 */
async function measureFit(browser, url) {
  const page = await browser.newPage();
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#terminal[data-fitted]", { timeout: READY_TIMEOUT_MS });
    return await page.evaluate(() => {
      const frame = document.querySelector(".terminal-frame").getBoundingClientRect();
      const grid = document.querySelector("#terminal .xterm").getBoundingClientRect();
      return Math.round(Math.max(grid.bottom - frame.bottom, grid.right - frame.right));
    });
  } finally {
    await page.close();
  }
}

async function main() {
  const config = readConfig();
  const puppeteer = loadFrom(config.resolveFrom, "puppeteer-core");
  const browser = await puppeteer.launch({
    executablePath: await findChrome(config.chromePath),
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  try {
    const page = await browser.newPage();
    const failures = watchForFailures(page);
    await page.goto(`${config.url}?cols=${config.columns}&rows=${config.rows}`, {
      waitUntil: "domcontentloaded",
    });
    const result = await collect(page, config);

    const overflow = await measureFit(browser, config.url);
    if (overflow > 0) {
      failures.push(`the terminal overflows its frame by ${overflow}px when it sizes itself`);
    }

    if (failures.length > 0) {
      process.stderr.write(`page reported ${failures.length} error(s):\n`);
      for (const failure of failures) {
        process.stderr.write(`  ${failure}\n`);
      }
      process.exitCode = 1;
    }
    process.stdout.write(`${JSON.stringify({ target: config.target.entry, ...result }, null, 2)}\n`);
  } finally {
    await browser.close();
  }
}

await main();
