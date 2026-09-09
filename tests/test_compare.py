"""Tests for the comparison that constitutes the experiment's verdict."""

from __future__ import annotations

import dataclasses

import pytest

from textual_wasm.compare import compare
from textual_wasm.report import CheckId, CheckResult, CheckStatus, ProbeReport, RuntimeFacts
from textual_wasm.screen import RenderedScreen

_NATIVE_RUNTIME = RuntimeFacts(
    platform="linux",
    python_version="3.14.7",
    textual_version="8.2.8",
    event_loop="_UnixSelectorEventLoop",
    threads_available=True,
    eager_task_factory_accepted=True,
    polyfills_applied=(),
    runtime="native",
    jspi=False,
    shared_memory=True,
    cross_origin_isolated=None,
)

_WASM_RUNTIME = dataclasses.replace(
    _NATIVE_RUNTIME,
    platform="emscripten",
    python_version="3.14.2",
    event_loop="WebLoop",
    threads_available=False,
    polyfills_applied=("asyncio.tasks._set_task_name",),
    runtime="Node.js/26",
    jspi=True,
    shared_memory=False,
)


_SCREEN = RenderedScreen(columns=80, rows=24, lines=("hello",))


_TARGET = "textual_wasm.app:SpikeApp"


def _report(runtime: RuntimeFacts, *statuses: CheckStatus) -> ProbeReport:
    return ProbeReport(
        target=_TARGET,
        runtime=runtime,
        checks=tuple(
            CheckResult(check, status, "") for check, status in zip(CheckId, statuses, strict=True)
        ),
        screen=_SCREEN,
    )


_ALL_PASS = (CheckStatus.PASS,) * len(CheckId)


def test_identical_passing_runs_are_equivalent() -> None:
    result = compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), _report(_WASM_RUNTIME, *_ALL_PASS))
    assert result.equivalent
    assert result.disagreements == ()
    assert result.unexpected_differences == ()


def test_expected_host_differences_do_not_break_equivalence() -> None:
    result = compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), _report(_WASM_RUNTIME, *_ALL_PASS))
    assert {d.field for d in result.runtime_differences} == {
        "platform",
        "python_version",
        "event_loop",
        "threads_available",
        "polyfills_applied",
        "runtime",
        "jspi",
        "shared_memory",
    }


def test_a_differing_textual_version_voids_the_comparison() -> None:
    """Two runs on different Textual builds are not comparable, however green they look."""
    mismatched = dataclasses.replace(_WASM_RUNTIME, textual_version="8.1.0")
    result = compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), _report(mismatched, *_ALL_PASS))
    assert not result.equivalent
    assert [d.field for d in result.unexpected_differences] == ["textual_version"]


def test_disagreement_is_reported() -> None:
    wasm_statuses = (CheckStatus.FAIL, *(CheckStatus.PASS,) * (len(CheckId) - 1))
    result = compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), _report(_WASM_RUNTIME, *wasm_statuses))
    assert not result.equivalent
    assert [a.check for a in result.disagreements] == [next(iter(CheckId))]


def test_reports_covering_different_checks_are_rejected() -> None:
    partial = ProbeReport(
        target=_TARGET,
        runtime=_WASM_RUNTIME,
        checks=(CheckResult(CheckId.TIMER, CheckStatus.PASS, ""),),
        screen=_SCREEN,
    )
    with pytest.raises(ValueError, match="different checks"):
        compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), partial)


def test_reports_of_different_applications_are_rejected() -> None:
    """The checks would line up perfectly, and the verdict would be about nothing."""
    other = dataclasses.replace(_report(_WASM_RUNTIME, *_ALL_PASS), target="other:App")
    with pytest.raises(ValueError, match="different applications"):
        compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), other)


def test_a_check_skipped_on_both_hosts_is_agreement() -> None:
    """An app that declares no keystroke does not exercise input on *either* runtime.

    Reporting that as non-equivalent would make the verdict a statement about the app's
    shape rather than about the runtimes.
    """
    statuses = (*(CheckStatus.PASS,) * (len(CheckId) - 1), CheckStatus.SKIP)
    result = compare(_report(_NATIVE_RUNTIME, *statuses), _report(_WASM_RUNTIME, *statuses))
    assert result.equivalent


def test_an_all_skipped_run_is_not_vacuously_equivalent() -> None:
    skipped = (CheckStatus.SKIP,) * len(CheckId)
    result = compare(_report(_NATIVE_RUNTIME, *skipped), _report(_WASM_RUNTIME, *skipped))
    assert not result.equivalent
