# playground

The Textual playground on the documentation site: a CodeMirror editor, a frame that runs what is in it under Pyodide, and a link that carries the program to someone else.

```bash
poetry install
pnpm install

pnpm dev                      # with Vite's reload
pnpm build && pnpm preview    # the static site
```

## How it fits together

- `runner/playground_runner` is an ordinary Textual package built with `textual-wasm build` into `public/runner/`. Its entry, `playground_runner.app:create`, reads the program from the frame's URL fragment, runs it as `__main__` with `App.run` intercepted, and returns the app it built. A bad link or an exception becomes an app that shows the problem.
- `src/main.mjs` is the page. Each run replaces the frame, so every run gets a fresh interpreter and the runtime is the same one every other build ships.
- `src/share.mjs` and `runner/playground_runner/share.py` read and write the same link format: `#v1.` followed by the source, raw-DEFLATE compressed and base64url-encoded. It is a fragment, so the program never reaches a server.
- `starters/` holds the programs in the "Start from" picker. `tests/test_playground.py` checks that each one builds an app.

The runner frame is sandboxed without `allow-same-origin`. A shared link is someone else's code, and Python in Pyodide can call JavaScript, so on a `*.github.io` origin that other sites share, an unsandboxed frame would give that code their storage. With the sandbox the frame has an opaque origin and fetches its own files cross-origin. GitHub Pages, `textual-wasm dev` and the Vite servers configured here all allow that.

Only what the build installs is importable: Textual, Rich and the standard library that Pyodide ships. There is no way to add a package from inside the playground yet.
