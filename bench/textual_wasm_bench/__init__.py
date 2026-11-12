"""Benchmarks for textual-wasm: time, CPU and memory, with every cost attributed to a layer.

Run with `just bench` (or `python -m textual_wasm_bench run`). A run builds the benchmark
apps, serves them, drives each scenario in a fresh browser through `bench/harness`, runs the
same workloads natively under CPython as the control, and writes everything to one JSON file
that `report` turns into the tables in the documentation.

Attribution is the design constraint. A number taken against the full page says what the
page costs and nothing about why, so every measurement comes with the layers under it
measured the same way: an empty browser tab, an interpreter running nothing, Textual
imported, the driver's timer alone, and the same app on a native terminal. The difference
between two adjacent layers is what the layer added.
"""
