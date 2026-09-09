"""Tests for the grid replay and the diff built on it."""

from __future__ import annotations

import pytest

from textual_wasm.compare import compare_screens
from textual_wasm.screen import RenderedScreen, normalise, replay


def test_replay_places_text_where_the_cursor_put_it() -> None:
    grid = replay("\x1b[2J\x1b[3;5Hhello", columns=20, rows=5)
    assert grid.lines == ("", "", "    hello")


def test_replay_keeps_wide_characters_in_two_columns() -> None:
    """A width table that called CJK narrow would put the terminator four columns early."""
    grid = replay("\x1b[2J\x1b[H世界|", columns=20, rows=1)
    assert grid.lines[0] == "世界|"


def test_normalise_drops_trailing_blanks() -> None:
    assert normalise(("a   ", "   ", "")) == ("a",)


def test_normalise_composes_to_nfc() -> None:
    """pyte yields a composed character, xterm.js the codepoints it was sent.

    Both are one column painting one glyph, so this must not read as a divergence.
    """
    assert normalise(("é",)) == normalise(("é",))


def test_diff_reports_the_column_where_rows_stop_agreeing() -> None:
    left = RenderedScreen(columns=20, rows=2, lines=("same", "abcXef"))
    right = RenderedScreen(columns=20, rows=2, lines=("same", "abcYef"))
    (diff,) = left.diff(right)
    assert (diff.row, diff.first_divergent_column) == (1, 3)


def test_grids_of_different_sizes_are_rejected() -> None:
    """A row-by-row diff of differently sized grids is meaningless, not merely noisy."""
    with pytest.raises(ValueError, match="differ in size"):
        compare_screens(
            RenderedScreen(columns=80, rows=24, lines=()),
            RenderedScreen(columns=100, rows=24, lines=()),
        )


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("variation selector", "⚠️|"),
        ("zero-width joiner", "\U0001f469‍\U0001f4bb|"),
    ],
)
def test_pyte_still_truncates_after_a_joiner_or_variation_selector(name: str, text: str) -> None:
    """Characterisation test pinning why emoji are absent from the width samples.

    pyte 0.8.2 discards the remainder of the line after U+200D or U+FE0F, while xterm.js
    preserves it - so on these sequences the oracle is wrong and the browser is right, and
    pyte cannot adjudicate them. If this ever starts failing, pyte has been fixed and the
    emoji samples should go back into `app.WIDTH_SAMPLES`.
    """
    assert not replay(text, columns=20, rows=1).lines[0].endswith("|"), name
