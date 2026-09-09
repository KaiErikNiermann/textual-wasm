"""Tests for the comparison that constitutes the experiment's verdict."""

from __future__ import annotations

import dataclasses

import pytest

from textual_wasm.compare import compare
from textual_wasm.report import CheckId, CheckResult, CheckStatus, ProbeReport, RuntimeFacts

_NATIVE_RUNTIME = RuntimeFacts(
    platform="linux",
    python_version="3.14.7",
    textual_version="8.2.8",
    event_loop="_UnixSelectorEventLoop",
    threads_available=True,
    eager_task_factory_accepted=True,
    polyfills_applied=(),
)

_WASM_RUNTIME = dataclasses.replace(
    _NATIVE_RUNTIME,
    platform="emscripten",
    python_version="3.14.2",
    event_loop="WebLoop",
    threads_available=False,
    polyfills_applied=("asyncio.tasks._set_task_name",),
)


def _report(runtime: RuntimeFacts, *statuses: CheckStatus) -> ProbeReport:
    return ProbeReport(
        runtime=runtime,
        checks=tuple(
            CheckResult(check, status, "") for check, status in zip(CheckId, statuses, strict=True)
        ),
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
        runtime=_WASM_RUNTIME,
        checks=(CheckResult(CheckId.TIMER, CheckStatus.PASS, ""),),
    )
    with pytest.raises(ValueError, match="different checks"):
        compare(_report(_NATIVE_RUNTIME, *_ALL_PASS), partial)
