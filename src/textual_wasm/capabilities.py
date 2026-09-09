"""What the host runtime can actually do, asked rather than assumed.

Everything here is a question with a runtime answer, and every answer is reported rather than
branched on elsewhere: the probe, the driver and the app must stay identical across runtimes
or the cross-runtime comparison means nothing. This module is the one place allowed to know
which runtime it is on, in the same way :mod:`textual_wasm.polyfills` is the one place allowed
to work around it.

Three of these are commonly guessed wrong:

* `pthreads` is False in every stock Pyodide build and no header or flag changes it. Pyodide
  is not compiled with `-pthread` and its ABI documentation forbids linking anything that is,
  so cross-origin isolation does not buy Python threads - it buys the interrupt buffer and
  urllib3's streaming worker.
* `jspi` is what actually makes synchronous Python able to await a promise, via WebAssembly
  stack switching. It is also False under a plain `runPython`, so it must be detected at the
  point of use rather than at import.
* `runtime` distinguishes Node from a browser. Several capabilities differ between them in
  both directions, so a fact gathered under Node is not a fact about the browser.
"""

from __future__ import annotations

import dataclasses
import errno
import sys
from typing import Final

from textual_wasm.polyfills import IS_EMSCRIPTEN

NATIVE_RUNTIME: Final[str] = "native"
"""Reported as the runtime when not running on WebAssembly at all."""


@dataclasses.dataclass(frozen=True, slots=True)
class Capabilities:
    """A snapshot of what this host supports."""

    platform: str
    """`sys.platform`; "emscripten" under Pyodide."""

    runtime: str
    """The host, e.g. "Node.js/26", a browser user-agent string, or "native"."""

    pthreads: bool
    """Whether OS threads exist. False in every stock Pyodide build."""

    shared_memory: bool
    """Whether SharedArrayBuffer is available - needed for interrupts and streaming, not for
    threads."""

    jspi: bool
    """Whether `pyodide.ffi.run_sync` can block on a promise via stack switching."""

    cross_origin_isolated: bool | None
    """Whether the page is cross-origin isolated, or None outside a browser."""

    in_worker: bool | None
    """Whether this interpreter runs in a Web Worker, or None outside a browser.

    Worth reporting because it changes which failures are possible rather than how fast
    anything is: `window` and `document` do not exist here, so code reaching for either
    raises where the same code works on the main thread. It does *not* imply threads -
    `pthreads` is False in a worker too."""

    enoent: int
    """`errno.ENOENT`. Emscripten uses its own table where this is 44, not 2, so code that
    compares a caught errno against a literal silently stops matching."""

    @property
    def threads_available(self) -> bool:
        """Whether `@work(thread=True)` and thread pools can work here at all."""
        return self.pthreads

    @property
    def blocking_calls_freeze_the_ui(self) -> bool:
        """Whether a synchronous call blocks the only thread the host has."""
        return IS_EMSCRIPTEN and not self.pthreads


def _emscripten_info() -> tuple[str, bool, bool]:
    """Read `sys._emscripten_info`, which exists only on Emscripten.

    Returns:
        Runtime name, whether pthreads are compiled in, whether shared memory is available.
    """
    info = getattr(sys, "_emscripten_info", None)
    if info is None:
        return NATIVE_RUNTIME, True, True
    return (
        str(getattr(info, "runtime", None) or "emscripten"),
        bool(getattr(info, "pthreads", False)),
        bool(getattr(info, "shared_memory", False)),
    )


def _jspi_available() -> bool:
    """Whether stack switching is usable right now.

    Deliberately called rather than cached: it answers False under a plain `runPython` and
    True under `runPythonAsync`, so the answer depends on how the caller was invoked.
    """
    try:
        from pyodide.ffi import can_run_sync  # noqa: PLC0415 - only exists inside Pyodide
    except ImportError:
        return False
    try:
        return bool(can_run_sync())
    except Exception:
        return False


def _cross_origin_isolated() -> bool | None:
    """Whether the page is cross-origin isolated, or None if there is no page."""
    try:
        import js  # noqa: PLC0415 - only exists inside a WASM runtime
    except ImportError:
        return None
    try:
        return bool(js.crossOriginIsolated)
    except AttributeError:
        return None


def _in_worker() -> bool | None:
    """Whether this is a Web Worker global scope, or None if there is no JavaScript host.

    Tested by the absence of `window` rather than the presence of a worker-only global,
    because that is the property the callers actually depend on: `browser.open_url` and
    `browser.deliver_file` need a document, and every scope without one is equally unable
    to give them one.
    """
    try:
        import js  # noqa: PLC0415 - only exists inside a WASM runtime
    except ImportError:
        return None
    return not hasattr(js, "document")


def detect() -> Capabilities:
    """Interrogate the host and return what it supports."""
    runtime, pthreads, shared_memory = _emscripten_info()
    return Capabilities(
        platform=sys.platform,
        runtime=runtime,
        pthreads=pthreads,
        shared_memory=shared_memory,
        jspi=_jspi_available(),
        cross_origin_isolated=_cross_origin_isolated(),
        in_worker=_in_worker(),
        enoent=errno.ENOENT,
    )
