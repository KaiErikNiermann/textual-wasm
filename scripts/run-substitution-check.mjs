/**
 * Re-measure the substitution registry's claims under Pyodide and print them as JSON.
 *
 * Sibling of `run-pyodide-node.mjs`, and deliberately separate: the probe answers "does
 * Textual work here", this answers "is what we tell people about this runtime still true".
 * They fail for different reasons and should be readable apart.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, "..");
const MOUNT_POINT = "/mnt/src";

function readRequirements() {
  return readFileSync(path.join(PROJECT_ROOT, "wasm-requirements.txt"), "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith("#"));
}

async function main() {
  const toStderr = (line) => process.stderr.write(`${line}\n`);
  // Return null for EOF rather than letting Pyodide inherit the harness's real stdin:
  // without this the `input()` probe blocks forever on the terminal that launched this
  // script, which measures the harness rather than Pyodide. "No stdin handler installed" is
  // also the state a browser page is in before it sets one, so it is the right thing to
  // measure.
  const pyodide = await loadPyodide({
    stdout: toStderr,
    stderr: toStderr,
    stdin: () => null,
  });
  await pyodide.loadPackage("micropip", {
    messageCallback: toStderr,
    errorCallback: toStderr,
  });
  await pyodide.pyimport("micropip").install(readRequirements());

  pyodide.FS.mkdirTree(MOUNT_POINT);
  pyodide.FS.mount(pyodide.FS.filesystems.NODEFS, { root: path.join(PROJECT_ROOT, "src") }, MOUNT_POINT);

  await pyodide.runPythonAsync(`
import sys
if ${JSON.stringify(MOUNT_POINT)} not in sys.path:
    sys.path.insert(0, ${JSON.stringify(MOUNT_POINT)})
`);
  await pyodide.runPythonAsync(
    readFileSync(path.join(HERE, "substitutions_entry.py"), "utf8"),
  );
  const run = pyodide.globals.get("run");
  process.stdout.write(`${await run()}\n`);
}

await main();
