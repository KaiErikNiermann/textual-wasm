/**
 * Run the probe under Pyodide (CPython compiled to wasm32-emscripten).
 *
 * This is the WASM half of the experiment. It must call exactly the same
 * `textual_wasm.probe.run_probe` the native CLI calls, with no shims and no patched
 * Textual, or the comparison it produces means nothing. The only things it is allowed to
 * do are: provide a filesystem, install dependencies, and transport the JSON back out.
 *
 * Node rather than a browser on purpose. Everything the study calls load-bearing on the
 * Python side - the TEXTUAL_DRIVER hook, lazy driver imports, `run_async` on a non-native
 * event loop, XTermParser, asyncio timers - is testable here and therefore CI-able here.
 * What is left for the browser is rendering and font metrics, which is a different claim.
 *
 * Everything specific to one run arrives in a JSON config file named by argv[2], written by
 * `textual_wasm.node`: which directories to mount, what to install, and which app to probe.
 * Nothing here knows about this project's own layout, so it works on a user's application
 * from an installed package.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

/**
 * Kept in sync with `textual_wasm.report.REPORT_SENTINEL`.
 */
const REPORT_SENTINEL = "TEXTUAL_WASM_PROBE_JSON";

/**
 * @returns {object} the run configuration.
 */
function readConfig() {
  const file = process.argv[2];
  if (file === undefined) {
    throw new Error("usage: node pyodide-probe.mjs <config.json>");
  }
  return JSON.parse(readFileSync(file, "utf8"));
}

/**
 * Load a Node package from wherever the caller's `node_modules` lives.
 *
 * A bare `import "pyodide"` would resolve relative to *this* file, which is inside an
 * installed Python package and has no `node_modules` above it. `createRequire` rebases
 * resolution onto a directory the caller chose, so the harness ships with the package and
 * still finds the runtime in the user's project.
 *
 * @param {string} resolveFrom directory containing `node_modules`
 * @param {string} name package to load
 */
function loadFrom(resolveFrom, name) {
  return createRequire(path.join(resolveFrom, "noop.cjs"))(name);
}

/**
 * Mount source directories rather than installing built wheels.
 *
 * The point of the check is that the *same source* runs in both places; installing a built
 * artifact here would leave room for the two runs to diverge in what they actually loaded.
 *
 * @param {object} pyodide
 * @param {{root: string, point: string}[]} mounts
 */
function mountSources(pyodide, mounts) {
  for (const mount of mounts) {
    pyodide.FS.mkdirTree(mount.point);
    pyodide.FS.mount(pyodide.FS.filesystems.NODEFS, { root: mount.root }, mount.point);
  }
}

/**
 * @param {object} pyodide
 * @param {object} config
 * @returns {Promise<object>} the probe report.
 */
async function probe(pyodide, config) {
  await pyodide.runPythonAsync(readFileSync(config.entryScript, "utf8"));
  const run = pyodide.globals.get("run");
  // The whole config as text, rather than positional arguments: the Python side then
  // validates it at that boundary the same way it validates a report crossing back.
  const output = await run(JSON.stringify(config));
  const parts = output.split(REPORT_SENTINEL);
  if (parts.length !== 3) {
    throw new Error(`probe did not emit a delimited report; got: ${output.slice(0, 400)}`);
  }
  return JSON.parse(parts[1]);
}

async function main() {
  const config = readConfig();
  // Everything the runtime says goes to stderr, so stdout carries only the report and a
  // caller can pipe it straight into a JSON parser.
  const toStderr = (line) => process.stderr.write(`${line}\n`);
  const { loadPyodide } = loadFrom(config.resolveFrom, "pyodide");

  const started = performance.now();
  const pyodide = await loadPyodide({ stdout: toStderr, stderr: toStderr });
  const bootMs = performance.now() - started;

  await pyodide.loadPackage("micropip", { messageCallback: toStderr, errorCallback: toStderr });
  const installStarted = performance.now();
  await pyodide.pyimport("micropip").install(config.requirements);
  const installMs = performance.now() - installStarted;

  mountSources(pyodide, config.mounts);

  const probeStarted = performance.now();
  const report = await probe(pyodide, config);
  const probeMs = performance.now() - probeStarted;

  const timings = {
    requirements: config.requirements.length,
    pyodide_boot_ms: Math.round(bootMs),
    dependency_install_ms: Math.round(installMs),
    probe_ms: Math.round(probeMs),
  };
  process.stdout.write(`${JSON.stringify({ ...report, timings }, null, 2)}\n`);

  const failed = report.checks.filter((check) => check.status === "fail");
  if (failed.length > 0) {
    process.stderr.write(`${failed.length} check(s) failed under Pyodide\n`);
    process.exitCode = 1;
  }
}

await main();
