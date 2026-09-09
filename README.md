# textual-wasm

Feasibility spike for running a [Textual](https://github.com/Textualize/textual) TUI **fully
client-side** under WebAssembly — the same application source running either as a classic
terminal TUI or as a static web page with no server-side Python process.

See [`textual-wasm-feasability-study.md`](./textual-wasm-feasability-study.md) for the
architecture audit this spike exists to confirm or refute.

## What the spike proves

`textual_wasm.probe.run_probe()` is a **single driver-agnostic coroutine** that boots a real
Textual `App`, drives it, and returns a structured `ProbeReport`. It is executed unchanged in
two places:

| Runner | Command | Runtime |
|---|---|---|
| native | `poetry run textual-wasm-spike probe` | CPython on Linux |
| WASM | `node scripts/run_pyodide_node.mjs` | Pyodide (CPython on wasm32-emscripten) |

Identical assertions, identical source, two runtimes. That equivalence *is* the thesis.

## Quick start

```bash
poetry install
poetry run textual-wasm-spike probe        # native baseline
pnpm install && node scripts/run_pyodide_node.mjs   # the WASM run
```

## Development

```bash
poetry run ruff check --fix && poetry run ruff format
poetry run pyright
poetry run radon cc -n B src/            # nothing above grade B
EIO_BACKEND=posix poetry run semgrep --config .semgrep --error
poetry run pytest
```

`git config core.hooksPath .githooks` wires the pre-push gate that runs all of the above.
