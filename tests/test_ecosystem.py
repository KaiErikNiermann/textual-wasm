"""The add-on registry and the document rendered from it.

The registry is measured data transcribed into Python, so the failures worth guarding are
transcription failures: a verdict class that never reaches the page, an entry that claims
something it does not evidence, a duplicate row. None of those raise on their own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from textual_wasm.docs import LIBRARIES_PATH, SUPPORT_HEADINGS, render_libraries
from textual_wasm.ecosystem import (
    LIBRARIES,
    SUPPORT_ORDER,
    Library,
    Support,
    by_distribution,
    with_support,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

NEEDS_GUIDANCE: Final[frozenset[Support]] = frozenset(
    {Support.TEXTUAL_CAP, Support.BLOCKED, Support.NOT_ON_PYPI, Support.OUT_OF_SCOPE}
)
"""Verdicts where the reader's next question is "so what do I do" and the row must answer it.

`VERIFIED` and `IMPORTS` are exempt: for those the answer is "use it", and inventing a
sentence to fill the column would be padding rather than guidance.
"""


def test_the_committed_table_matches_the_registry() -> None:
    """Same contract as the porting matrix: the page is a rendering, not a parallel document."""
    committed = (PROJECT_ROOT / LIBRARIES_PATH).read_text(encoding="utf-8")
    assert committed == render_libraries(), (
        f"{LIBRARIES_PATH} is out of date; run `textual-wasm libraries -o {LIBRARIES_PATH}`"
    )


def test_every_verdict_class_has_an_order_and_a_heading() -> None:
    """A `Support` value missing from either silently drops its whole section.

    The renderer iterates `SUPPORT_ORDER` and looks each value up in `SUPPORT_HEADINGS`, so
    adding a seventh verdict without touching both would lose every library in it - and the
    page would still render, still look complete, and still pass a spot check.
    """
    assert set(SUPPORT_ORDER) == set(Support)
    assert set(SUPPORT_HEADINGS) == set(Support)


def test_every_library_reaches_the_document() -> None:
    rendered = render_libraries()
    for library in LIBRARIES:
        assert f"`{library.distribution}`" in rendered, f"{library.distribution} was dropped"


def test_distributions_are_unique() -> None:
    """Two rows for one distribution would present as two verdicts about the same thing."""
    names = [library.distribution for library in LIBRARIES]
    assert len(names) == len(set(names)), "duplicate distribution in the registry"


@pytest.mark.parametrize("library", LIBRARIES, ids=lambda item: item.distribution)
def test_every_row_carries_its_evidence(library: Library) -> None:
    """`observed` is the column that makes a verdict checkable rather than asserted."""
    assert library.summary.strip(), f"{library.distribution} has no summary"
    assert library.observed.strip(), f"{library.distribution} has no observed evidence"


@pytest.mark.parametrize("library", LIBRARIES, ids=lambda item: item.distribution)
def test_rows_that_need_an_answer_have_one(library: Library) -> None:
    if library.support in NEEDS_GUIDANCE:
        assert library.guidance.strip(), (
            f"{library.distribution} is {library.support.value} but says nothing about what to do"
        )


@pytest.mark.parametrize("library", LIBRARIES, ids=lambda item: item.distribution)
def test_a_version_is_recorded_for_anything_that_installed(library: Library) -> None:
    """An installed library with no version means the row cannot be re-checked later."""
    if library.support not in {Support.BLOCKED, Support.NOT_ON_PYPI}:
        assert library.version.strip(), f"{library.distribution} installed but records no version"


def test_usable_means_installs_and_imports() -> None:
    """The property the docs count with, kept honest against the enum."""
    for library in LIBRARIES:
        assert library.usable == (library.support in {Support.VERIFIED, Support.IMPORTS})


def test_with_support_orders_by_downloads() -> None:
    """The page's ordering claim - most-used first - is the registry's job, not the reader's."""
    for support in SUPPORT_ORDER:
        counts = [library.downloads for library in with_support(support)]
        assert counts == sorted(counts, reverse=True)


def test_lookup_of_an_unprobed_library_is_an_error() -> None:
    """Not None: the caller asked about a specific library and silence would read as approval."""
    with pytest.raises(KeyError):
        by_distribution("textual-does-not-exist")
    assert by_distribution("textual-autocomplete").support is Support.VERIFIED


def test_a_pipe_in_a_cell_cannot_break_the_table() -> None:
    """Markdown tables are delimited by the character most likely to appear in a version pin."""
    rendered = render_libraries()
    for line in rendered.splitlines():
        if line.startswith("|") and not line.startswith("|--"):
            # Four columns means five delimiters; anything more is an unescaped pipe inside
            # a cell, which shifts every column after it.
            assert line.count("|") - line.count("\\|") == 5, f"broken row: {line[:120]}"
