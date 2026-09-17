/**
 * Drive every direction of the data channel in a real browser, in one run.
 *
 * The claim worth measuring is not that a message arrives - a unit test with a fake page
 * shows that - but that the *same* Python code behaves identically whether the interpreter
 * is on this thread or in a worker. So this harness knows nothing about either mode: it is
 * pointed at a build, it exercises the channel through the page's own public surface, and
 * the caller runs it twice.
 *
 * Emits `{ runtime, initial, applied, echoed, fromApp }`.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import process from "node:process";

const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(`${config.resolveFrom}/`);
const playwright = require("playwright");

/**
 * Pyodide boot plus a Textual startup is seconds, and tens of them on a slow engine.
 */
const READY_TIMEOUT_MS = 300_000;

/**
 * How long to wait for a message once the application is already running.
 *
 * Far shorter than the boot budget on purpose: after the app is drawing, a message either
 * crosses in milliseconds or is never coming, and spending five minutes finding that out
 * turns one broken direction into a run nobody waits for.
 */
const MESSAGE_TIMEOUT_MS = 30_000;

/**
 * Text that survives the pipe only if nothing along the way tries to interpret it: an
 * escape sequence the terminal leg would act on, and a null a JSON decoder would refuse.
 */
const RAW_PAYLOAD = "not json \u{1B}[31m \u{0} done";

/**
 * Install a recorder for one channel before anything is sent on it.
 *
 * Subscribing from the page side rather than polling, because "did this arrive" is the
 * question and a poll would answer "did this arrive eventually" - which is also true of a
 * message that arrived for the wrong reason.
 *
 * @param {import("playwright").Page} page
 */
async function record(page) {
  await page.evaluate(() => {
    // A global because it lives in the page's realm, which is the only place a listener
    // registered there can write to and a later `evaluate` can read from.
    // eslint-disable-next-line unicorn/no-global-object-property-assignment
    globalThis.seen = { gain: [], "echo-back": [] };
    for (const channel of Object.keys(globalThis.seen)) {
      globalThis.textualWasm.bridge.onText(channel, (text) => {
        globalThis.seen[channel].push(text);
      });
    }
  });
}

/**
 * @param {import("playwright").Page} page
 * @param {string} channel
 * @param {number} count how many payloads to wait for
 * @returns {Promise<string[]>}
 */
async function waitForPayloads(page, channel, count) {
  await page.waitForFunction(
    ([name, wanted]) => globalThis.seen[name].length >= wanted,
    [channel, count],
    { timeout: MESSAGE_TIMEOUT_MS },
  );
  return page.evaluate((name) => globalThis.seen[name], channel);
}

/**
 * The first trimmed line on the grid starting with `prefix`, or null.
 *
 * @param {import("playwright").Page} page
 * @param {string} prefix
 * @returns {Promise<string | null>}
 */
async function gridLine(page, prefix) {
  return page.evaluate(
    (wanted) =>
      globalThis.textualWasm
        .screen()
        .lines.map((line) => line.trim())
        .find((line) => line.startsWith(wanted)) ?? null,
    prefix,
  );
}

async function main() {
  const browser = await playwright.chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    await page.goto(`${config.url}?cols=80&rows=24`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => globalThis.textualWasm !== undefined, {
      timeout: READY_TIMEOUT_MS,
    });
    await record(page);

    // 1. app -> page, unprompted: `bind(initial=True)` publishes the app's state on mount.
    // The relay is what makes this observable at all - the send happens while this thread
    // is still installing the listener above.
    const initial = await waitForPayloads(page, "gain", 1);

    // 2. page -> app, through a binding: the slider case.
    await page.evaluate(() => globalThis.textualWasm.bridge.send("gain", 42));
    await page.waitForFunction(
      () => globalThis.textualWasm.screen().lines.some((line) => line.includes("gain=42")),
      { timeout: MESSAGE_TIMEOUT_MS },
    );
    const applied = await gridLine(page, "gain=");

    // 3. the raw pipe, round trip, with text that only survives if nothing decodes it.
    await page.evaluate((payload) => {
      globalThis.textualWasm.bridge.sendText("echo", payload);
    }, RAW_PAYLOAD);
    const echoed = await waitForPayloads(page, "echo-back", 1);

    // 4. app -> page on a change the page did not cause, so an echo cannot explain it.
    // One more payload than has arrived so far, not two: the value this page sent in step 2
    // is deliberately not echoed back, and expecting it would be waiting for a bug.
    await page.evaluate(() => globalThis.textualWasm.input("u"));
    const fromApp = await waitForPayloads(page, "gain", initial.length + 1);

    process.stdout.write(
      `${JSON.stringify(
        {
          runtime: { worker: Boolean(config.worker) },
          sent: RAW_PAYLOAD,
          initial,
          applied,
          echoed,
          fromApp,
        },
        null,
        2,
      )}\n`,
    );
  } finally {
    await browser.close();
  }
}

await main();
