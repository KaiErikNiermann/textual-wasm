"""Tests for the porting doctor.

Structured around a planted fixture, like the semgrep suite, because the same failure mode
applies: a rule that silently stops matching looks exactly like a clean codebase, and three
of the semgrep rules were broken on the day they were written.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

import pytest

from textual_wasm import diagnostics, doctor
from textual_wasm.diagnostics.errors import WasmCompatibilityWarning
from textual_wasm.doctor.deps import Catalogue, Dependency, DependencyState
from textual_wasm.doctor.scan import scan_source
from textual_wasm.substitutions import Severity

FIXTURE: Final[Path] = Path(__file__).parent / "doctor" / "unportable_app.py"

PLANTED: Final[frozenset[str]] = frozenset(
    {
        "os.system",
        "time.sleep",
        "threading.thread",
        "concurrent.thread_pool",
        "curses",
        "termios.tcsetattr",
        "fcntl.ioctl",
        "pty.openpty",
        "socket.bind",
    }
)
"""Every problem deliberately written into the fixture."""


@pytest.fixture(scope="module")
def report() -> doctor.DoctorReport:
    return doctor.run(FIXTURE)


def test_every_planted_problem_is_found(report: doctor.DoctorReport) -> None:
    found = {finding.substitution.id for finding in report.findings}
    assert found >= PLANTED, f"missed: {PLANTED - found}"


def test_the_fixture_does_not_pass(report: doctor.DoctorReport) -> None:
    assert not report.ok
    assert report.blocking_findings


def test_findings_carry_a_usable_location(report: doctor.DoctorReport) -> None:
    """`file:line` is the whole point; a finding without one is not actionable."""
    for finding in report.findings:
        assert finding.line > 0
        assert finding.location.endswith(f":{finding.line}")
        assert finding.source, "no source line captured"


def test_worst_findings_come_first(report: doctor.DoctorReport) -> None:
    """A truncated report must show the dangerous class, not the alphabetically first."""
    order = list(Severity)
    severities = [order.index(f.substitution.severity) for f in report.findings]
    assert severities == sorted(severities)


def test_this_project_is_itself_clean() -> None:
    """The module that tells people to avoid these must not use them."""
    assert doctor.run(Path("src/textual_wasm")).ok


# --- the scanner ------------------------------------------------------------------------


def test_a_bare_imported_name_is_still_matched() -> None:
    """`from os import system` then `system(...)` is the same call written differently."""
    findings = scan_source("from os import system\nsystem('ls')\n", Path("x.py"))
    assert "os.system" in {f.substitution.id for f in findings}


def test_a_dynamic_call_target_is_not_guessed_at() -> None:
    """`get_module().system()` cannot honestly be claimed to be `os.system`."""
    findings = scan_source("get_module().system('ls')\n", Path("x.py"))
    assert findings == ()


def test_the_same_line_is_not_reported_twice() -> None:
    """One line matching two rules is one piece of advice; repeating it trains skimming."""
    findings = scan_source("import threading\n", Path("x.py"))
    assert len(findings) == len({(f.substitution.id, f.line) for f in findings})


def test_a_pragma_with_a_reason_suppresses_a_finding() -> None:
    """Legitimate native-only code is normal; a doctor with no escape hatch gets ignored."""
    source = "import os\nos.system('git status')  # textual-wasm: allow os.system - native tool\n"
    assert scan_source(source, Path("x.py")) == ()


def test_a_pragma_on_the_line_above_also_works() -> None:
    source = "import os\n# textual-wasm: allow os.system - native tool\nos.system('git status')\n"
    assert scan_source(source, Path("x.py")) == ()


def test_a_pragma_without_a_reason_does_not_suppress() -> None:
    """Same rule this repository applies to `nosemgrep`: an exemption must be justified."""
    source = "import os\nos.system('git status')  # textual-wasm: allow os.system\n"
    assert {f.substitution.id for f in scan_source(source, Path("x.py"))} == {"os.system"}


def test_a_pragma_only_suppresses_what_it_names() -> None:
    source = (
        "import os\nimport time\n"
        "os.system('x')  # textual-wasm: allow time.sleep - wrong id on purpose\n"
    )
    assert {f.substitution.id for f in scan_source(source, Path("x.py"))} == {"os.system"}


def test_unparseable_source_is_not_swallowed() -> None:
    """A file that will not parse is a fact worth reporting, not one to hide."""
    with pytest.raises(SyntaxError):
        scan_source("def (:\n", Path("x.py"))


def test_scanner_and_guard_agree_about_the_zero_sleep() -> None:
    """The static rule and the runtime guard must not contradict each other.

    `time.sleep(0)` is the yield idiom. If the doctor flagged what the guard deliberately
    lets through, the report would be noisy in exactly the place people notice.
    """
    assert scan_source("import time\ntime.sleep(0)\n", Path("x.py")) == ()

    diagnostics.install(force=True)
    try:
        with pytest.warns(WasmCompatibilityWarning):
            time.sleep(0.001)
        recorded_before = len(diagnostics.recorded())
        time.sleep(0)
        assert len(diagnostics.recorded()) == recorded_before, "guard reported a zero sleep"
    finally:
        diagnostics.uninstall()


# --- dependencies -----------------------------------------------------------------------


def _catalogue() -> Catalogue:
    return Catalogue(
        version="3.14.2",
        packages={
            "numpy": Dependency("numpy", DependencyState.BUNDLED_NATIVE, "2.4.6"),
            "rich": Dependency("rich", DependencyState.PURE),
        },
    )


def test_a_bundled_native_package_reports_its_pinned_version() -> None:
    """It works, at Pyodide's version and no other - a constraint people meet late."""
    dependency = _catalogue().classify("numpy")
    assert dependency.state is DependencyState.BUNDLED_NATIVE
    assert "2.4.6" in dependency.guidance
    assert not dependency.blocks


def test_names_are_normalised_before_lookup() -> None:
    """`typing_extensions` and `typing-extensions` are the same distribution."""
    catalogue = Catalogue(
        version="x", packages={"typing-extensions": Dependency("t", DependencyState.PURE)}
    )
    assert catalogue.classify("typing_extensions").state is DependencyState.PURE


def test_an_uninspectable_package_is_unknown_not_assumed_fine() -> None:
    """Guessing "probably pure" about the one category that blocks loses the doctor's trust."""
    assert _catalogue().classify("definitely-not-installed-xyz").state is DependencyState.UNKNOWN


def test_a_locally_compiled_package_is_detected_as_unavailable() -> None:
    """A distribution shipping a .so cannot be fetched from PyPI by micropip at any version."""
    assert _catalogue().classify("pydantic-core").state is DependencyState.UNAVAILABLE


def test_a_pure_local_package_is_installable() -> None:
    assert _catalogue().classify("typer").state is DependencyState.PURE


@pytest.mark.skipif(
    not doctor.DEFAULT_LOCKFILE.exists(),
    reason=f"{doctor.DEFAULT_LOCKFILE} not present; install the Pyodide runtime",
)
def test_the_real_lockfile_classifies_the_projects_own_pins() -> None:
    """Guards the lock-file reader against a schema change in the vendored runtime.

    Skipped rather than failed without the runtime: it reads a file a contributor may not
    have fetched, and a suite that fails for a missing optional tool is one people learn to
    ignore.
    """
    catalogue = doctor.load_catalogue()
    assert catalogue.packages
    assert catalogue.classify("rich").state is DependencyState.PURE
    assert catalogue.classify("numpy").state is DependencyState.BUNDLED_NATIVE
