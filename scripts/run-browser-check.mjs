/**
 * Render the spike in a real browser at a fixed grid and emit the resulting screen as JSON.
 *
 * The Node probe settles the Python side; this settles the half it cannot reach. Textual's
 * output is a rendering instruction, and the open question in the feasibility study is
 * whether a browser terminal emulator executes it the way a terminal does - `xterm.js`'s
 * character-width table is not the one that produced the stream, nor the one `pyte` uses to
 * replay it.
 *
 * Emits `{ runtime, screen }` on stdout, the same `screen` shape a probe report carries, so
 * `textual-wasm-spike compare-screens` can diff the two.
 *
 * Drives an already-installed Chrome through puppeteer-core rather than downloading one:
 * this runs against the browser the result is being claimed for.
 */

import { spawn } from "node:child_process";
import { once } from "node:events";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, "..");

/**
 * Matches the probe's default, so the two grids are directly comparable.
 */
const COLUMNS = Number(process.env.SPIKE_COLUMNS ?? 80);
const ROWS = Number(process.env.SPIKE_ROWS ?? 24);
const PORT = Number(process.env.PORT ?? 8123);

/**
 * Pyodide boot plus a Textual startup is seconds, not milliseconds.
 */
const READY_TIMEOUT_MS = 120_000;

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/usr/bin/google-chrome-stable",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

/**
 * @returns {Promise<string>} path to an installed Chrome.
 */
async function findChrome() {
  const { access } = await import("node:fs/promises");
  for (const candidate of CHROME_CANDIDATES) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  throw new Error(`no Chrome found; tried ${CHROME_CANDIDATES.join(", ")}`);
}

/**
 * Start the project's static server and resolve once it announces its port.
 *
 * @returns {Promise<import("node:child_process").ChildProcess>}
 */
async function startServer() {
  const server = spawn(process.execPath, [path.join(HERE, "serve.mjs")], {
    cwd: PROJECT_ROOT,
    env: { ...process.env, PORT: String(PORT) },
    stdio: ["ignore", "pipe", "inherit"],
  });
  await once(server.stdout, "data");
  return server;
}

/**
 * @param {import("puppeteer-core").Page} page
 * @returns {Promise<{runtime: object, screen: object}>}
 */
async function collect(page) {
  await page.waitForFunction("globalThis.textualWasmSpike !== undefined", {
    timeout: READY_TIMEOUT_MS,
  });

  // Drive the same binding the probe drives, through xterm's own user-input entry point,
  // so the captured screen is of an app that has actually handled input rather than one
  // that merely started.
  await page.evaluate(() => globalThis.textualWasmSpike.input("a"));
  await page.waitForFunction(
    () => globalThis.textualWasmSpike.screen().lines.some((l) => l.includes("pressed 1")),
    { timeout: READY_TIMEOUT_MS },
  );

  return page.evaluate(() => ({
    runtime: {
      user_agent: navigator.userAgent,
      device_pixel_ratio: devicePixelRatio,
      font_family: getComputedStyle(document.documentElement)
        .getPropertyValue("--font-terminal")
        .trim(),
    },
    screen: globalThis.textualWasmSpike.screen(),
  }));
}

async function main() {
  const executablePath = await findChrome();
  const server = await startServer();
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  try {
    const page = await browser.newPage();
    const failures = [];
    page.on("pageerror", (error) => {
      failures.push(String(error));
    });
    page.on("console", (message) => {
      if (message.type() === "error") {
        failures.push(message.text());
      }
    });
    // A console message for a failed request says only "404"; the URL is on the response,
    // and without it the report names a problem nobody can act on.
    page.on("response", (response) => {
      if (response.status() >= 400) {
        failures.push(`HTTP ${response.status()} ${response.url()}`);
      }
    });

    await page.goto(`http://localhost:${PORT}/?cols=${COLUMNS}&rows=${ROWS}`, {
      waitUntil: "domcontentloaded",
    });
    const result = await collect(page);

    if (failures.length > 0) {
      // A browser reports most of its failures to a console nobody is reading. Silence is
      // part of the claim being made here, so it is checked rather than assumed.
      process.stderr.write(`page reported ${failures.length} error(s):\n`);
      for (const failure of failures) {
        process.stderr.write(`  ${failure}\n`);
      }
      process.exitCode = 1;
    }
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } finally {
    await browser.close();
    server.kill();
  }
}

await main();
