/**
 * Static server for the browser half of the spike.
 *
 * Serves the page, the vendored Pyodide and xterm.js builds, and the project's own Python
 * source straight from `src/` so that editing a driver and reloading is the whole loop -
 * no wheel build, no copy step, and no chance of the browser running different code from
 * the Node probe.
 *
 * Deliberately dependency-free: adding a framework to serve four directories would be a
 * larger surface than the thing under test.
 */

import { createReadStream } from "node:fs";
import { readdir, readFile, stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, "..");
const PORT = Number(process.env.PORT ?? 8000);

/**
 * URL prefix to directory. Everything served is reached through this table, so a request
 * can never name a directory that was not deliberately published.
 */
const ROOTS = new Map([
  ["/vendor/pyodide", path.join(PROJECT_ROOT, "node_modules", "pyodide")],
  ["/vendor/xterm", path.join(PROJECT_ROOT, "node_modules", "@xterm", "xterm")],
  ["/vendor/addon-fit", path.join(PROJECT_ROOT, "node_modules", "@xterm", "addon-fit")],
  ["/entry", path.join(PROJECT_ROOT, "scripts")],
  ["", path.join(PROJECT_ROOT, "web")],
]);

const PACKAGE_DIR = path.join(PROJECT_ROOT, "src", "textual_wasm");
const REQUIREMENTS = path.join(PROJECT_ROOT, "wasm-requirements.txt");

const CONTENT_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".mjs", "text/javascript; charset=utf-8"],
  [".py", "text/plain; charset=utf-8"],
  [".txt", "text/plain; charset=utf-8"],
  [".wasm", "application/wasm"],
  [".whl", "application/octet-stream"],
  [".zip", "application/zip"],
]);

/**
 * Resolve a request path to a file, or null if it escapes every published root.
 *
 * @param {string} urlPath
 * @returns {string | null}
 */
function resolveFile(urlPath) {
  const clean = urlPath === "/" ? "/index.html" : urlPath;
  for (const [prefix, root] of ROOTS) {
    if (prefix !== "" && !clean.startsWith(`${prefix}/`)) {
      continue;
    }
    const relative = clean.slice(prefix.length).replace(/^\/+/, "");
    const candidate = path.resolve(root, relative);
    // Containment check: `path.resolve` collapses `..`, so comparing the result against
    // the root is what actually rules out traversal - filtering the input string does not.
    if (candidate === root || candidate.startsWith(root + path.sep)) {
      return candidate;
    }
    return null;
  }
  return null;
}

/**
 * The project's own package, as a `{ filename: source }` map the page writes into
 * Pyodide's filesystem. Generated per request so an edit needs only a reload.
 *
 * @returns {Promise<Record<string, string>>}
 */
async function packageSources() {
  const listing = await readdir(PACKAGE_DIR);
  const names = listing.filter((name) => name.endsWith(".py"));
  const entries = await Promise.all(
    names.map(async (name) => {
      // Not user input: `name` comes from readdir of a fixed directory, filtered to *.py.
      // eslint-disable-next-line security/detect-non-literal-fs-filename
      const source = await readFile(path.join(PACKAGE_DIR, name), "utf8");
      return [name, source];
    }),
  );
  return Object.fromEntries(entries);
}

/**
 * @param {http.ServerResponse} response
 * @param {number} status
 * @param {string} body
 */
function sendText(response, status, body) {
  response.writeHead(status, { "content-type": "text/plain; charset=utf-8" });
  response.end(body);
}

/**
 * @param {http.IncomingMessage} request
 * @param {http.ServerResponse} response
 */
async function handle(request, response) {
  const urlPath = new URL(request.url ?? "/", `http://${request.headers.host}`).pathname;

  if (urlPath === "/api/package") {
    response.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    response.end(JSON.stringify(await packageSources()));
    return;
  }

  const file = urlPath === "/wasm-requirements.txt" ? REQUIREMENTS : resolveFile(urlPath);
  if (file === null) {
    sendText(response, 403, "forbidden");
    return;
  }

  try {
    // `file` is constrained to a published root by resolveFile's containment check.
    // eslint-disable-next-line security/detect-non-literal-fs-filename
    const info = await stat(file);
    if (!info.isFile()) {
      sendText(response, 404, "not found");
      return;
    }
  } catch {
    sendText(response, 404, "not found");
    return;
  }

  response.writeHead(200, {
    "content-type": CONTENT_TYPES.get(path.extname(file)) ?? "application/octet-stream",
    // Pyodide's wasm is large and immutable per install; the page and the Python source
    // must not be cached or the edit-reload loop stops working.
    "cache-control": file.endsWith(".wasm") ? "public, max-age=3600" : "no-store",
  });
  // Same containment guarantee as the stat above.
  // eslint-disable-next-line security/detect-non-literal-fs-filename
  createReadStream(file).pipe(response);
}

const server = http.createServer(async (request, response) => {
  try {
    await handle(request, response);
  } catch (error) {
    process.stderr.write(`${error}\n`);
    sendText(response, 500, "internal error");
  }
});

server.listen(PORT, () => {
  process.stdout.write(`serving ${PROJECT_ROOT} on http://localhost:${PORT}\n`);
});
