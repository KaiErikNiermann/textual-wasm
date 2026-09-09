"""The feasibility probe: boot a real Textual app on the host runtime and report what worked.

One coroutine, executed unchanged on CPython and on Pyodide. Every claim in the feasibility
study that can be settled mechanically is a :class:`~textual_wasm.report.CheckId` here.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
import threading
from typing import Final

from rich.text import Text
from textual import __version__ as textual_version
from textual import constants
from textual.geometry import Size
from textual.pilot import Pilot

from textual_wasm import APPLIED_POLYFILLS
from textual_wasm.app import EXIT_CODE, MARKER, SpikeApp
from textual_wasm.bootstrap import DRIVER_IMPORT_PATH
from textual_wasm.driver import DEFAULT_SIZE, CaptureDriver, active_driver
from textual_wasm.report import (
    CheckId,
    CheckResult,
    CheckStatus,
    ProbeReport,
    RuntimeFacts,
)
from textual_wasm.screen import replay

FORBIDDEN_TTY_MODULES: Final[tuple[str, ...]] = ("termios", "tty", "pty", "curses")
"""Modules that only a tty driver needs.

`selectors`, `signal` and `fcntl` are deliberately absent, all for the same reason: importing
`asyncio` alone pulls every one of them on POSIX (`fcntl` arrives via `subprocess`, which
`asyncio.unix_events` needs). Measured, not assumed - `python -X importtime -c "import
asyncio"` shows `fcntl` nested under `subprocess`. Including them would have made this check
fail against an import graph Textual does not control, which is the opposite of informative.
"""

FORBIDDEN_DRIVER_MODULES: Final[tuple[str, ...]] = (
    "textual.drivers.linux_driver",
    "textual.drivers.linux_inline_driver",
    "textual.drivers.windows_driver",
)
"""Textual's own platform drivers.

The direct form of the claim: `App.get_driver_class` imports these lazily (`app.py:1602`), so
with `TEXTUAL_DRIVER` set none of them should ever be loaded. Unlike the stdlib check this is
equally meaningful on both runtimes, because these modules exist in the wheel either way.
"""

TRUECOLOR_SGR: Final[str] = "\x1b[38;2;"
"""Foreground truecolor SGR introducer — emitted by the compositor, never by the driver."""

_SETTLE_MARGIN: Final[float] = 0.1
"""Extra wait beyond the app's timer delay, so a slow `setTimeout` clamp cannot flake the run."""


@dataclasses.dataclass(frozen=True, slots=True)
class _Observations:
    """Raw facts gathered from one app run, before they are judged."""

    driver_class_name: str
    return_value: int | None
    observed_size: tuple[int, int] | None
    bump_count: int
    timer_fired: bool
    rendered_output: str


def _verdict(*, passed: bool) -> CheckStatus:
    return CheckStatus.PASS if passed else CheckStatus.FAIL


def _check_import_purity() -> CheckResult:
    """Assert neither a POSIX terminal module nor a Textual platform driver was imported.

    The stdlib half is meaningful natively, where those modules exist and an eager import
    anywhere in Textual's package graph would have succeeded and left a trace; under
    Emscripten they are absent outright, so it can only confirm nothing tried. The driver
    half is meaningful on both.
    """
    watched = FORBIDDEN_TTY_MODULES + FORBIDDEN_DRIVER_MODULES
    present = tuple(name for name in watched if name in sys.modules)
    detail = (
        f"no tty module or platform driver imported (checked {len(watched)}: {', '.join(watched)})"
        if not present
        else f"unexpectedly present in sys.modules: {', '.join(present)}"
    )
    return CheckResult(CheckId.IMPORT_PURITY, _verdict(passed=not present), detail)


def _check_driver_hook(observed_class_name: str) -> CheckResult:
    """Assert `TEXTUAL_DRIVER` selected the out-of-tree driver.

    A failure here usually means the environment was applied after something imported
    `textual.constants`, which caches it at import time.
    """
    passed = observed_class_name == CaptureDriver.__name__
    detail = (
        f"TEXTUAL_DRIVER={DRIVER_IMPORT_PATH!r} selected {observed_class_name}"
        if passed
        else (
            f"expected {CaptureDriver.__name__}, got {observed_class_name}; "
            f"textual.constants.DRIVER={constants.DRIVER!r}"
        )
    )
    return CheckResult(CheckId.DRIVER_HOOK, _verdict(passed=passed), detail)


def _check_run_async(return_value: int | None) -> CheckResult:
    passed = return_value == EXIT_CODE
    detail = f"run_async returned {return_value!r} (expected {EXIT_CODE!r})"
    return CheckResult(CheckId.RUN_ASYNC, _verdict(passed=passed), detail)


