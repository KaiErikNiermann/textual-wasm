/**
 * Measure whether the page stays responsive while Python blocks.
 *
 * This is the one claim worker mode makes that the render comparison cannot test. `check`
 * proves a worker build draws the same cells as a terminal; it says nothing about the
 * reason for building one, which is that a slow Python call should stop freezing the tab.
 *
 * The method is deliberately blunt, because the effect is enormous and a subtle metric
 * would only add ways to be wrong. A `requestAnimationFrame` loop counts frames on the main
 * thread while the application runs a synchronous busy loop. A thread that is blocked
 * renders no frames at all - not fewer frames, none - so the two modes are separated by a
 * gap no timing noise can close.
 *
 * Emits `{ runtime, frames, longestGapMs, blockedMs }`.
 */

import process from "node:process";

import { READY_TIMEOUT_MS, loadFrom, readConfig, waitForMarker } from "./_collect.mjs";

/**
 * How long to keep sampling after the key is sent, in milliseconds. The fixture's busy loop
 * is about a second; this needs to outlast it, and a run that ends early would understate
 * the worker case and flatter the main-thread one, so erring long is the safe direction.
 */
const SAMPLE_WINDOW_MS = 6000;

/**
 * Count animation frames on the main thread across a window of time.
 *
 * Installed as one page function rather than polled from the driver, because every round
 * trip to the driver is itself a task on the page's event loop - measuring from outside
 * would keep the thread alive and hide exactly the freeze being measured.
 *
 * @param {import("playwright").Page} page
 * @param {string} keys the keystrokes that trigger the blocking call
 * @returns {Promise<{frames: number, longestGapMs: number, blockedMs: number}>}
 */
async function measure(page, keys) {
  return page.evaluate(
    async ({ keys: sendKeys, window: windowMs }) => {
      const gaps = [];
      let last = performance.now();
      let isSampling = true;
      const tick = (now) => {
        if (!isSampling) {
          return;
        }
        gaps.push(now - last);
        last = now;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);

      // Let the sampler establish a baseline before the app is asked to block, so a slow
      // first frame after page load is not counted as part of the blocked window.
      await new Promise((resolve) => setTimeout(resolve, 250));
      gaps.length = 0;
      last = performance.now();

      const started = performance.now();
      globalThis.textualWasm.input(sendKeys);
      await new Promise((resolve) => setTimeout(resolve, windowMs));
      isSampling = false;

      return {
        frames: gaps.length,
        longestGapMs: gaps.length === 0 ? null : Math.max(...gaps),
        blockedMs: performance.now() - started,
      };
    },
    { keys, window: SAMPLE_WINDOW_MS },
  );
}

async function main() {
  const config = readConfig("responsiveness.mjs");
  const playwright = loadFrom(config.resolveFrom, "playwright");
  const browser = await playwright.chromium.launch();

  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    await page.goto(`${config.url}?cols=${config.columns}&rows=${config.rows}`, {
      waitUntil: "domcontentloaded",
    });
    // The same readiness rule the render harness uses, so a blank half-booted page cannot
    // be mistaken for a responsive one.
    await page.waitForFunction(() => globalThis.textualWasm !== undefined, {
      timeout: READY_TIMEOUT_MS,
    });
    if (config.target.ready_marker) {
      await waitForMarker((source) => page.evaluate(source), config.target.ready_marker);
    }

    const result = await measure(page, config.keys);
    process.stdout.write(
      `${JSON.stringify({ runtime: { worker: Boolean(config.worker) }, ...result }, null, 2)}\n`,
    );
  } finally {
    await browser.close();
  }
}

await main();
