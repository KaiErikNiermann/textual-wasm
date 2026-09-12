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
 * Name the storage object is registered under, and where IDBFS is mounted.
 *
 * `textual_wasm.storage` resolves the module by this name and reads `mountPoint` from it, so
 * these two strings are the whole contract between the page and Python. Duplicated in
 * `textual_wasm/storage.py` as `STORAGE_MODULE` and `DEFAULT_MOUNT`; a test asserts the two
 * agree, because a silent disagreement would present as "this build has no storage".
 */
export const STORAGE_MODULE = "textual_wasm_storage";
export const STORAGE_MOUNT = "/persist";

/**
 * Mount a persistent filesystem and hand Python the one call it cannot make itself.
 *
 * IDBFS rather than `localStorage`: measured across Chromium and Firefox, `localStorage` is
 * absent from a Web Worker's global scope - `js.localStorage` raises `AttributeError` there -
 * while IndexedDB is present in both contexts. Since a worker build is the one worth
 * recommending, a store that only works on the main thread is not a store.
 *
 * The initial `syncfs(true)` is a *load*, not a save: it populates the in-memory filesystem
 * from IndexedDB. Without it the mount is empty and the first read of a file written in a
 * previous session reports that it does not exist.
 *
 * @param {object} pyodide
 * @returns {Promise<void>}
 */
export async function mountStorage(pyodide) {
  pyodide.FS.mkdirTree(STORAGE_MOUNT);
  pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, STORAGE_MOUNT);
  await syncfs(pyodide, true);
  pyodide.registerJsModule(STORAGE_MODULE, {
    mountPoint: STORAGE_MOUNT,
    flush: () => syncfs(pyodide, false),
  });
}

/**
 * Write the mounted filesystem back to IndexedDB, reporting failure rather than raising.
 *
 * The callers are page-lifecycle handlers - `pagehide`, `visibilitychange`, a `flush`
 * message - which are synchronous and have nobody left to report to: the tab is on its way
 * out. So this swallows the error into the console deliberately, and is the only place that
 * does; `textual_wasm.storage.flush()` still propagates to application code that awaited it.
 *
 * @param {object} pyodide
 * @returns {Promise<void>}
 */
export async function flushQuietly(pyodide) {
  try {
    await syncfs(pyodide, false);
  } catch (error) {
    console.error("storage flush failed", error);
  }
}

/**
 * Promisify Emscripten's callback-style `syncfs`.
 *
 * @param {object} pyodide
 * @param {boolean} populate true to load from IndexedDB, false to write back to it.
 * @returns {Promise<void>}
 */
export function syncfs(pyodide, populate) {
  return new Promise((resolve, reject) => {
    pyodide.FS.syncfs(populate, (error) => (error ? reject(error) : resolve()));
  });
}

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
 * Rewrite micropip's install failures into something that names the actual cause.
 *
 * Three shapes come out of a failed `micropip.install`, and the first is actively
 * misleading. "Can't find a pure Python 3 wheel for tree-sitter>=0.25.0" reads as "nobody
 * has built this for wasm", when the far more common truth is that Pyodide *has* built it
 * and bundled a version your pin excludes - tree-sitter is bundled at 0.23.2. The two cases
 * have completely different fixes and the message distinguishes neither.
 *
 * This runs at boot, where there is no package set to consult, so it cannot say which of
 * the two applies. What it can do is name both and point at the command that does know -
 * `textual-wasm doctor -r <requirement>` reads Pyodide's lock file and answers exactly this.
 *
 * @param {unknown} error the failure from `micropip.install`
 * @returns {string} a message for the page's status line
 */
export function explainInstallFailure(error) {
  const text = String(error?.message ?? error);

  const missing = /Can't find a pure Python 3 wheel for '([^']+)'/.exec(text);
  if (missing !== null) {
    return (
      `cannot install ${missing[1]}: either nothing has built it for WebAssembly, or ` +
      "Pyodide bundles it as a native wheel at a version your requirement excludes - a " +
      "native wheel cannot be fetched from PyPI at any other version. Run " +
      `\`textual-wasm doctor -r "${missing[1]}"\` to find out which, before the next build.`
    );
  }

  const unknown = /Can't fetch metadata for '([^']+)'/.exec(text);
  if (unknown !== null) {
    return (
      `cannot install ${unknown[1]}: PyPI has no distribution under that name. micropip ` +
      "installs from PyPI or a URL and has no path to a git repository, so a library that " +
      "only exists as a repository has to be vendored into your own package instead."
    );
  }

  const clash = /Requested '([^']+)', but ([^ ]+) is already installed/.exec(text);
  if (clash !== null) {
    return (
      `cannot install ${clash[1]}: it contradicts ${clash[2]}, which is already in this ` +
      "build's closure. One of the two has to move; `textual-wasm doctor` reports which " +
      "requirement declared the conflicting constraint."
    );
  }

  return `cannot install this build's packages: ${text}`;
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

  // Before the packages, so that a package whose import reads a config file finds one.
  if (manifest.storage) {
    onStatus("booting", "opening persistent storage…");
    await mountStorage(pyodide);
  }

  onStatus("booting", `installing ${manifest.requirements.length} package(s)…`);
  await pyodide.loadPackage("micropip");
  try {
    await pyodide.pyimport("micropip").install(manifest.requirements);
  } catch (error) {
    // Rethrown rather than reported and swallowed: the application cannot run without its
    // packages, and a boot that continues from here fails later with something unrelated.
    // The original is kept as `cause` so the console still has the full traceback.
    throw new Error(explainInstallFailure(error), { cause: error });
  }
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
