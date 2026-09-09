"""The WASM dependency closure is walked, not listed."""

from __future__ import annotations

from pathlib import Path

from textual_wasm.pins import ROOT_DISTRIBUTIONS, closure, resolve_pins, write_pins

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / "wasm-requirements.txt"


def test_extras_are_followed() -> None:
    """The regression this module was rewritten for.

    A hand-written list of distribution names cannot express `markdown-it-py[linkify]`, and
    its absence is invisible until Textual's own Markdown widget runs in a browser and dies
    with "Linkify enabled but not installed" - three layers from the list that was wrong.
    """
    assert "linkify-it-py" in closure()


def test_the_roots_are_in_the_closure() -> None:
    assert set(ROOT_DISTRIBUTIONS) <= set(closure())


def test_nothing_appears_twice() -> None:
    """A distribution reached by two paths is one install, not two conflicting pins."""
    names = closure()
    assert len(names) == len(set(names))


def test_every_pin_carries_an_exact_version() -> None:
    assert all("==" in pin for pin in resolve_pins())


def test_the_committed_requirements_match_the_environment(tmp_path: Path) -> None:
    """Two runtimes cannot be compared unless they load the same code."""
    regenerated = tmp_path / "wasm-requirements.txt"
    write_pins(regenerated)
    assert regenerated.read_text(encoding="utf-8") == REQUIREMENTS.read_text(encoding="utf-8"), (
        "wasm-requirements.txt is out of date; run `textual-wasm pins`"
    )
