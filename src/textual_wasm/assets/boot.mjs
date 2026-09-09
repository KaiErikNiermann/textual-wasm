/**
 * The half of the boot sequence that does not care where it runs.
 *
 * A Textual app can be hosted on the main thread or inside a Web Worker. Those two differ
 * only in what drives the terminal: the Python side is identical, and so is everything
 * needed to get a Pyodide interpreter to the point of running it. That shared part lives
 * here so `main.mjs` and `worker.mjs` are each only the part that is genuinely different -
 * a second copy of the install sequence is the kind of thing that stays correct for exactly
 * as long as nobody edits one of them.
 *
 * Nothing in this module may touch `document` or `window`. A worker has neither, and a
 * reference to either is not a load error - it is a `ReferenceError` thrown several seconds
 * in, after the runtime has already been fetched.
 */

/**
 * Where Python packages are written into Pyodide's filesystem. A build writes both this
 * project and the application here, so neither has to be a wheel.
 */
export const SITE_PACKAGES = "/lib/python3.14/site-packages";

/**
 * Name the host registers its terminal object under via `pyodide.registerJsModule`.
 * `textual_wasm.browser` resolves it at import time and says so explicitly if it is absent.
 */
export const HOST_MODULE = "textual_wasm_host";

/**
 * Write Python sources into Pyodide's filesystem.
 *
 * Sources rather than wheels, so a development server can serve straight from disk and an
 * edit needs only a reload - and so the browser demonstrably runs the same files the other
 * runtimes do.
 *
 * Every file in the package travels, not only the ones with a source-like suffix: an app is
 * entitled to read a JSON file, a font or an image sitting next to its code, and a build that
 * quietly left those behind produced a `FileNotFoundError` in the browser for a path that
 * plainly existed on disk. Anything that is not valid UTF-8 arrives base64-encoded.
 *
 * @param {object} pyodide
 * @param {Record<string, Record<string, {encoding: string, data: string}>>} packages
 *   package name to {path: {encoding, data}}
 */
export function installPackages(pyodide, packages) {
  for (const [name, files] of Object.entries(packages)) {
    for (const [relative, file] of Object.entries(files)) {
      const target = `${SITE_PACKAGES}/${name}/${relative}`;
      pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
      if (file.encoding === "base64") {
        // `atob` yields one character per byte, all below U+0100, so there are no surrogate
        // pairs and code point and code unit are the same number. Going through a
        // TextDecoder instead would mangle the bytes by guessing an encoding they do not have.
        const binary = atob(file.data);
        const bytes = Uint8Array.from(binary, (character) => character.codePointAt(0));
        pyodide.FS.writeFile(target, bytes);
      } else {
        pyodide.FS.writeFile(target, file.data, { encoding: "utf8" });
      }
    }
  }
}

/**
 * Read a build manifest and resolve the URLs inside it.
 *
 * The manifest's relative URLs are relative to the manifest, not to the document. That is
 * what lets a build be served from a subdirectory of someone else's site: `/terminal/app.json`
 * finds `/terminal/sources.json` while the page itself lives at `/`.
 *
 * The resolved URLs are returned as strings rather than `URL` objects because a manifest
 * read on the main thread is handed to a worker through `postMessage`, and a plain object
 * of strings survives that without depending on what the structured clone algorithm happens
 * to support.
 *
 * @param {string | URL} manifestUrl
 * @returns {Promise<object>} the manifest, with absolute `sourcesUrl` and `entryUrl`.
 */
export async function readManifest(manifestUrl) {
  const response = await fetch(manifestUrl);
  if (!response.ok) {
    throw new Error(`no ${manifestUrl}; run \`textual-wasm build\` to produce one`);
  }
  const manifest = await response.json();
  return {
    ...manifest,
    sourcesUrl: new URL(manifest.sourcesUrl, manifestUrl).href,
    entryUrl: new URL(manifest.entryUrl, manifestUrl).href,
  };
}

/**
 * Import the Pyodide build the manifest pinned.
 *
 * Dynamic rather than a static import because the URL comes from the manifest: a static
 * import would mean a second copy of the version number living in this file, and a copy is
 * a thing that drifts.
 *
 * @param {object} manifest
 * @returns {Promise<Function>} `loadPyodide`
 */
export async function importPyodide(manifest) {
  const module = await import(`${manifest.pyodideIndexUrl}pyodide.mjs`);
  return module.loadPyodide;
}

/**
 * Boot an interpreter, install the app, and start it against `host`.
 *
 * @param {object} options
 * @param {object} options.manifest a manifest from `readManifest`
 * @param {object} options.host an object satisfying `textual_wasm.browser.TerminalHost`
 * @param {Function} options.loadPyodide from `importPyodide`
 * @param {(state: string, message: string) => void} options.onStatus progress reporting
 * @returns {Promise<{pyodide: object, finished: Promise<unknown>}>} `finished` settles when
 *   the application exits. It is deliberately not awaited here: a module whose top-level
 *   evaluation waits for the application to exit never finishes evaluating.
 */
export async function boot({ manifest, host, loadPyodide, onStatus }) {
  onStatus("booting", "starting Python…");
  const pyodide = await loadPyodide({
    indexURL: manifest.pyodideIndexUrl,
    // COLUMNS and LINES because os.get_terminal_size() raises here and
    // shutil.get_terminal_size() falls back to 80x24 - a TUI would lay out for the wrong
    // grid without them. isatty likewise: a terminal app that believes it has no terminal
    // disables colour and line editing before it draws anything.
    env: { COLUMNS: String(host.cols), LINES: String(host.rows), TERM: "xterm-256color" },
  });
  pyodide.setStdin({ stdin: () => null, isatty: true });

  onStatus("booting", `installing ${manifest.requirements.length} package(s)…`);
  await pyodide.loadPackage("micropip");
  await pyodide.pyimport("micropip").install(manifest.requirements);
  const sources = await fetch(manifest.sourcesUrl);
  installPackages(pyodide, await sources.json());

  // Registered before the entry module is executed, because that module imports the driver
  // and the driver resolves the host at import time.
  pyodide.registerJsModule(HOST_MODULE, host);

  onStatus("booting", "starting the app…");
  const entry = await fetch(manifest.entryUrl);
  await pyodide.runPythonAsync(await entry.text());

  const start = pyodide.globals.get("start");
  return { pyodide, finished: start(manifest.entry) };
}
