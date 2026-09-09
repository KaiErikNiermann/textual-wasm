"""Replay a terminal byte stream into a character grid.

The cross-runtime probe proves the two Python runtimes emit the *same bytes*. That is a
strong result and an incomplete one: a byte stream is only a rendering instruction, and the
open question in the feasibility study is whether a browser terminal emulator turns it into
the same grid a real terminal would.

Answering that needs the stream interpreted, not compared. `pyte` is a terminal emulator in
pure Python, so it runs in both runtimes and gives a grid that can be diffed against the one
`xterm.js` produces from the identical input.

Three width tables are involved and they are not the same code: Textual lays out using
`rich`'s `cell_len`, `pyte` uses `wcwidth`, and `xterm.js` uses its own. A disagreement
between the last two, on output produced by the first, is exactly the font-metric risk the
study flagged - located to the character rather than described.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from typing import TYPE_CHECKING

import pyte

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclasses.dataclass(frozen=True, slots=True)
class LineDiff:
    """One row on which two grids disagree."""

    row: int
    left: str
    right: str

    @property
    def first_divergent_column(self) -> int:
        """Column where the two rows stop matching, which is where a width bug shows."""
        for column, (a, b) in enumerate(zip(self.left, self.right, strict=False)):
            if a != b:
                return column
        return min(len(self.left), len(self.right))


@dataclasses.dataclass(frozen=True, slots=True)
class RenderedScreen:
    """The visible character grid, trailing blanks removed."""

    columns: int
    rows: int
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def diff(self, other: RenderedScreen) -> tuple[LineDiff, ...]:
        """Rows on which this grid and `other` disagree."""
        return tuple(self._diff_lines(other))

    def _diff_lines(self, other: RenderedScreen) -> Iterator[LineDiff]:
        height = max(len(self.lines), len(other.lines))
        for row in range(height):
            left = self.lines[row] if row < len(self.lines) else ""
            right = other.lines[row] if row < len(other.lines) else ""
            if left != right:
                yield LineDiff(row=row, left=left, right=right)


def normalise(lines: tuple[str, ...]) -> tuple[str, ...]:
    """Reduce a grid to what a reader would actually see.

    Two adjustments, both because a difference in how a cell is *represented* is not a
    difference in what it renders:

    * Trailing blanks go. Emulators disagree about whether an untouched cell is a space or
      nothing - `pyte` pads every row to full width, `xterm.js` trims.
    * Text is composed to NFC. `pyte` merges a combining mark into the cell it modifies and
      yields the composed character; `xterm.js` hands back the codepoints it was sent. Both
      occupy one column and paint the same glyph, so `e` + U+0301 and `é` are the same
      render and must not be reported as a divergence.
    """
    stripped = [unicodedata.normalize("NFC", line).rstrip() for line in lines]
    while stripped and not stripped[-1]:
        stripped.pop()
    return tuple(stripped)


def replay(data: str, *, columns: int, rows: int) -> RenderedScreen:
    """Interpret a terminal byte stream and return the grid it leaves behind.

    Args:
        data: The stream as written by a `Driver`.
        columns: Grid width the stream was produced for.
        rows: Grid height the stream was produced for.

    Returns:
        The final visible grid.
    """
    screen = pyte.Screen(columns, rows)
    pyte.Stream(screen).feed(data)
    return RenderedScreen(columns=columns, rows=rows, lines=normalise(tuple(screen.display)))
