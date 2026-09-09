"""The feasibility probe: boot a real Textual app on the host runtime and report what worked.

One coroutine, executed unchanged on CPython and on Pyodide. Every claim in the feasibility
study that can be settled mechanically is a :class:`~textual_wasm.report.CheckId` here.

The app under test is a parameter, not this module's own demo, so the same eight checks are
available to anyone porting their own application. Nothing here asks the app to cooperate:
the timer is scheduled by the probe, the resize is read back off the `Screen` the app laid
out, and input is judged by what appears on that screen. An app that has never heard of this
project is measurable by exactly the same code as the one that ships with it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
import threading  # textual-wasm: allow threading.thread - measures whether threads exist
from typing import Final

from textual import __version__ as textual_version
from textual import constants
from textual.app import App, ScreenStackError
from textual.pilot import Pilot

from textual_wasm import APPLIED_POLYFILLS
from textual_wasm.bootstrap import DRIVER_IMPORT_PATH
from textual_wasm.capabilities import detect as detect_capabilities
from textual_wasm.driver import DEFAULT_SIZE, CaptureDriver, active_capture
from textual_wasm.report import (
    CheckId,
    CheckResult,
    CheckStatus,
    ProbeReport,
    RuntimeFacts,
)
from textual_wasm.screen import RenderedScreen, replay
from textual_wasm.target import SPIKE_TARGET, AppTarget

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

EXIT_CODE: Final[int] = 7
"""Arbitrary non-zero, non-default value, so `run_async` returning it cannot be a coincidence.

Owned by the probe rather than by any app: the probe is what calls `App.exit`, so any app can
be made to settle the `run_async` question without knowing this value exists.
"""

TIMER_DELAY: Final[float] = 0.05
"""Short enough to keep the probe quick, long enough to be a real `call_later` round trip."""

_SETTLE_MARGIN: Final[float] = 0.1
"""Extra wait beyond the timer delay, so a slow `setTimeout` clamp cannot flake the run."""

MARKER_TIMEOUT: Final[float] = 30.0
"""How long to wait for a target's marker to appear on the grid.

Generous, and the same rule the other legs use: the tmux capture polls a pane and the browser
harness polls the xterm buffer, both until a timeout. A fixed sleep here instead would fail
`widget_rendered` on any app that loads lazily - Textual's own demo draws "Loading..." first -
while the other legs waited and passed, and the check would report a disagreement about
nothing.
"""

_MARKER_POLL: Final[float] = 0.05
"""Gap between grid replays while waiting. Small enough not to dominate a fast app's run."""


@dataclasses.dataclass(frozen=True, slots=True)
class _Observations:
    """Raw facts gathered from one app run, before they are judged."""

    driver_class_name: str
    return_value: object
    laid_out_size: tuple[int, int] | None
    timer_fired: bool
    rendered_output: str
    screen: RenderedScreen


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


def _check_run_async(return_value: object) -> CheckResult:
    passed = return_value == EXIT_CODE
    detail = f"run_async returned {return_value!r} (expected {EXIT_CODE!r})"
    return CheckResult(CheckId.RUN_ASYNC, _verdict(passed=passed), detail)


def _check_resize(observed: tuple[int, int] | None, expected: tuple[int, int]) -> CheckResult:
    """Assert the driver-synthesised resize reached the widget tree.

    Read off `Screen.size` rather than an `on_resize` handler the app would have to declare.
    A `Screen` only has a size once `_check_resize` has arranged it, and that runs solely
    from `App._on_resize` - so this is the same claim without asking the app for anything.
    """
    passed = observed == expected
    detail = f"Screen laid out at {observed} (expected {expected})"
    return CheckResult(CheckId.RESIZE_DELIVERED, _verdict(passed=passed), detail)


def _check_ansi(rendered: str) -> CheckResult:
    passed = TRUECOLOR_SGR in rendered
    detail = (
        f"compositor emitted truecolor SGR in {len(rendered)} chars of output"
        if passed
        else f"no truecolor SGR in {len(rendered)} chars of compositor output"
    )
    return CheckResult(CheckId.ANSI_OUTPUT, _verdict(passed=passed), detail)


def _check_widget_rendered(screen: RenderedScreen, target: AppTarget) -> CheckResult:
    """Assert the app drew something, judged on the replayed grid.

    The grid rather than the byte stream, because that is what every other leg reads: the
    terminal capture polls a pane and the browser harness reads the xterm buffer. A marker
    that the probe finds in the stream but a terminal never puts on screen would make the
    legs disagree for reasons that have nothing to do with the runtime.
    """
    if target.ready_marker is None:
        # No marker to look for. Weaker, but still an observation, and it is the honest
        # answer for an app whose output this project has never seen.
        passed = any(line.strip() for line in screen.lines)
        detail = (
            f"{'some' if passed else 'no'} non-blank content on the "
            f"{screen.columns}x{screen.rows} grid (no ready marker was given)"
        )
        return CheckResult(CheckId.WIDGET_RENDERED, _verdict(passed=passed), detail)
    passed = screen.contains(target.ready_marker)
    detail = f"ready marker {target.ready_marker!r} {'found' if passed else 'absent'} on the grid"
    return CheckResult(CheckId.WIDGET_RENDERED, _verdict(passed=passed), detail)


