"""Tests for the orchestrator that runs one app on every runtime available."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from textual_wasm import check as check_module
from textual_wasm import node
from textual_wasm.check import (
    CheckReport,
    Leg,
    LegOutcome,
    LegStatus,
    package_directory,
    run_check,
)
from textual_wasm.target import SPIKE_TARGET, AppTarget

UNAVAILABLE = node.NodeAvailability(node=None, resolve_from=None, missing=("pyodide",))


def _outcome(leg: Leg, status: LegStatus) -> LegOutcome:
    return LegOutcome(leg, status, "")


def test_the_apps_package_is_found_through_the_import_system() -> None:
    """Not guessed from the entry string, so an installed app works like a local one."""
    assert package_directory(SPIKE_TARGET) == Path(check_module.__file__).parent


def test_a_single_module_app_is_refused_with_the_reason() -> None:
    """A build copies a directory; a lone module has none to copy."""
    with pytest.raises(ValueError, match="not a package"):
        package_directory(AppTarget(entry="dataclasses:Field"))


def test_a_skipped_leg_is_not_a_failure() -> None:
    """A machine without Node still gets a verdict about the runtimes it does have.

    A check that fails for a missing tool teaches people to ignore its result.
    """
    report = CheckReport(
        target=SPIKE_TARGET.entry,
        size=(80, 24),
        legs=(
            _outcome(Leg.NATIVE, LegStatus.RAN),
            _outcome(Leg.WASM, LegStatus.SKIPPED),
        ),
    )
    assert report.ok
    assert [leg.leg for leg in report.skipped] == [Leg.WASM]


def test_a_failed_leg_is_a_failure() -> None:
    report = CheckReport(
        target=SPIKE_TARGET.entry,
        size=(80, 24),
        legs=(_outcome(Leg.NATIVE, LegStatus.FAILED),),
    )
    assert not report.ok


def test_the_check_runs_the_legs_it_can_and_says_why_not_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The native leg alone still produces a report, with fixes attached to the others."""

    def unavailable(packages: Sequence[str], *, start: Path | None = None) -> node.NodeAvailability:
        return UNAVAILABLE

    monkeypatch.setattr(check_module.node, "availability", unavailable)
    monkeypatch.setattr(check_module, "TMUX", None)

    report = run_check(SPIKE_TARGET)

    assert report.ok
    assert report.runtimes is None
    assert report.render_diffs is None
    statuses = {leg.leg: leg.status for leg in report.legs}
    assert statuses[Leg.NATIVE] is LegStatus.RAN
    assert statuses[Leg.WASM] is LegStatus.SKIPPED
    assert all("install" in leg.detail or "tmux" in leg.detail for leg in report.skipped)
