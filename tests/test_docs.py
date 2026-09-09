"""The porting matrix must be a rendering of the registry, never a parallel document."""

from __future__ import annotations

from pathlib import Path

from textual_wasm.docs import MATRIX_PATH, render_matrix
from textual_wasm.substitutions import SUBSTITUTIONS

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_the_committed_matrix_matches_the_registry() -> None:
    """The failure this prevents is the whole reason the matrix is generated.

    A hand-maintained porting table goes wrong silently: nothing fails when the runtime
    changes, and the reader has no way to tell a measured claim from a stale one.
    """
    committed = (PROJECT_ROOT / MATRIX_PATH).read_text(encoding="utf-8")
    assert committed == render_matrix(), (
        f"{MATRIX_PATH} is out of date; run `textual-wasm matrix -o {MATRIX_PATH}`"
    )


def test_every_substitution_reaches_the_document() -> None:
    """A severity class with no section would drop entries without failing anything."""
    rendered = render_matrix()
    for substitution in SUBSTITUTIONS:
        assert f"`{substitution.id}`" in rendered


def test_a_pipe_in_guidance_cannot_break_the_table() -> None:
    """Markdown tables are column-delimited by the character most likely to appear in code."""
    assert "\\|" in render_matrix() or all(
        "|" not in s.guidance and "|" not in s.observed for s in SUBSTITUTIONS
    )
