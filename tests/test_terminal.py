"""Tests for the real-terminal reference capture.

Skipped without tmux, the same way the semgrep suite is skipped without semgrep: a machine
that cannot produce the reference can still run every other part of the experiment, and a
suite that fails for a missing tool teaches people to ignore it.
"""

from __future__ import annotations

import pytest

from textual_wasm import terminal
from textual_wasm.app import WIDTH_SAMPLES
from textual_wasm.target import SPIKE_TARGET

_USABLE, _REASON = terminal.usable()
pytestmark = pytest.mark.skipif(not _USABLE, reason=_REASON)

GRID = (80, 24)


@pytest.fixture(scope="module")
def reference() -> terminal.RenderedScreen:
    """One capture for the whole module; each costs a real app start."""
    return terminal.capture_target(SPIKE_TARGET, columns=GRID[0], rows=GRID[1])


def test_the_app_renders_in_a_real_terminal(reference: terminal.RenderedScreen) -> None:
    assert SPIKE_TARGET.ready_marker is not None
    assert reference.contains(SPIKE_TARGET.ready_marker)


def test_the_capture_waits_for_the_keystroke_to_be_handled(
    reference: terminal.RenderedScreen,
) -> None:
    """Without a settled marker the capture races the app and sometimes reads 'pressed 0'."""
    assert SPIKE_TARGET.settled_marker is not None
    assert reference.contains(SPIKE_TARGET.settled_marker)


def test_every_width_sample_survives_a_real_terminal(
    reference: terminal.RenderedScreen,
) -> None:
    """Each sample ends in a terminator; a mis-measured width would move or drop it.

    This is the assertion pyte could not make - it discards the rest of the line after a
    zero-width joiner or a variation selector, so two of these samples were invisible to it.
    """
    rendered = {line.split(maxsplit=1)[0]: line for line in reference.lines if line and " " in line}
    for name, _sample in WIDTH_SAMPLES:
        assert name in rendered, f"sample {name!r} did not render"
        assert rendered[name].endswith("|"), f"sample {name!r} lost its terminator"


def test_capture_reports_which_emulator_produced_it() -> None:
    assert terminal.version().startswith("tmux")


def test_capture_without_tmux_is_an_explicit_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(terminal, "TMUX", None)
    with pytest.raises(terminal.TmuxUnavailableError):
        terminal.capture_target(SPIKE_TARGET, columns=GRID[0], rows=GRID[1])


def test_an_old_tmux_is_refused_as_a_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measured: fed the same bytes, tmux 3.4 and Chrome place a VS16 emoji in different
    columns, while 3.7c and Chrome agree. Capturing from the old one anyway reports a
    disagreement about tmux as though it were one about the browser."""
    monkeypatch.setattr(terminal, "version", lambda: "tmux 3.4")
    usable, reason = terminal.usable()
    assert not usable
    assert "3.5" in reason


def test_a_patch_suffix_does_not_confuse_the_version_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tmux appends a letter to patch releases: `3.5a` is newer than `3.5`, not unparseable."""
    monkeypatch.setattr(terminal, "version", lambda: "tmux 3.5a")
    usable, _reason = terminal.usable()
    assert usable
