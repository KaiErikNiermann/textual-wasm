/**
 * Send an application everything a page should not, and record what survived.
 *
 * The assertions live in `test_bridge_errors.py`; this only collects. Split that way so the
 * same run answers for every engine - a case that is a bug in one browser and not another
 * is exactly what a single-engine harness cannot see.
 *
 * The one thing checked *here* rather than there is that the application is still drawing
 * after each case. That is a property of the moment, not of the payload, and it is the
 * claim that matters most: a channel that survives bad input by killing the app has not
 * survived it.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import process from "node:process";

const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
const require = createRequire(`${config.resolveFrom}/`);
const playwright = require("playwright");

const BOOT_TIMEOUT_MS = 300_000;
const REPLY_TIMEOUT_MS = 30_000;

/**
 * Text that only survives a round trip if nothing along the way decodes or rewrites it: a
 * terminal escape the driver's own parser would act on, a null JSON refuses, an
 * right-to-left override, and an astral-plane character that is two UTF-16 units.
 */
const HOSTILE_TEXT = "\u{1B}[31m \u{0} \u{202E} \u{1F600} done";

/**
 * Collect every `report` the application sends, in order.
 */
async function instrument(page) {
  await page.evaluate(() => {
    // The page's realm is the only place a listener registered there can write to.
    // eslint-disable-next-line unicorn/no-global-object-property-assignment
    globalThis.collected = { reports: [], echoes: [], thrown: [] };
    const { bridge } = globalThis.textualWasm;
    bridge.on("report", (value) => {
      globalThis.collected.reports.push(value);
    });
    bridge.onText("echo-back", (text) => {
      globalThis.collected.echoes.push(text);
    });
  });
}

/**
 * @param {import("playwright").Page} page
 * @param {string} bucket
 * @param {number} count
 */
async function waitFor(page, bucket, count) {
  await page.waitForFunction(
    ([name, wanted]) => globalThis.collected[name].length >= wanted,
    [bucket, count],
    { timeout: REPLY_TIMEOUT_MS },
  );
}

/**
 * Whether the application is still drawing, asked the only way that proves it.
 */
async function stillAlive(page) {
  return page.evaluate(() =>
    globalThis.textualWasm.screen().lines.some((line) => line.includes("errors ready")),
  );
}

async function main() {
  const engine = config.browser ?? "chromium";
  const browser = await playwright[engine].launch();
  const consoleErrors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
    page.on("pageerror", (error) => {
      consoleErrors.push(`pageerror: ${error.message}`);
    });
    await page.goto(`${config.url}?cols=80&rows=24`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => globalThis.textualWasm !== undefined, {
      timeout: BOOT_TIMEOUT_MS,
    });
    await page.waitForFunction(
      () => globalThis.textualWasm.screen().lines.some((l) => l.includes("errors ready")),
      { timeout: BOOT_TIMEOUT_MS },
    );
    await instrument(page);

    // 1. The page refuses to put a non-string on the wire, at the call site.
    const refusedAtCallSite = await page.evaluate(() => {
      const { bridge } = globalThis.textualWasm;
      const attempts = new Map();
      const record = (name, action) => {
        try {
          action();
          attempts.set(name, null);
        } catch (error) {
          attempts.set(name, `${error.constructor.name}: ${error.message}`);
        }
      };
      record("sendUndefined", () => bridge.send("loose", globalThis.nothing));
      record("sendTextUndefined", () => bridge.sendText("loose", globalThis.nothing));
      record("sendTextNumber", () => bridge.sendText("loose", 42));
      record("sendTextMissing", () => bridge.sendText("loose"));
      return Object.fromEntries(attempts);
    });

    // 2. Malformed JSON on a bound channel: dropped, app alive, nothing else affected.
    await page.evaluate(() => {
      globalThis.textualWasm.bridge.sendText("loose", "{not json");
    });
    await page.evaluate(() => globalThis.textualWasm.bridge.sendText("probe", ""));
    await waitFor(page, "reports", 1);
    const afterMalformed = await page.evaluate(() => globalThis.collected.reports.at(-1));
    const aliveAfterMalformed = await stillAlive(page);

    // 3. The wrong type, with and without a validator.
    await page.evaluate(() => {
      const { bridge } = globalThis.textualWasm;
      bridge.send("loose", "not a number");
      bridge.send("strict", "not a number");
    });
    await page.evaluate(() => globalThis.textualWasm.bridge.sendText("probe", ""));
    await waitFor(page, "reports", 2);
    const afterWrongType = await page.evaluate(() => globalThis.collected.reports.at(-1));

    // 4. A validator that can convert does, rather than rejecting.
    await page.evaluate(() => {
      globalThis.textualWasm.bridge.send("strict", "17");
      globalThis.textualWasm.bridge.sendText("probe", "");
    });
    await waitFor(page, "reports", 3);
    const afterCoercible = await page.evaluate(() => globalThis.collected.reports.at(-1));

    // 5. What `message.data` raises, and whether it names its channel.
    await page.evaluate(() => {
      globalThis.textualWasm.bridge.sendText("decode", "{not json");
    });
    await waitFor(page, "reports", 4);
    const decodeError = await page.evaluate(() => globalThis.collected.reports.at(-1));

    // 6. What the application cannot send, and what stops it.
    await page.evaluate(() => globalThis.textualWasm.bridge.sendText("send-bad", ""));
    await waitFor(page, "reports", 5);
    const sendBad = await page.evaluate(() => globalThis.collected.reports.at(-1));

    // 7. Hostile text survives the raw pipe unchanged, in both directions.
    await page.evaluate((text) => {
      globalThis.textualWasm.bridge.sendText("echo", text);
    }, HOSTILE_TEXT);
    await waitFor(page, "echoes", 1);
    const echoed = await page.evaluate(() => globalThis.collected.echoes.at(-1));

    // 8. A large payload crosses intact.
    const large = await page.evaluate(async () => {
      const payload = "y".repeat(2 * 1024 * 1024);
      const before = globalThis.collected.echoes.length;
      globalThis.textualWasm.bridge.sendText("echo", payload);
      const deadline = performance.now() + 30_000;
      while (globalThis.collected.echoes.length === before && performance.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      const echoed = globalThis.collected.echoes.at(-1);
      return { sent: payload.length, echoed: echoed ? echoed.length : 0 };
    });

    // 9. Coalescing keeps the newest and drops the rest.
    const coalescing = await page.evaluate(async () => {
      const { bridge } = globalThis.textualWasm;
      const before = globalThis.collected.reports.length;
      // A synchronous loop never yields, so the frame this schedules fires once, after it.
      for (let index = 0; index < 500; index += 1) {
        bridge.sendLatest("loose", index);
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
      bridge.sendText("probe", "");
      const deadline = performance.now() + 30_000;
      while (globalThis.collected.reports.length <= before && performance.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 20));
      }
      return globalThis.collected.reports.at(-1);
    });

    // 10. Still drawing, after all of it.
    const aliveAtEnd = await stillAlive(page);


    const result = {
      engine,
      worker: Boolean(config.worker),
      refusedAtCallSite,
      afterMalformed,
      aliveAfterMalformed,
      afterWrongType,
      afterCoercible,
      decodeError,
      sendBad,
      echoed,
      echoSent: HOSTILE_TEXT,
      large,
      coalescing,
      aliveAtEnd,
      pageErrors: consoleErrors,
    };

    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } finally {
    await browser.close();
  }
}

await main();
