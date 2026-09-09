"""Tests for the real-terminal reference capture.

Skipped without tmux, the same way the semgrep suite is skipped without semgrep: a machine
that cannot produce the reference can still run every other part of the experiment, and a
suite that fails for a missing tool teaches people to ignore it.
"""

from __future__ import annotations

import pytest

from textual_wasm import terminal
from textual_wasm.app import MARKER, WIDTH_SAMPLES

pytestmark = pytest.mark.skipif(terminal.TMUX is None, reason="tmux is not installed")

GRID = (80, 24)


@pytest.fixture(scope="module")
def reference() -> terminal.RenderedScreen:
    """One capture for the whole module; each costs a real app start."""
    return terminal.capture_spike(columns=GRID[0], rows=GRID[1])


def test_the_app_renders_in_a_real_terminal(reference: terminal.RenderedScreen) -> None:
    assert any(MARKER in line for line in reference.lines)


def test_the_capture_waits_for_the_keystroke_to_be_handled(
    reference: terminal.RenderedScreen,
) -> None:
    """Without a settled marker the capture races the app and sometimes reads 'pressed 0'."""
    assert any(terminal.SETTLED_MARKER in line for line in reference.lines)


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
        terminal.capture_spike(columns=GRID[0], rows=GRID[1])
