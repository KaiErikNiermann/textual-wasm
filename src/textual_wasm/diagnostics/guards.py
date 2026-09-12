"""Intercept the operations that fail without raising anything.

The registry's `LOUD_*` classes have an exception to improve on. This module exists for the
`SILENT_WRONG` class, which does not: `os.system` returns 0 in a browser having done nothing,
`run_in_executor` returns the right answer after running the work inline on the only thread,
`time.sleep` blocks the tab. There is no error to catch, no traceback to read, and no reason
for the developer to suspect the line they are looking at.

So the failure has to be manufactured. Each guard wraps the real callable and reports through
the registry before deciding whether to continue.

The policy split is deliberate. An operation with no correct use in a browser raises, because
the code is definitely wrong. An operation that still returns the right answer at an
unexpected cost warns, because raising would break working code and silence is how a page
ends up frozen for reasons nobody can trace.
"""

from __future__ import annotations

import asyncio
import enum
import os
import socket
import time
import warnings
from typing import TYPE_CHECKING, Any, Final

from textual_wasm.diagnostics.errors import UnsupportedInWasmError, WasmCompatibilityWarning
from textual_wasm.polyfills import IS_EMSCRIPTEN
from textual_wasm.substitutions import by_id

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


class GuardPolicy(enum.StrEnum):
    """What a guard does when it fires."""

    RAISE = "raise"
    """No correct use in a browser; the calling code is wrong."""

    WARN = "warn"
    """Right answer, unexpected cost. Report and continue."""


DEFAULT_POLICIES: Final[Mapping[str, GuardPolicy]] = {
    "os.system": GuardPolicy.RAISE,
    "socket.connect": GuardPolicy.RAISE,
    "os.kill.terminate": GuardPolicy.RAISE,
    "os.kill.suspend": GuardPolicy.WARN,
    "time.sleep": GuardPolicy.WARN,
    "asyncio.run_in_executor": GuardPolicy.WARN,
    # WARN rather than RAISE: a library that probes the terminal usually has a fallback for
    # the case where the probe fails, and raising here would take that path away. What the
    # developer needs is to know the probe is about to answer nothing, before the read that
    # follows it blocks forever.
    "termios.tcsetattr": GuardPolicy.WARN,
}
"""Per-substitution policy. Overridable at `install()` for a project that wants a strict run."""

_policies: dict[str, GuardPolicy] = dict(DEFAULT_POLICIES)
_undo: list[Callable[[], None]] = []
_recorded: list[WasmCompatibilityWarning] = []


def recorded() -> tuple[WasmCompatibilityWarning, ...]:
    """Warnings raised so far.

    Kept because `warnings.warn` writes to stderr, which under Pyodide is the browser
    console - the one place a terminal-app developer is not looking. `surface` renders these
    into the app instead.
    """
    return tuple(_recorded)


def _report(substitution_id: str, detail: str) -> None:
    """Raise or warn for `substitution_id`, per policy.

    Raises:
        UnsupportedInWasmError: When the policy for this substitution is `RAISE`.
    """
    substitution = by_id(substitution_id)
    if _policies.get(substitution_id, GuardPolicy.WARN) is GuardPolicy.RAISE:
        raise UnsupportedInWasmError(substitution, detail)
    warning = WasmCompatibilityWarning(substitution, detail)
    _recorded.append(warning)
    warnings.warn(warning, stacklevel=3)


def _guard_os_system() -> Callable[[], None]:
    """`os.system` shells out under Node and silently returns 0 in a browser."""
    # Deprecated in 3.14, which is beside the point: the guard exists because application
    # code still calls it, and the whole failure is that a browser makes it do nothing.
    original = os.system  # pyright: ignore[reportDeprecated]

    def guarded(command: str) -> int:
        _report("os.system", f"os.system({command!r})")
        return original(command)

    os.system = guarded
    return lambda: setattr(os, "system", original)


def _guard_time_sleep() -> Callable[[], None]:
    """`time.sleep` blocks the only thread, so the tab stops rendering for the duration."""
    original = time.sleep

    def guarded(secs: float) -> None:
        # A zero sleep is the "yield to whatever is next" idiom and costs nothing; reporting
        # it would bury the real cases.
        if secs > 0:
            _report("time.sleep", f"time.sleep({secs!r}) blocks for {secs}s")
        original(secs)

    time.sleep = guarded
    return lambda: setattr(time, "sleep", original)


def _guard_socket_connect() -> Callable[[], None]:
    """`connect` succeeds and the first read then hangs, which reads as a network problem."""
    original = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        _report("socket.connect", f"connect({address!r})")
        original(self, address)

    socket.socket.connect = guarded  # type: ignore[method-assign]
    return lambda: setattr(socket.socket, "connect", original)


