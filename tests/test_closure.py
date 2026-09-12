"""Requirements checked against each other, rather than against Pyodide.

The failure this catches is the largest single category in the add-on survey and the
quietest: five libraries cap Textual below the version this project pins, and
`micropip.install(name)` *succeeds* for every one of them by resolving Textual down. Nothing
raises, at install or at import. The application then runs against a Textual it was not
written for.

Declared metadata is stubbed rather than read from whatever happens to be installed in the
test environment. A test whose result depends on the developer's virtualenv passes or fails
for reasons that have nothing to do with the code.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from textual_wasm.doctor import closure

if TYPE_CHECKING:
    from collections.abc import Sequence

PINS: Final[tuple[str, ...]] = ("textual==8.2.8", "rich==15.0.0", "pyte==0.8.2")
"""A closure shaped like the one `textual-wasm pins` writes."""

DECLARED: Final[dict[str, tuple[str, ...]]] = {
    # The real metadata of the five capped libraries, and of one that is fine.
    "textual-window": ("textual<6.0.0,>=5.1.0",),
    "textual-slidecontainer": ("textual<6.0.0,>=3.0.0",),
    "textual-spinbox": ("textual<2.1.3,>=1.0.0",),
    "textual-timepiece": ("textual<9.0.0,>=6.0.0",),
    "textual-autocomplete": ("textual>=2.0.0", "typing-extensions>=4.5.0"),
    "textual": (),
    "rich": (),
    "pyte": (),
}


def _stub(distribution: str) -> tuple[str, ...] | None:
    """Answer "what does this distribution declare" from the table above."""
    return DECLARED.get(distribution)


def _check(requirements: Sequence[str]) -> closure.ClosureReport:
    """Check against the stated metadata rather than whatever is installed here."""
    return closure.check(requirements, declared=_stub)


def _names(conflicts: Sequence[closure.ClosureConflict]) -> set[str]:
    return {conflict.dependent for conflict in conflicts}


def test_a_cap_below_the_pinned_version_is_a_conflict() -> None:
    report = _check([*PINS, "textual-window"])
    assert _names(report.conflicts) == {"textual-window"}
    conflict = report.conflicts[0]
    assert conflict.dependency == "textual"
    assert conflict.pinned == "8.2.8"
    assert conflict.declared == "textual<6.0.0,>=5.1.0"


def test_every_capped_library_in_the_survey_is_caught() -> None:
    """Three real caps, each of which installs cleanly on its own."""
    capped = ["textual-window", "textual-slidecontainer", "textual-spinbox"]
    report = _check([*PINS, *capped])
    assert _names(report.conflicts) == set(capped)


def test_a_cap_that_admits_the_pinned_version_is_not_a_conflict() -> None:
    """`textual-timepiece` allows `>=6.0.0,<9.0.0`, which includes 8.2.8 - the one library in
    the survey whose cap is wide enough."""
    assert _check([*PINS, "textual-timepiece"]).ok


def test_an_uncapped_requirement_is_not_a_conflict() -> None:
    assert _check([*PINS, "textual-autocomplete"]).ok


def test_a_closure_with_no_pins_has_nothing_to_contradict() -> None:
    """Only `==` counts as a pin. A range against a range is the resolver's business, and
    guessing at it here would invent conflicts that may not exist."""
    assert _check(["textual>=8", "textual-window"]).ok


def test_a_distribution_that_is_not_installed_is_reported_not_assumed_fine() -> None:
    """The whole point: "nothing was checked" must not read as "nothing is wrong"."""
    report = _check([*PINS, "some-library-nobody-has"])
    assert report.unexpanded == ("some-library-nobody-has",)
    assert report.ok


def test_a_marker_false_under_emscripten_cannot_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Windows-only or extra-gated requirement is never installed, so its cap is moot."""
    monkeypatch.setitem(DECLARED, "windows-only", ('textual<6.0.0; sys_platform == "win32"',))
    monkeypatch.setitem(DECLARED, "extra-only", ('textual<6.0.0; extra == "dev"',))
    assert _check([*PINS, "windows-only", "extra-only"]).ok


def test_an_unparseable_requirement_is_skipped_not_fatal() -> None:
    """Requirement lists arrive from files people edit by hand."""
    assert _check(["textual==8.2.8", "not a requirement!!"]).ok


def test_this_projects_own_closure_is_self_consistent() -> None:
    """The regression guard, against real metadata rather than the stub.

    `wasm-requirements.txt` is what every build installs; if it contradicted itself the
    build would now refuse to run at all.
    """
    root = Path(__file__).resolve().parent.parent
    requirements = [
        line.strip()
        for line in (root / "wasm-requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    # The real metadata this time, deliberately: the point is that the file every build
    # installs does not contradict itself.
    report = closure.check(requirements)
    assert report.ok, [conflict.guidance for conflict in report.conflicts]
