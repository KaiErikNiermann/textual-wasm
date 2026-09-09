"""Tests for the app reference every leg of a check is pointed at."""

from __future__ import annotations

from pathlib import Path

import pytest

from textual_wasm.app import HINT_TEMPLATE, MARKER, SpikeApp
from textual_wasm.target import SPIKE_ENTRY, SPIKE_TARGET, AppTarget, EntryError, resolve_target


def test_the_demo_targets_markers_are_the_demo_apps_own_strings() -> None:
    """`target` restates them so hosts can read it without importing Textual.

    A copy is a thing that drifts, and a drifted ready marker does not fail loudly - the
    harness waits out its timeout and reports that the app never drew.
    """
    assert SPIKE_TARGET.ready_marker == MARKER
    assert SPIKE_TARGET.load() is SpikeApp
    assert SPIKE_TARGET.settled_marker is not None
    assert SPIKE_TARGET.settled_marker in HINT_TEMPLATE.format(count=1)


def test_an_entry_without_a_colon_is_rejected_where_it_is_written() -> None:
    with pytest.raises(EntryError, match="module:AppClass"):
        AppTarget(entry="textual_wasm.app.SpikeApp")


def test_keys_without_a_settled_marker_are_rejected() -> None:
    """Otherwise the capture races the app and the result depends on machine load."""
    with pytest.raises(EntryError, match="settled marker"):
        AppTarget(entry="mod:App", keys="a")


def test_a_missing_attribute_names_the_attribute() -> None:
    with pytest.raises(EntryError, match="Nope"):
        AppTarget(entry="textual_wasm.app:Nope").load()


def test_naming_no_app_yields_the_demo_complete_with_its_markers() -> None:
    """So `check` with no arguments is a whole run, not one with two checks skipped."""
    assert resolve_target(None) == SPIKE_TARGET
    assert resolve_target(SPIKE_ENTRY) == SPIKE_TARGET


def test_an_unknown_app_starts_with_no_markers() -> None:
    resolved = resolve_target("myapp:App")
    assert resolved.ready_marker is None
    assert not resolved.exercises_input


def test_markers_given_on_the_command_line_win() -> None:
    resolved = resolve_target(SPIKE_ENTRY, ready_marker="something else", keys="")
    assert resolved.ready_marker == "something else"
    assert resolved.keys == ""


def test_verify_accepts_an_app() -> None:
    assert AppTarget(entry="tests.bare_app:BareApp").verify() is None


def test_verify_rejects_something_that_is_not_an_app() -> None:
    """Resolving is not enough; the name has to be runnable."""
    with pytest.raises(EntryError, match="not a Textual App"):
        AppTarget(entry="tests.bare_app:Static").verify()


def test_verify_rejects_a_missing_attribute() -> None:
    with pytest.raises(EntryError, match="has no 'Nope'"):
        AppTarget(entry="tests.bare_app:Nope").verify()


def test_verify_rejects_a_missing_entry_module() -> None:
    """A module that does not exist is a typo, and typos are the point of this check."""
    with pytest.raises(ModuleNotFoundError):
        AppTarget(entry="no_such_module_at_all:App").verify()


def test_verify_tolerates_a_dependency_that_only_exists_in_the_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An app may import a distribution `micropip` installs at boot and this machine lacks.

    Declaring one with `--requirement` is the supported way to do that, so failing the build
    would reject a correct project - and pushing people to switch verification off wholesale
    would lose the check for the typos it exists to catch.
    """
    package = tmp_path / "browser_only"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(
        "import a_distribution_installed_by_micropip\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    note = AppTarget(entry="browser_only.app:Whatever").verify()

    assert note is not None
    assert "a_distribution_installed_by_micropip" in note
