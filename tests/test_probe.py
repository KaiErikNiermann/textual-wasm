"""The native half of the experiment, as a regression suite.

These are the same assertions the WASM harness runs; keeping them in pytest means a change
that breaks the driver is caught before anyone boots a browser.
"""

from __future__ import annotations

import sys

import pytest
from textual import constants

from textual_wasm.app import EXIT_CODE, MARKER
from textual_wasm.bootstrap import DRIVER_IMPORT_PATH, REQUIRED_ENVIRONMENT
from textual_wasm.driver import (
    ENTER_APPLICATION_MODE,
    EXIT_APPLICATION_MODE,
    CaptureDriver,
    active_driver,
)
from textual_wasm.probe import FORBIDDEN_DRIVER_MODULES, TRUECOLOR_SGR, run_probe
from textual_wasm.report import CheckStatus, ProbeReport


async def test_every_check_passes_natively() -> None:
    report = await run_probe()
    assert report.failures == ()
    assert {result.status for result in report.checks} == {CheckStatus.PASS}


async def test_report_survives_a_json_round_trip() -> None:
    """The WASM report crosses a process boundary as text; the native one must too."""
    report = await run_probe()
    assert ProbeReport.from_json(report.to_json()) == report


async def test_driver_emits_application_mode_around_the_render() -> None:
    report = await run_probe()
    assert report.ok
    driver = active_driver()
    assert isinstance(driver, CaptureDriver)
    assert driver.output.startswith("".join(ENTER_APPLICATION_MODE))
    assert driver.output.endswith("".join(EXIT_APPLICATION_MODE))


async def test_rendered_output_excludes_the_drivers_own_preamble() -> None:
    """An 'is there ANSI' assertion must not be satisfiable by the driver's own writes."""
    await run_probe()
    driver = active_driver()
    assert TRUECOLOR_SGR not in "".join(ENTER_APPLICATION_MODE)
    assert TRUECOLOR_SGR in driver.rendered_output
    assert MARKER not in "".join(ENTER_APPLICATION_MODE)


async def test_forced_size_reaches_the_app() -> None:
    report = await run_probe(size=(120, 40))
    assert report.ok, report.failures


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
