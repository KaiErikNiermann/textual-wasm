/**
 * Run one benchmark scenario in a fresh browser and print what it measured as JSON.
 *
 * One scenario per process, and a new browser for each: memory readings taken after an
 * earlier scenario would carry that scenario's leftovers, and a run that is interrupted
 * resumes at the scenario it lost rather than at the start. The Python side
 * (`textual_wasm_bench`) decides what to run and aggregates; this decides nothing.
 *
 * Config: `{ resolveFrom, engine, url, readyText, probe, scenario, params }`, where
 * `readyText` is null for a baseline page and `probe` says whether the page runs the
 * benchmark app and so answers on the data channel.
 *
 * Emits `{ engine, browserVersion, scenario, data }`.
 */

import process from "node:process";

import {
  bootMarks,
  devtools,
  installClient,
  interpreterMemory,
  launch,
  openReady,
  readConfig,
  sleep,
} from "./_bench.mjs";

/**
The grid every page is forced to, so a render costs the same in every run.
*/
const GRID = "cols=80&rows=24";

/**
 * @param {string} url
 */
function withGrid(url) {
  if (url.startsWith("about:")) {
    return url;
  }
  return `${url}${url.includes("?") ? "&" : "?"}${GRID}`;
}

/**
 * Everything that can be said about memory at this moment, from every vantage point.
 *
 * @param {object} session
 * @param {object} page
 * @param {object | null} tools
 * @param {boolean} hasProbe whether the page runs the benchmark app
 */
async function memory(session, page, tools, hasProbe) {
  // The page heap first: it forces a collection, which the process reading should follow.
  const heap = tools === null ? null : await tools.heap();
  const tree = await session.tree();
  const interpreter = hasProbe ? await interpreterMemory(page) : null;
  return { tree, heap, interpreter };
}

/**
 * Record how much the app had written at the moment the page published `textualWasm`.
 *
 * Runs in the page before any of its scripts, and traps the assignment itself, so the reading
 * is taken at publication rather than at whenever a poll next looked. The page promises that
 * the surface appears only once the app has drawn; a main-thread page once published it
 * ~600ms before the first frame, and this is the number that showed it - zero.
 */
function capturePublication() {
  let published;
  Object.defineProperty(globalThis, "textualWasm", {
    configurable: true,
    get: () => published,
    set(value) {
      published = value;
      // eslint-disable-next-line unicorn/no-global-object-property-assignment
      globalThis.benchWritesAtPublish = value?.output?.().writes ?? null;
    },
  });
}

/**
 * Time from navigation to running, split by boot phase, then the memory of the settled page.
 *
 * `warm` loads the page once and measures a reload, so the interpreter and the wheels come
 * from the HTTP cache: the cost of a second visit rather than a first.
 */
async function boot({ session, context, page, config }) {
  const url = withGrid(config.url);
  await context.addInitScript(capturePublication);
  if (config.params.warm) {
    // The first load fills the HTTP cache; the second, navigated to the same way, is timed.
    await openReady(page, url, config.readyText);
  }
  await openReady(page, url, config.readyText);
  const marks = await bootMarks(page);
  const writesAtPublish = await page.evaluate(() => globalThis.benchWritesAtPublish ?? null);
  await sleep(config.params.settleMs);
  const tools = await devtools(context, page, config.engine);
  if (config.probe) {
    await installClient(page);
  }
  return { marks, writesAtPublish, memory: await memory(session, page, tools, config.probe) };
}

/**
Read every idle counter at once, so a window's two ends are comparable.
*/
async function idleReading(session, page, tools, hasOutput) {
  return {
    tree: await session.tree(),
    devtools: tools === null ? null : await tools.metrics(),
    output: hasOutput ? await page.evaluate(() => globalThis.textualWasm.output()) : null,
    at: performance.now(),
  };
}

/**
 * What the page costs while nobody touches it: CPU over a window, and what it redrew.
 */
async function idle({ session, context, page, config }) {
  await openReady(page, withGrid(config.url), config.readyText);
  await sleep(config.params.settleMs);
  const tools = await devtools(context, page, config.engine);
  const hasOutput = config.readyText !== null;
  const before = await idleReading(session, page, tools, hasOutput);
  await sleep(config.params.windowMs);
  const after = await idleReading(session, page, tools, hasOutput);
  const delta = (pick) => (pick(before) === null ? null : pick(after) - pick(before));
  return {
    windowMs: after.at - before.at,
    cpuMs: after.tree.cpuMs - before.tree.cpuMs,
    processes: after.tree.processes,
    mainThread:
      tools === null
        ? null
        : Object.fromEntries(
            Object.entries(before.devtools).map(([key, value]) => [
              key,
              after.devtools[key] - value,
            ]),
          ),
    writes: delta((reading) => reading.output?.writes ?? null),
    characters: delta((reading) => reading.output?.characters ?? null),
  };
}

