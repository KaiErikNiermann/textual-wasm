# Benchmarks

Time, CPU and memory for textual-wasm builds, with every cost attributed to the layer that causes it. The results and what they mean are in [docs/benchmarks.md](../docs/benchmarks.md); this file is about running them.

```bash
just bench          # the full run behind the docs, about an hour; resumes if interrupted
just bench-smoke    # every case at toy sizes, a few minutes
just bench-report   # render bench/results/latest.json into docs/benchmark-results.md
```

Pass `--only NAME` to run the cases whose name contains `NAME`, `--engine` and `--mode` to narrow the matrix, `--force` to redo cases the result file already has. `python -m textual_wasm_bench run --help` lists everything.

## Layout

- `bench_apps/`: the Textual apps being measured. `probe.py` is a static app that answers every data-channel scenario and reports the interpreter's memory; `idle.py` has a focused, blinking input. Each workload is a method, so the native control runs the same code.
- `harness/bench.mjs`: one scenario in one fresh browser, printed as JSON. `pages/` holds the baseline pages that bring the interpreter up one layer at a time, using the build's own `boot.mjs`.
- `textual_wasm_bench/`: builds the apps, runs the plan (`plan.py`), runs the native controls (`native.py`), saves after every case (`results.py`) and renders the tables (`report.py`).
- `results/latest.json`: the committed run the documentation is generated from.

## Running it well

Close what you can. The idle and memory readings are of the whole browser process tree, and the run is strictly sequential for that reason, but a busy machine still shows up in CPU time. A first visit fetches Pyodide and the wheels from jsDelivr, so the cold boot rows depend on the network. Firefox and Chromium are the default engines; `--engine webkit` adds Playwright's WebKit where it is installed.
