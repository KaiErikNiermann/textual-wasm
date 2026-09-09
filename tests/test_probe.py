"""The native half of the experiment, as a regression suite.

These are the same assertions the WASM harness runs; keeping them in pytest means a change
that breaks the driver is caught before anyone boots a browser.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from textual import constants

from textual_wasm.app import EXIT_CODE, MARKER
from textual_wasm.bootstrap import DRIVER_IMPORT_PATH, REQUIRED_ENVIRONMENT
from textual_wasm.driver import (
    ENTER_APPLICATION_MODE,
    EXIT_APPLICATION_MODE,
    CaptureDriver,
    active_capture,
)
from textual_wasm.probe import FORBIDDEN_DRIVER_MODULES, TRUECOLOR_SGR, run_probe
from textual_wasm.report import CheckStatus, ProbeReport

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def _probe_in_a_fresh_interpreter(*extra: str) -> ProbeReport:
    """Run the shipped CLI in a subprocess and read its report back.

    `import_purity` asserts on `sys.modules`, which is interpreter-global, so it can only be
    measured in a process that has done nothing else. Inside pytest it cannot: `tmp_path`
    calls `getpass.getuser()`, and `getpass` imports `termios`, so any test that asks for a
    temporary directory makes every later purity assertion fail for a reason unrelated to
    Textual.

    A subprocess is also the more faithful test - the WASM and browser harnesses each run in
    a fresh process, so this measures the same thing they do, through the same entry point a
    user would.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths are ours
        [sys.executable, "-m", "textual_wasm", "probe", "--json", *extra],
        capture_output=True,
        text=True,
        check=True,
        cwd=PROJECT_ROOT,
    )
    return ProbeReport.from_json(completed.stdout)


def test_every_check_passes_natively() -> None:
    report = _probe_in_a_fresh_interpreter()
    assert report.failures == ()
    assert {result.status for result in report.checks} == {CheckStatus.PASS}


async def test_report_survives_a_json_round_trip() -> None:
    """The WASM report crosses a process boundary as text; the native one must too."""
    report = await run_probe()
    assert ProbeReport.from_json(report.to_json()) == report


async def test_driver_emits_application_mode_around_the_render() -> None:
    # Deliberately in-process: this is about the driver's own output, and the driver
    # instance is only reachable from the interpreter that constructed it.
    await run_probe()
    driver = active_capture()
    assert isinstance(driver, CaptureDriver)
    assert driver.output.startswith("".join(ENTER_APPLICATION_MODE))
    assert driver.output.endswith("".join(EXIT_APPLICATION_MODE))


async def test_rendered_output_excludes_the_drivers_own_preamble() -> None:
    """An 'is there ANSI' assertion must not be satisfiable by the driver's own writes."""
    await run_probe()
    driver = active_capture()
    assert TRUECOLOR_SGR not in "".join(ENTER_APPLICATION_MODE)
    assert TRUECOLOR_SGR in driver.rendered_output
    assert MARKER not in "".join(ENTER_APPLICATION_MODE)


def test_forced_size_reaches_the_app() -> None:
    report = _probe_in_a_fresh_interpreter("--width", "120", "--height", "40")
    assert report.ok, report.failures
    assert report.screen.columns == 120


async def test_probe_exit_code_is_distinctive() -> None:
    """Guard against `run_async` returning a default that would pass by accident."""
    assert EXIT_CODE not in (0, 1, None)


def test_environment_was_applied_before_textual_was_imported() -> None:
    """`textual.constants` caches every TEXTUAL_* var at import time.

    If the package `__init__` ever stops running first, this is the check that says so
    instead of the app silently falling back to the platform driver.
    """
    assert constants.DRIVER == DRIVER_IMPORT_PATH
    assert REQUIRED_ENVIRONMENT["TEXTUAL_COLOR_SYSTEM"] == constants.COLOR_SYSTEM


@pytest.mark.parametrize("module", FORBIDDEN_DRIVER_MODULES)
def test_textual_platform_drivers_are_never_imported(module: str) -> None:
    assert module not in sys.modules