/**
Sequential round trips of a one-character message, each timed in the page.
*/
async function latency({ page, config }) {
  return page.evaluate(async (count) => {
    const { bridge } = globalThis.textualWasm;
    const samples = [];
    for (let index = 0; index < count; index += 1) {
      const started = performance.now();
      bridge.sendText("echo", "x");
      await globalThis.benchClient.next("echo-back");
      samples.push(performance.now() - started);
    }
    return { samples };
  }, config.params.n);
}

/**
 * Send `n` messages as fast as the page can, then wait until the app has handled them all.
 *
 * `sendMs` is how long the page spent sending; `totalMs` runs until the app acknowledges
 * the end marker, which it reads only after every flood message ahead of it. The count it
 * returns is checked against what was sent, so a dropped message fails the run instead of
 * flattering it.
 */
async function drain({ page, config }) {
  return page.evaluate(
    async ({ count, repeats }) => {
      const { bridge } = globalThis.textualWasm;
      const runs = [];
      for (let round = 0; round < repeats; round += 1) {
        const started = performance.now();
        for (let index = 0; index < count; index += 1) {
          bridge.sendText("flood", "1");
        }
        const sent = performance.now();
        bridge.sendText("flood-end", "");
        const received = Number(await globalThis.benchClient.next("flood-done"));
        runs.push({ sendMs: sent - started, totalMs: performance.now() - started, received });
      }
      return { count, runs };
    },
    { count: config.params.n, repeats: config.params.repeats },
  );
}

/**
Round trips of payloads of the given sizes, checked for length on the way back.
*/
async function payload({ page, config }) {
  return page.evaluate(
    async ({ sizes, repeats }) => {
      const { bridge } = globalThis.textualWasm;
      const results = [];
      for (const size of sizes) {
        const text = "a".repeat(size);
        const samples = [];
        for (let round = 0; round < repeats; round += 1) {
          const started = performance.now();
          bridge.sendText("echo", text);
          const back = await globalThis.benchClient.next("echo-back");
          samples.push(performance.now() - started);
          if (back.length !== size) {
            throw new Error(`echo of ${size} characters came back as ${back.length}`);
          }
        }
        results.push({ bytes: size, samples });
      }
      return { results };
    },
    { sizes: config.params.sizes, repeats: config.params.repeats },
  );
}

/**
 * `sendLatest` in a synchronous loop: how many messages does the app actually receive?
 *
 * The end marker goes out only after two frames, because `sendLatest` flushes on a frame
 * and the marker uses `send`, which does not wait - sent at once it would overtake the
 * coalesced value and the count would read zero.
 */
async function latest({ page, config }) {
  return page.evaluate(async (count) => {
    const { bridge } = globalThis.textualWasm;
    for (let index = 0; index < count; index += 1) {
      bridge.sendLatest("flood", index);
    }
    // Defined in here because this function runs in the page, not in this module.
    // eslint-disable-next-line unicorn/consistent-function-scoping
    const frame = () => new Promise((resolve) => requestAnimationFrame(resolve));
    await frame();
    await frame();
    bridge.sendText("flood-end", "");
    return { calls: count, received: Number(await globalThis.benchClient.next("flood-done")) };
  }, config.params.n);
}

/**
 * The longest gap between animation frames while a burst is sent and handled, against the
 * same measurement with no burst - the control that says what one frame is here.
 */