def _guard_terminal_mode() -> Callable[[], None]:
    """Putting the terminal into cbreak or raw mode succeeds here and changes nothing.

    Worth a guard precisely because nothing fails: the call is only ever made in order to
    write a query escape sequence and read the terminal's reply, and the read is what hangs.
    Reporting at the mode change names the library responsible while there is still a stack
    to attribute it to - by the time the read blocks, the traceback is a bare `os.read`.

    `tty.setcbreak` and `tty.setraw` are wrapped rather than only `termios.tcsetattr` because
    they are what callers actually write; `tty` calls into `termios` but a wrapper installed
    on `termios` alone would attribute the report to the standard library.
    """
    import termios  # noqa: PLC0415 - native-only modules, imported where they are wrapped
    import tty  # noqa: PLC0415

    originals = {
        (tty, "setcbreak"): tty.setcbreak,
        (tty, "setraw"): tty.setraw,
        (termios, "tcsetattr"): termios.tcsetattr,
    }

    def wrap(module: Any, name: str, original: Any) -> Any:
        def guarded(*args: Any, **kwargs: Any) -> Any:
            _report(
                "termios.tcsetattr",
                f"{module.__name__}.{name}() succeeds here and changes nothing; a read of "
                "the terminal's reply will not return",
            )
            return original(*args, **kwargs)

        return guarded

    for (module, name), original in originals.items():
        setattr(module, name, wrap(module, name, original))

    def undo() -> None:
        for (module, name), original in originals.items():
            setattr(module, name, original)

    return undo


def _guard_os_kill() -> Callable[[], None]:
    """`SIGKILL` destroys the interpreter; `SIGTSTP` silently does nothing."""
    original = os.kill
    fatal = {getattr(__import__("signal"), name, None) for name in ("SIGKILL", "SIGTERM")}

    def guarded(pid: int, sig: int, /) -> None:
        if sig in fatal:
            _report("os.kill.terminate", f"os.kill(..., {sig}) would destroy the runtime")
        else:
            _report("os.kill.suspend", f"os.kill(..., {sig}) does nothing here")
        original(pid, sig)

    os.kill = guarded
    return lambda: setattr(os, "kill", original)


def _loop_classes() -> tuple[type[asyncio.AbstractEventLoop], ...]:
    """Event-loop classes worth patching.

    Pyodide's `WebLoop` does not inherit `BaseEventLoop`'s `run_in_executor`, it defines its
    own, so patching the base class alone would silently miss the runtime this module exists
    for.
    """
    classes: list[type[asyncio.AbstractEventLoop]] = [asyncio.BaseEventLoop]
    try:
        from pyodide.webloop import WebLoop  # noqa: PLC0415 - only exists inside Pyodide
    except ImportError:
        return tuple(classes)
    classes.append(WebLoop)
    return tuple(classes)


def _guard_run_in_executor() -> Callable[[], None]:
    """Pyodide's loop ignores the executor and runs the callable inline on the only thread."""
    undos: list[Callable[[], None]] = []
    for loop_class in _loop_classes():
        original = loop_class.run_in_executor

        def guarded(
            self: asyncio.AbstractEventLoop,
            executor: Any,
            func: Callable[..., Any],
            *args: Any,
            _original: Any = original,
        ) -> Any:
            _report(
                "asyncio.run_in_executor",
                f"run_in_executor({getattr(func, '__name__', func)!r}) runs inline",
            )
            return _original(self, executor, func, *args)

        loop_class.run_in_executor = guarded  # type: ignore[method-assign]
        undos.append(
            lambda cls=loop_class, fn=original: setattr(cls, "run_in_executor", fn)  # type: ignore[misc]
        )

    def undo() -> None:
        for callback in undos:
            callback()

    return undo


_GUARDS: Final[Sequence[Callable[[], Callable[[], None]]]] = (
    _guard_os_system,
    _guard_time_sleep,
    _guard_socket_connect,
    _guard_os_kill,
    _guard_run_in_executor,
    _guard_terminal_mode,
)


def install(
    *,
    force: bool = False,
    policies: Mapping[str, GuardPolicy] | None = None,
) -> None:
    """Wrap the silent-failure operations so they report themselves.

    Args:
        force: Install even off Emscripten. Off by default because none of these operations
            misbehave natively, and a warning about a real thread pool would be noise. The
            tests use it to exercise the guards on CPython.
        policies: Per-substitution overrides, e.g. to make every guard raise in CI.
    """
    if _undo or not (force or IS_EMSCRIPTEN):
        return
    _policies.clear()
    _policies.update(DEFAULT_POLICIES)
    if policies:
        _policies.update(policies)
    _undo.extend(guard() for guard in _GUARDS)


def uninstall() -> None:
    """Restore every patched callable, in reverse order."""
    while _undo:
        _undo.pop()()
    _recorded.clear()
