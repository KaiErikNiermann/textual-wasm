"""Textual applications the benchmarks drive, in a browser and natively.

Shipped into the page as a package of its own rather than as part of `textual_wasm`, so
that the measurements exercise the same build path an application author's code takes.
Every workload is a method on the application, so the native control runs the identical
code under CPython that the browser run executes under Pyodide.
"""
