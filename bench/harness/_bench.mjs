/**
 * What every benchmark scenario needs: a browser whose processes can be measured, a page
 * brought to a known state, and readings taken the same way each time.
 *
 * The browser is started with `launchServer` and then connected to, rather than launched
 * directly, for one reason: a server exposes its process id, and the process tree is the
 * only place CPU time and resident memory can be read for every engine alike. The page's
 * own APIs see one thread; the tree sees the renderer, the GPU process and any worker.
 */

import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

/**
Pyodide boot plus a Textual startup, generously, for the slowest engine.
*/
export const READY_TIMEOUT_MS = 300_000;

/**
Once the app is running, a reply either arrives quickly or is not coming.
*/
export const REPLY_TIMEOUT_MS = 120_000;

/**
 * Load a Node package from the caller's `node_modules`, as the packaged harnesses do.
 *
 * @param {string} resolveFrom directory containing `node_modules`
 * @param {string} name
 */
export function loadFrom(resolveFrom, name) {
  return createRequire(path.join(resolveFrom, "noop.cjs"))(name);
}

/**
 * Read the run configuration this harness was given.
 *
 * @returns {Promise<object>}
 */
export async function readConfig() {
  const file = process.argv[2];
  if (file === undefined) {
    throw new Error("usage: node bench.mjs <config.json>");
  }
  return JSON.parse(await readFile(file, "utf8"));
}

/**
 * Start `engine` as a server and connect to it.
 *
 * @param {object} config needs `resolveFrom` and `engine`
 * @returns {Promise<{browser: object, pid: number, close: () => Promise<void>, tree: object}>}
 */
export async function launch(config) {
  const playwright = loadFrom(config.resolveFrom, "playwright");
  const { pidtree } = loadFrom(config.resolveFrom, "pidtree");
  const pidusage = loadFrom(config.resolveFrom, "pidusage");
  const type = playwright[config.engine];
  const server = await type.launchServer();
  const pid = server.process().pid;
  const browser = await type.connect(server.wsEndpoint());
  return {
    browser,
    pid,
    tree: () => sampleTree(pid, { pidtree, pidusage }),
    close: async () => {
      await browser.close();
      await server.close();
    },
  };
}

/**
 * Proportional set size of one process, in bytes, or null where it cannot be read.
 *
 * Resident size double-counts every page shared between a browser's processes - the same
 * libraries mapped into six of them read as six copies - so summing it over the tree
 * overstates the browser by a large and engine-dependent amount. PSS divides each shared
 * page between the processes sharing it, so it sums to what the tree really holds. Linux
 * only; elsewhere this is null and the RSS sum is the number on offer.
 *
 * @param {number} pid
 * @returns {Promise<number | null>}
 */
async function proportionalSet(pid) {
  try {
    const rollup = await readFile(`/proc/${pid}/smaps_rollup`, "utf8");
    const match = /^Pss:\s+(\d+) kB$/m.exec(rollup);
    return match === null ? null : Number(match[1]) * 1024;
  } catch {
    return null;
  }
}

/**
 * CPU time and memory, summed over the browser process and everything it spawned.
 *
 * A process that exits between listing and reading is skipped rather than failing the
 * sample: browsers start and stop helper processes on their own schedule.
 *
 * @param {number} pid
 * @param {{pidtree: Function, pidusage: Function}} libraries
 * @returns {Promise<{cpuMs: number, rssBytes: number, pssBytes: number | null,
 *   processes: number}>}
 */
async function sampleTree(pid, { pidtree, pidusage }) {
  const pids = [pid, ...(await pidtree(pid))];
  const totals = { cpuMs: 0, rssBytes: 0, pssBytes: 0, processes: 0 };
  let isPssComplete = true;
  for (const child of pids) {
    let usage;
    try {
      usage = await pidusage(child);
    } catch {
      continue;
    }
    totals.cpuMs += usage.ctime;
    totals.rssBytes += usage.memory;
    totals.processes += 1;
    const pss = await proportionalSet(child);
    if (pss === null) {
      isPssComplete = false;
    } else {
      totals.pssBytes += pss;
    }
  }
  pidusage.clear();
  return { ...totals, pssBytes: isPssComplete ? totals.pssBytes : null };
}

/**
 * Chromium's own accounting for the page's main thread, through the DevTools protocol.
 *
 * Only Chromium has it, so every caller treats a null as "not measured" rather than zero.
 * It answers a question the process tree cannot: of the CPU the renderer spent, how much
 * was script, style, layout or paint. It sees the page's main thread only - a worker's
 * time shows in the process tree and not here, which is itself an attribution.
 *
 * @param {object} context
 * @param {object} page
 * @param {string} engine
 */