async function stall({ page, config }) {
  return page.evaluate(
    async ({ count, repeats }) => {
      const { bridge } = globalThis.textualWasm;
      // The helpers below run in the page, where this module's scope does not exist.
      // eslint-disable-next-line unicorn/consistent-function-scoping
      const longestGap = async (work) => {
        let last = performance.now();
        let longest = 0;
        let isSampling = true;
        const tick = (now) => {
          if (!isSampling) {
            return;
          }
          longest = Math.max(longest, now - last);
          last = now;
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
        await new Promise((resolve) => setTimeout(resolve, 200));
        longest = 0;
        last = performance.now();
        await work();
        await new Promise((resolve) => setTimeout(resolve, 200));
        isSampling = false;
        return longest;
      };
      const burst = async () => {
        for (let index = 0; index < count; index += 1) {
          bridge.sendText("flood", "1");
        }
        bridge.sendText("flood-end", "");
        await globalThis.benchClient.next("flood-done");
      };
      // eslint-disable-next-line unicorn/consistent-function-scoping
      const quiet = () => new Promise((resolve) => setTimeout(resolve, 300));
      const withBurst = [];
      const without = [];
      for (let round = 0; round < repeats; round += 1) {
        without.push(await longestGap(quiet));
        withBurst.push(await longestGap(burst));
      }
      return { count, burstGapMs: withBurst, quietGapMs: without };
    },
    { count: config.params.n, repeats: config.params.repeats },
  );
}

/**
The workloads that time themselves inside Python: the interpreter-side controls.
*/
async function control({ page, config }) {
  return page.evaluate(async (parameters) => {
    const { command } = globalThis.benchClient;
    const run = async (op, n) => {
      const samples = [];
      for (let round = 0; round < parameters.repeats; round += 1) {
        const reply = await command({ op, n });
        samples.push(reply.ms);
      }
      return { n, samples };
    };
    return {
      selfFlood: await run("self-flood", parameters.selfFlood),
      spin: await run("spin", parameters.spin),
      churn: await run("churn", parameters.churn),
    };
  }, config.params);
}

/**
 * Repeat a workload in rounds and read memory after each, from every vantage point.
 *
 * Growth across rounds that does not level off is a leak, and the vantage point it shows in
 * says whose: the interpreter's object count is Python, the page heap is the page's
 * JavaScript, the process tree is everything including the WebAssembly memory.
 */
async function leak({ session, context, page, config }) {
  const tools = await devtools(context, page, config.engine);
  const { rounds, perRound, workload } = config.params;
  const readings = [await memory(session, page, tools, true)];
  for (let round = 0; round < rounds; round += 1) {
    await page.evaluate(
      async ({ count, kind }) => {
        const { bridge } = globalThis.textualWasm;
        if (kind === "churn") {
          await globalThis.benchClient.command({ op: "churn", n: count });
          return;
        }
        for (let index = 0; index < count; index += 1) {
          bridge.sendText("flood", "1");
        }
        bridge.sendText("flood-end", "");
        await globalThis.benchClient.next("flood-done");
      },
      { count: perRound, kind: workload },
    );
    readings.push(await memory(session, page, tools, true));
  }
  return { workload, perRound, readings };
}

const SCENARIOS = { boot, idle, latency, drain, payload, latest, stall, control, leak };

/**
Scenarios that start from a running probe app with the client installed.
*/
const NEEDS_CLIENT = new Set(["latency", "drain", "payload", "latest", "stall", "control", "leak"]);

async function main() {
  const config = await readConfig();
  const scenario = SCENARIOS[config.scenario];
  if (scenario === undefined) {
    throw new Error(`unknown scenario ${config.scenario}`);
  }
  const session = await launch(config);
  try {
    const context = await session.browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await context.newPage();
    // The page's own console, on stderr, so a failure inside the app is visible in the log
    // of the run that hit it.
    page.on("console", (message) => process.stderr.write(`[page] ${message.text()}\n`));
    // Requests still open when a scenario fails. Once in nineteen runs a Firefox worker boot
    // stopped inside `micropip.install` and never resumed; an unanswered fetch is the only
    // unbounded wait on that path, and this is what would show it.
    const inFlight = new Set();
    context.on("request", (request) => inFlight.add(request.url()));
    const forget = (request) => {
      inFlight.delete(request.url());
    };
    context.on("requestfinished", forget);
    context.on("requestfailed", forget);
    let data;
    try {
      if (NEEDS_CLIENT.has(config.scenario)) {
        await openReady(page, withGrid(config.url), config.readyText);
        await installClient(page);
      }
      data = await scenario({ session, context, page, config });
    } catch (error) {
      process.stderr.write(`requests still in flight: ${JSON.stringify([...inFlight])}\n`);
      throw error;
    }
    process.stdout.write(
      `${JSON.stringify({
        engine: config.engine,
        browserVersion: session.browser.version(),
        scenario: config.scenario,
        data,
      })}\n`,
    );
  } finally {
    await session.close();
  }
}

await main();
