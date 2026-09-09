"""Tests for the app reference every leg of a check is pointed at."""

from __future__ import annotations

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
