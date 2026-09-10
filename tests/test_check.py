"""Tests for the orchestrator that runs one app on every runtime available."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from textual_wasm import check as check_module
from textual_wasm import node
from textual_wasm.check import CheckReport, Leg, LegOutcome, LegStatus, run_check
from textual_wasm.target import SPIKE_TARGET, AppTarget, EntryError

UNAVAILABLE = node.NodeAvailability(node=None, resolve_from=None, missing=("pyodide",))


def _outcome(leg: Leg, status: LegStatus) -> LegOutcome:
    return LegOutcome(leg, status, "")


def test_the_apps_package_is_found_through_the_import_system() -> None:
    """Not guessed from the entry string, so an installed app works like a local one."""
    assert SPIKE_TARGET.package_directory() == Path(check_module.__file__).parent


def test_a_single_module_app_is_refused_with_the_reason() -> None:
    """A build copies a directory; a lone module has none to copy."""
    with pytest.raises(EntryError, match="not a package"):
        AppTarget(entry="dataclasses:Field").package_directory()


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
    monkeypatch.setattr(
        check_module, "terminal_usable", lambda: (False, "tmux is not installed; ...")
    )

    report = run_check(SPIKE_TARGET)

    assert report.ok
    assert report.runtimes is None
    assert report.render_diffs is None
    statuses = {leg.leg: leg.status for leg in report.legs}
    assert statuses[Leg.NATIVE] is LegStatus.RAN
    assert statuses[Leg.WASM] is LegStatus.SKIPPED
    assert all("install" in leg.detail or "tmux" in leg.detail for leg in report.skipped)


def test_a_leg_that_blows_up_is_reported_rather_than_raised() -> None:
    """One broken leg must not take the other three down with it.

    Pointed at ten real applications from GitHub, this command died three separate ways - a
    dependency that would not install under Pyodide, a `tmux` session that had already
    exited, and a harness that wrote no JSON. Each printed a traceback and no leg results at
    all, throwing away the legs that had worked.
    """

    def explode() -> tuple[LegOutcome, None]:
        raise RuntimeError("the multiplexer went away")

    outcome, observation = check_module._guarded(Leg.TERMINAL, explode)  # pyright: ignore[reportPrivateUsage]

    assert outcome.status is LegStatus.FAILED
    assert outcome.leg is Leg.TERMINAL
    assert "the multiplexer went away" in outcome.detail
    assert observation is None


def test_a_working_leg_passes_through_untouched() -> None:
    """The guard must be invisible when nothing goes wrong."""
    expected = (LegOutcome(Leg.NATIVE, LegStatus.RAN, "8 checks, 0 failed"), "observation")

    assert check_module._guarded(Leg.NATIVE, lambda: expected) == expected  # pyright: ignore[reportPrivateUsage]


def test_a_failure_message_survives_a_minified_runtime() -> None:
    """Pyodide's runtime is a quarter of a megabyte of minified JavaScript.

    An exception thrown inside a harness drags all of it into stderr, and the line that says
    what went wrong is somewhere in the middle. Reporting the *first* surviving lines showed
    `Loading micropip` - progress printed before the failure - for six real applications in
    a row.
    """
    noise = "Loading micropip\nLoaded micropip\n" + "async function f(){var " + "x=1;" * 200
    failure = "ModuleNotFoundError: No module named 'xdg'"
    message = f"harness produced no JSON (exit 1); stderr:\n{noise}\n{failure}"

    detail = check_module._first_lines(message)  # pyright: ignore[reportPrivateUsage]

    assert "No module named 'xdg'" in detail
    assert "async function" not in detail
    assert "Loading micropip" not in detail


def test_a_long_diagnostic_is_kept_even_though_it_is_long() -> None:
    """`micropip` explains a version conflict in one 260-character sentence.

    It names both versions and the way out, and a cap tuned to reject minified code threw
    away the single most useful line in a thousand.
    """
    conflict = (
        "ValueError: Requested 'textual<0.44.0,>=0.43.0', but textual==8.2.8 is already "
        "installed. If you want to reinstall the package with a different version, use "
        "micropip.install(..., reinstall=True) to force reinstall."
    )

    detail = check_module._first_lines(f"stderr:\n{'z' * 5000}\n{conflict}")  # pyright: ignore[reportPrivateUsage]

    assert "textual<0.44.0" in detail
    assert "z" * 100 not in detail


def test_a_driver_keeps_the_command_that_fixes_it() -> None:
    """A complaint without its remedy is half an answer."""
    detail = check_module._first_lines(  # pyright: ignore[reportPrivateUsage]
        "Host system is missing dependencies\nRun: playwright install --with-deps"
    )

    assert "missing dependencies" in detail
    assert "playwright install --with-deps" in detail