export async function devtools(context, page, engine) {
  if (engine !== "chromium") {
    return null;
  }
  const session = await context.newCDPSession(page);
  await session.send("Performance.enable");
  return {
    /**
    Cumulative main-thread durations in milliseconds, and the JS heap in bytes.
    */
    async metrics() {
      const { metrics } = await session.send("Performance.getMetrics");
      const named = Object.fromEntries(metrics.map(({ name, value }) => [name, value]));
      return {
        taskMs: named.TaskDuration * 1000,
        scriptMs: named.ScriptDuration * 1000,
        layoutMs: named.LayoutDuration * 1000,
        styleMs: named.RecalcStyleDuration * 1000,
      };
    },
    /**
    The page's JS heap after a forced full collection, so garbage is not counted.
    */
    async heap() {
      await session.send("HeapProfiler.collectGarbage");
      const { usedSize, totalSize } = await session.send("Runtime.getHeapUsage");
      return { usedBytes: usedSize, totalBytes: totalSize };
    },
  };
}

/**
 * Open `url` and wait until it is running: the app's text on the grid, or a baseline's
 * ready flag.
 *
 * @param {object} page
 * @param {string} url
 * @param {string | null} readyText text the app draws once mounted; null for a baseline
 */
export async function openReady(page, url, readyText) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  if (url.startsWith("about:")) {
    return;
  }
  if (readyText === null) {
    await page.waitForFunction(() => globalThis.baselineReady !== undefined, null, {
      timeout: READY_TIMEOUT_MS,
    });
    const state = await page.evaluate(() => globalThis.baselineReady);
    if (state !== true) {
      throw new Error(`baseline failed: ${state}`);
    }
    return;
  }
  await page.waitForFunction(
    (text) =>
      globalThis.textualWasm !== undefined &&
      globalThis.textualWasm.screen().lines.some((line) => line.includes(text)),
    readyText,
    { timeout: READY_TIMEOUT_MS },
  );
}

/**
 * The boot marks the page left, relative to navigation start, in milliseconds.
 *
 * @param {object} page
 * @returns {Promise<Record<string, number>>}
 */
export async function bootMarks(page) {
  return page.evaluate(() => {
    const marks = Object.fromEntries(
      performance
        .getEntriesByType("mark")
        .filter(({ name }) => name.startsWith("textual-wasm:"))
        .map(({ name, startTime }) => [name.slice("textual-wasm:".length), startTime]),
    );
    const [navigation] = performance.getEntriesByType("navigation");
    if (navigation !== undefined) {
      marks.domContentLoaded = navigation.domContentLoadedEventEnd;
    }
    return marks;
  });
}

/**
 * Install the page-side client every bridge scenario drives the app through.
 *
 * Timing loops run inside the page, never from here: a round trip from Node to the page is
 * itself milliseconds, and measured from outside a 0.1ms channel would read as the
 * automation protocol's latency.
 *
 * @param {object} page
 */
export async function installClient(page) {
  await page.evaluate((replyTimeout) => {
    const queues = new Map();
    const waiters = new Map();
    const push = (channel, text) => {
      const waiting = waiters.get(channel);
      if (waiting !== undefined && waiting.length > 0) {
        waiting.shift()(text);
        return;
      }
      const queued = queues.get(channel) ?? [];
      queued.push(text);
      queues.set(channel, queued);
    };
    const { bridge } = globalThis.textualWasm;
    for (const channel of ["echo-back", "flood-done", "bench-reply"]) {
      bridge.onText(channel, (text) => push(channel, text));
    }
    /**
    The next payload on `channel`, whether it already arrived or not.
    */
    const next = (channel) => {
      const queued = queues.get(channel);
      if (queued !== undefined && queued.length > 0) {
        return Promise.resolve(queued.shift());
      }
      return new Promise((resolve, reject) => {
        const waiting = waiters.get(channel) ?? [];
        waiting.push(resolve);
        waiters.set(channel, waiting);
        setTimeout(() => reject(new Error(`no reply on ${channel}`)), replyTimeout);
      });
    };
    // eslint-disable-next-line unicorn/no-global-object-property-assignment
    globalThis.benchClient = {
      next,
      async command(request) {
        bridge.sendText("bench", JSON.stringify(request));
        return JSON.parse(await next("bench-reply"));
      },
    };
  }, REPLY_TIMEOUT_MS);
}

/**
 * The interpreter's own memory counters, from inside Python.
 *
 * @param {object} page
 */
export async function interpreterMemory(page) {
  return page.evaluate(() => globalThis.benchClient.command({ op: "stats" }));
}

/**
@param {number} ms
*/
export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
