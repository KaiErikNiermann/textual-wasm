/**
 * Render an app in **real Safari** and emit the resulting screen as JSON.
 *
 * Sibling of `browser-check.mjs`, and separate only because Playwright cannot drive Safari:
 * there is no channel for it, and its WebKit is a different port of the engine, built against
 * GTK, with a different font stack and none of Apple's platform limits. That port answers
 * "does this engine run the page"; this one answers "does the browser people actually have".
 *
 * WebDriver through `safaridriver`, which macOS ships and which has to be enabled once with
 * `sudo safaridriver --enable`.
 *
 * The waiting and the reading are not reimplemented here - they come from `_collect.mjs`, so
 * that "the app is ready" means the same thing as it does in every other leg. A disagreement
 * between harnesses would be a disagreement about the harness.
 *
 * One capability is deliberately absent: Safari's WebDriver does not expose console output,
 * so this leg checks what was rendered and not that the console stayed silent. The Playwright
 * legs cover that.
 */

import process from "node:process";

import { collect, loadFrom, readConfig } from "./_collect.mjs";

async function main() {
  const config = readConfig("safari-check.mjs");
  const { Builder } = loadFrom(config.resolveFrom, "selenium-webdriver");
  const driver = await new Builder().forBrowser("safari").build();

  try {
    await driver.manage().window().setRect({ width: 1400, height: 900 });
    await driver.get(`${config.url}?cols=${config.columns}&rows=${config.rows}`);

    // `executeScript` wants a statement; every expression `_collect` builds is safe to return.
    const result = await collect((source) => driver.executeScript(`return (${source});`), config);

    const capabilities = await driver.getCapabilities();
    result.runtime.browser = "safari";
    result.runtime.browser_version = String(capabilities.get("browserVersion") ?? "unknown");
    process.stdout.write(`${JSON.stringify({ target: config.target.entry, ...result }, null, 2)}\n`);
  } finally {
    await driver.quit();
  }
}

await main();