def _check_resize(observed: tuple[int, int] | None, expected: tuple[int, int]) -> CheckResult:
    passed = observed == expected
    detail = f"app observed Resize{observed} (expected {expected})"
    return CheckResult(CheckId.RESIZE_DELIVERED, _verdict(passed=passed), detail)


def _check_ansi(rendered: str) -> CheckResult:
    passed = TRUECOLOR_SGR in rendered
    detail = (
        f"compositor emitted truecolor SGR in {len(rendered)} chars of output"
        if passed
        else f"no truecolor SGR in {len(rendered)} chars of compositor output"
    )
    return CheckResult(CheckId.ANSI_OUTPUT, _verdict(passed=passed), detail)


def _check_widget_rendered(rendered: str) -> CheckResult:
    plain = Text.from_ansi(rendered).plain
    passed = MARKER in plain
    detail = f"{MARKER!r} {'found' if passed else 'absent'} in de-ANSI'd output"
    return CheckResult(CheckId.WIDGET_RENDERED, _verdict(passed=passed), detail)


def _check_key_input(bump_count: int) -> CheckResult:
    passed = bump_count == 1
    detail = f"XTermParser-fed 'a' fired the binding {bump_count} time(s), expected 1"
    return CheckResult(CheckId.KEY_INPUT, _verdict(passed=passed), detail)


def _check_timer(*, fired: bool) -> CheckResult:
    detail = f"set_timer callback {'fired' if fired else 'did not fire'}"
    return CheckResult(CheckId.TIMER, _verdict(passed=fired), detail)


def _evaluate(
    observations: _Observations, expected_size: tuple[int, int]
) -> tuple[CheckResult, ...]:
    """Turn raw observations into verdicts, in `CheckId` declaration order."""
    return (
        _check_import_purity(),
        _check_driver_hook(observations.driver_class_name),
        _check_run_async(observations.return_value),
        _check_resize(observations.observed_size, expected_size),
        _check_ansi(observations.rendered_output),
        _check_widget_rendered(observations.rendered_output),
        _check_key_input(observations.bump_count),
        _check_timer(fired=observations.timer_fired),
    )


def _as_pair(size: Size | None) -> tuple[int, int] | None:
    """Narrow a `Size` to a plain pair so the report stays JSON-shaped and comparable."""
    return None if size is None else (size.width, size.height)


def _threads_available() -> bool:
    """Whether `@work(thread=True)` could work here.

    `worker.py:326` hands thread workers to `loop.run_in_executor`, so this is the single
    fact that decides whether that decorator is usable on a host.
    """
    try:
        thread = threading.Thread(target=lambda: None)
        thread.start()
        thread.join()
    except RuntimeError:
        return False
    return True


def _eager_task_factory_accepted(loop: asyncio.AbstractEventLoop) -> bool:
    """Whether the loop honoured the factory `App.run_async` sets (`app.py:2283`)."""
    try:
        return loop.get_task_factory() is not None
    except (AttributeError, NotImplementedError):
        return False


def _collect_runtime_facts(loop: asyncio.AbstractEventLoop) -> RuntimeFacts:
    return RuntimeFacts(
        platform=sys.platform,
        python_version=sys.version.split()[0],
        textual_version=textual_version,
        event_loop=type(loop).__name__,
        threads_available=_threads_available(),
        eager_task_factory_accepted=_eager_task_factory_accepted(loop),
        polyfills_applied=APPLIED_POLYFILLS,
    )


async def run_probe(*, size: tuple[int, int] = DEFAULT_SIZE) -> ProbeReport:
    """Boot :class:`~textual_wasm.app.SpikeApp` on the host runtime and report the outcome.

    Args:
        size: Grid to force, so the `Resize` assertion has a value that cannot come from a
            real terminal.

    Returns:
        A report whose JSON is directly comparable between the native and WASM runs.
    """
    app = SpikeApp()
    driver_class_name = app.driver_class.__name__
    facts: list[RuntimeFacts] = []

    async def drive(pilot: Pilot[object]) -> None:
        facts.append(_collect_runtime_facts(asyncio.get_running_loop()))
        await pilot.pause()
        # Straight into the driver, not `pilot.press`: the point is to exercise the real
        # host -> XTermParser -> Driver.process_message -> App path a browser would use.
        active_driver().feed_input("a")
        await pilot.pause()
        await asyncio.sleep(_SETTLE_MARGIN)
        await pilot.pause()
        app.exit(EXIT_CODE)

    return_value = await app.run_async(size=size, auto_pilot=drive)
    driver = active_driver()
    observations = _Observations(
        driver_class_name=driver_class_name,
        return_value=return_value,
        observed_size=_as_pair(app.observed_size),
        bump_count=app.bump_count,
        timer_fired=app.timer_fired,
        rendered_output=driver.rendered_output,
    )
    return ProbeReport(
        runtime=facts[0],
        checks=_evaluate(observations, size),
        screen=replay(observations.rendered_output, columns=size[0], rows=size[1]),
    )
