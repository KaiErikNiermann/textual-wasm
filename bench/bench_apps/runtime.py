"""What the interpreter itself can report about its memory, in either runtime.

Read from inside Python because two of the three numbers exist nowhere else: the browser
can say how big the tab is, but only the interpreter knows how many objects it holds, and
those are the numbers that separate a leak in Python from a leak in the page around it.
"""

from __future__ import annotations

import dataclasses
import gc
import importlib
import sys


@dataclasses.dataclass(frozen=True, slots=True)
class InterpreterMemory:
    """One reading, taken after a full collection so that garbage is not counted as growth."""

    gc_objects: int
    """Objects the cycle collector tracks. Grows with any Python-level leak."""

    allocated_blocks: int | None
    """Blocks held by CPython's small-object allocator, which also sees untracked objects.

    None under Pyodide, which is built without pymalloc: `sys.getallocatedblocks()` reads
    zero there, and a zero would look like a measurement rather than its absence."""

    wasm_bytes: int | None
    """The size of the WebAssembly linear memory, or None on a native interpreter.

    This is the interpreter's whole heap as the browser sees it. It only ever grows - linear
    memory cannot shrink - so it reads as a high-water mark rather than current use."""

    javascript_collected: bool
    """Whether the JavaScript realm around the interpreter was collected first, too."""


def wasm_memory_bytes() -> int | None:
    """The WebAssembly memory size, read through Pyodide's own module object.

    Imported by name at call time because `pyodide_js` exists only inside Pyodide, and a
    native run is supposed to answer None here rather than fail to import this module.
    """
    try:
        pyodide_js = importlib.import_module("pyodide_js")
    except ImportError:
        return None
    heap: object = getattr(getattr(pyodide_js, "_module", None), "HEAPU8", None)
    length: object = getattr(heap, "length", None)
    return length if isinstance(length, int) else None


def collect_javascript() -> bool:
    """Run a full collection of the JavaScript realm this interpreter lives in, if allowed.

    Only possible where the engine exposes `gc()` - Chromium started with `--expose-gc`,
    which the benchmark harness does. In a worker build that realm is the worker, which the
    page's own collection never reaches, so without this the worker's garbage would read as
    growth in every reading taken from outside.

    Returns:
        Whether a collection ran.
    """
    try:
        js = importlib.import_module("js")
    except ImportError:
        return False
    collect: object = getattr(js, "gc", None)
    if not callable(collect):
        return False
    collect()
    return True


def interpreter_memory() -> InterpreterMemory:
    """Collect, then read every counter."""
    gc.collect()
    collected = collect_javascript()
    return InterpreterMemory(
        gc_objects=len(gc.get_objects()),
        allocated_blocks=sys.getallocatedblocks() or None,
        wasm_bytes=wasm_memory_bytes(),
        javascript_collected=collected,
    )


def spin(iterations: int) -> int:
    """Pure arithmetic in a loop, for comparing interpreter speed across runtimes.

    Nothing here touches Textual, the page or the host, so the time it takes is set by the
    interpreter alone. That makes it the control for every other Python-side number: a
    workload that is N times slower under Pyodide than natively, when this loop is also N
    times slower, is slow because of the interpreter and not because of anything built on
    top of it.
    """
    total = 0
    for index in range(iterations):
        total += index * index
    return total