def _check_key_input(screen: RenderedScreen, target: AppTarget) -> CheckResult:
    """Assert bytes fed through `XTermParser` changed what is on screen.

    Skipped rather than failed when the target declares no keys: an app that cannot be
    driven from a fixed keystroke is not a broken runtime, and reporting it as one would
    make the whole check untrustworthy on real applications.
    """
    if not target.exercises_input or target.settled_marker is None:
        return CheckResult(
            CheckId.KEY_INPUT,
            CheckStatus.SKIP,
            "target declares no keys and a settled marker, so the input path is unexercised",
        )
    passed = screen.contains(target.settled_marker)
    detail = (
        f"fed {target.keys!r} through XTermParser; settled marker "
        f"{target.settled_marker!r} {'found' if passed else 'absent'} on the grid"
    )
    return CheckResult(CheckId.KEY_INPUT, _verdict(passed=passed), detail)


def _check_timer(*, fired: bool) -> CheckResult:
    detail = f"probe-scheduled set_timer callback {'fired' if fired else 'did not fire'}"
    return CheckResult(CheckId.TIMER, _verdict(passed=fired), detail)


def _evaluate(
    observations: _Observations, target: AppTarget, expected_size: tuple[int, int]
) -> tuple[CheckResult, ...]:
    """Turn raw observations into verdicts, in `CheckId` declaration order."""
    return (
        _check_import_purity(),
        _check_driver_hook(observations.driver_class_name),
        _check_run_async(observations.return_value),
        _check_resize(observations.laid_out_size, expected_size),
        _check_ansi(observations.rendered_output),
        _check_widget_rendered(observations.screen, target),
        _check_key_input(observations.screen, target),
        _check_timer(fired=observations.timer_fired),
    )


def _threads_available() -> bool:
    """Whether `@work(thread=True)` could work here.

    `worker.py:326` hands thread workers to `loop.run_in_executor`, so this is the single
    fact that decides whether that decorator is usable on a host.
    """
    try:
        # textual-wasm: allow threading.thread - measuring whether threads exist here
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
    capabilities = detect_capabilities()
    return RuntimeFacts(
        platform=capabilities.platform,
        python_version=sys.version.split()[0],
        textual_version=textual_version,
        event_loop=type(loop).__name__,
        threads_available=_threads_available(),
        eager_task_factory_accepted=_eager_task_factory_accepted(loop),
        runtime=capabilities.runtime,
        jspi=capabilities.jspi,
        shared_memory=capabilities.shared_memory,
        cross_origin_isolated=capabilities.cross_origin_isolated,
        polyfills_applied=APPLIED_POLYFILLS,
    )


def _laid_out_size(app: App[object]) -> tuple[int, int] | None:
    """The size the `Screen` was arranged at, or None if there is no screen to ask."""
    try:
        size = app.screen.size
    except ScreenStackError:
        return None
    return (size.width, size.height)


async def _wait_for_marker(
    pilot: Pilot[object], driver: CaptureDriver, marker: str, size: tuple[int, int]
) -> None:
    """Let the app run until `marker` is on the grid, or the timeout expires.

    Not an assertion: a marker that never arrives is reported by the check that was waiting
    for it, with what the grid did say. Raising here would lose that.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MARKER_TIMEOUT
    while loop.time() < deadline:
        if replay(driver.rendered_output, columns=size[0], rows=size[1]).contains(marker):
            return
        await pilot.pause()
        await asyncio.sleep(_MARKER_POLL)


@dataclasses.dataclass(slots=True)
class _Run:
    """Mutable state the pilot fills in, kept out of the app so no app has to declare it."""

    facts: RuntimeFacts | None = None
    timer_fired: bool = False
    laid_out_size: tuple[int, int] | None = None


async def run_probe(
    *, target: AppTarget = SPIKE_TARGET, size: tuple[int, int] = DEFAULT_SIZE
) -> ProbeReport:
    """Boot `target` on the host runtime and report the outcome.

    Args:
        target: The application to run, and the text that proves it ran.
        size: Grid to force, so the resize assertion has a value that cannot come from a
            real terminal.

    Returns:
        A report whose JSON is directly comparable between the native and WASM runs.
    """
    app = target.load()()
    driver_class_name = app.driver_class.__name__
    run = _Run()

    def mark_timer_fired() -> None:
        run.timer_fired = True

    async def drive(pilot: Pilot[object]) -> None:
        run.facts = _collect_runtime_facts(asyncio.get_running_loop())
        await pilot.pause()
        driver = active_capture()
        if target.ready_marker is not None:
            await _wait_for_marker(pilot, driver, target.ready_marker, size)
        # Scheduled here rather than expected from the app: `set_timer` is a runtime
        # capability, and making the app provide it would mean only instrumented apps could
        # settle the question.
        app.set_timer(TIMER_DELAY, mark_timer_fired)
        if target.keys:
            # Straight into the driver, not `pilot.press`: the point is to exercise the real
            # host -> XTermParser -> Driver.process_message -> App path a browser would use.
            driver.feed_input(target.keys)
            if target.settled_marker is not None:
                await _wait_for_marker(pilot, driver, target.settled_marker, size)
        await pilot.pause()
        await asyncio.sleep(TIMER_DELAY + _SETTLE_MARGIN)
        await pilot.pause()
        run.laid_out_size = _laid_out_size(app)
        app.exit(EXIT_CODE)

    return_value = await app.run_async(size=size, auto_pilot=drive)
    driver = active_capture()
    rendered_output = driver.rendered_output
    observations = _Observations(
        driver_class_name=driver_class_name,
        return_value=return_value,
        laid_out_size=run.laid_out_size,
        timer_fired=run.timer_fired,
        rendered_output=rendered_output,
        screen=replay(rendered_output, columns=size[0], rows=size[1]),
    )
    if run.facts is None:  # pragma: no cover - the pilot always runs before the app exits
        raise RuntimeError("the pilot never ran, so no runtime facts were collected")
    return ProbeReport(
        target=target.entry,
        runtime=run.facts,
        checks=_evaluate(observations, target, size),
        screen=observations.screen,
    )
