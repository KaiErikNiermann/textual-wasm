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
 *
 * Runs against a real `textual-wasm build`, served by `textual-wasm dev`, rather than a
 * bespoke harness server. Checking something other than what ships is how a harness comes to
 * pass while the product is broken.
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

const SITE = path.join(PROJECT_ROOT, "artifacts", "browser-check-site");
const ENTRY = "textual_wasm.app:SpikeApp";

/**
 * Run a project command to completion.
 *
 * @param {string[]} command
 * @returns {Promise<void>}
 */
async function run(command) {
  // A developer harness invoking this project's own tooling from the developer's own PATH.
  // eslint-disable-next-line sonarjs/no-os-command-from-path
  const child = spawn("poetry", ["run", ...command], {
    cwd: PROJECT_ROOT,
    stdio: ["ignore", "ignore", "inherit"],
  });
  const [code] = await once(child, "exit");
  if (code !== 0) {
    throw new Error(`${command.join(" ")} exited ${code}`);
  }
}

/**
 * Build the site and serve it, resolving once it answers.
 *
 * @returns {Promise<import("node:child_process").ChildProcess>}
 */
async function startServer() {
  await run(["textual-wasm", "build", ENTRY, "src/textual_wasm", "-o", SITE]);
  // Same as above: the project's own CLI, from the developer's own PATH.
  // eslint-disable-next-line sonarjs/no-os-command-from-path
  const server = spawn("poetry", ["run", "textual-wasm", "dev", SITE, "-p", String(PORT)], {
    cwd: PROJECT_ROOT,
    stdio: ["ignore", "ignore", "inherit"],
  });
  // The server prints through rich, so its output is not a reliable readiness signal;
  // asking it for the manifest is.
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`http://localhost:${PORT}/app.json`);
      if (response.ok) {
        return server;
      }
    } catch {
      // not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  server.kill();
  throw new Error(`build server never answered on port ${PORT}`);
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
