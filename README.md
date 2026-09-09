# textual-wasm

Feasibility spike for running a [Textual](https://github.com/Textualize/textual) TUI **fully
client-side** under WebAssembly — the same application source running either as a classic
terminal TUI or as a static web page with no server-side Python process.

**Result: it works, against unpatched Textual 8.2.8, with no fork and no upstream patch.**
[`textual-wasm-feasability-study.md`](./textual-wasm-feasability-study.md) has the
architecture audit and, in §11, what the spike actually measured.

## The claim, and how it is checked

`textual_wasm.probe.run_probe()` is a **single driver-agnostic coroutine** that boots a real
Textual `App`, drives it, and returns a structured `ProbeReport`. It runs unchanged in two
places:

| Runner | Command | Runtime |
|---|---|---|
| native | `poetry run textual-wasm-spike probe` | CPython on Linux |
| WASM | `node scripts/run-pyodide-node.mjs` | Pyodide (CPython on wasm32-emscripten) |

`./scripts/run-spike.sh` runs both and diffs the reports. Eight checks, both runtimes, all
passing; the compositor emits a byte-identical 7311 characters either way.

Nothing in the probe, the driver or the app may branch on `sys.platform` — a semgrep rule
enforces it. Runtime differences are confined to `polyfills.py` and recorded in the report,
so a WASM run can never look accidentally native.

## The browser half

```bash
pnpm install && pnpm serve      # http://localhost:8000
```

`web/` runs the same app against a real `xterm.js` terminal: Pyodide boots, micropip installs
the pinned closure, the page registers a four-member terminal object, and
`textual_wasm.browser.BrowserDriver` writes to it. Python is served straight from `src/`, so
the browser demonstrably runs the same files as the Node probe.

## How the pieces fit

```
bootstrap.py   TEXTUAL_* env, applied before the first `import textual` (it caches at import)
polyfills.py   runtime bugs, quarantined and reported
driver.py      WasmDriverBase  ->  CaptureDriver (sink: a list)
browser.py     WasmDriverBase  ->  BrowserDriver (sink: xterm.js)
app.py         the Textual app under test — ordinary, with no WASM awareness
probe.py       the experiment
compare.py     the verdict
```

Selecting a driver needs no patch to Textual: `TEXTUAL_DRIVER=module:Symbol` is a supported
hook (`textual/app.py:1585`).

## Development

```bash
poetry install
poetry run pytest                            # includes a selftest of the semgrep rules
pnpm lint:all                                # eslint (css + js), stylelint, principled-css
poetry run textual-wasm-spike pins           # regenerate wasm-requirements.txt
git config core.hooksPath .githooks          # lint, types, complexity, policy, tests
```
