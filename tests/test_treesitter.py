"""The tree-sitter shim that makes Textual's syntax highlighting usable under Pyodide.

tree-sitter is not installed in this project's environment - it is optional, and present
only inside Pyodide or for someone who installed `textual[syntax]`. So the versions are
stubbed: each test states the tree-sitter it is reasoning about, which is both deterministic
and the only way to exercise the branches that depend on a version nobody here has.

That the shim actually works is not asserted here and cannot be. It was measured by building
an ordinary `TextArea.code_editor(language="python")` application and driving it in Chromium
and Firefox: 14 and 13 distinct foreground colours painted in the terminal, the source
rendered, typing still reparsing, no console errors.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from textual_wasm import treesitter
from textual_wasm.treesitter import ShimOutcome


def _fake_tree_sitter(*, query_cursor: bool, query_methods: bool, version: str) -> types.ModuleType:
    """A stand-in for whichever tree-sitter a runtime happens to have."""
    module = types.ModuleType("tree_sitter")
    module.__version__ = version  # type: ignore[attr-defined]

    class Query:
        def captures(self, node: Any, **kwargs: Any) -> dict[str, list[Any]]:
            return {"captured": [node, kwargs]}

        def matches(self, node: Any, **kwargs: Any) -> list[Any]:
            return [node, kwargs]

    if not query_methods:
        del Query.captures
        del Query.matches

    module.Query = Query  # type: ignore[attr-defined]
    if query_cursor:
        module.QueryCursor = object  # type: ignore[attr-defined]
    return module


@pytest.fixture
def install_fake(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201 - a fixture factory
    """Put a stubbed tree-sitter on `sys.modules` for the duration of one test."""

    def place(**kwargs: Any) -> types.ModuleType:
        module = _fake_tree_sitter(**kwargs)
        monkeypatch.setitem(sys.modules, "tree_sitter", module)
        return module

    return place


def test_no_tree_sitter_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary case on a terminal, where highlighting is simply not installed."""
    monkeypatch.setitem(sys.modules, "tree_sitter", None)
    report = treesitter.install()
    assert report.outcome is ShimOutcome.NO_TREE_SITTER
    assert not report.highlighting_available
    assert "without highlighting" in report.summary


def test_a_current_tree_sitter_is_left_alone(install_fake: Any) -> None:
    """The shim must disappear on its own once Pyodide bundles 0.25 or newer.

    This is what makes it a workaround rather than a fork: nothing has to be removed by hand
    when the underlying problem is fixed.
    """
    module = install_fake(query_cursor=True, query_methods=True, version="0.25.2")
    report = treesitter.install()
    assert report.outcome is ShimOutcome.NOT_NEEDED
    assert report.highlighting_available
    assert module.QueryCursor is object, "the real QueryCursor was replaced"


def test_the_version_pyodide_bundles_gets_the_shim(install_fake: Any) -> None:
    """0.23.2 is what Pyodide 314.0.6 ships, and the only reason highlighting is unavailable."""
    module = install_fake(query_cursor=False, query_methods=True, version="0.23.2")
    report = treesitter.install()
    assert report.outcome is ShimOutcome.APPLIED
    assert report.highlighting_available
    assert report.version == "0.23.2"
    assert hasattr(module, "QueryCursor")


def test_a_tree_sitter_too_old_to_shim_is_refused(install_fake: Any) -> None:
    """Refusing is the point: a QueryCursor that cannot work would make Textual believe
    highlighting is available and fail further from the cause."""
    module = install_fake(query_cursor=False, query_methods=False, version="0.20.0")
    report = treesitter.install()
    assert report.outcome is ShimOutcome.TOO_OLD
    assert not report.highlighting_available
    assert not hasattr(module, "QueryCursor")


def test_the_shim_forwards_to_the_old_api(install_fake: Any) -> None:
    """`QueryCursor(query).captures(node)` in 0.25 is `query.captures(node)` in 0.23."""
    module = install_fake(query_cursor=False, query_methods=True, version="0.23.2")
    treesitter.install()
    query = module.Query()
    cursor = module.QueryCursor(query)
    assert cursor.captures("node") == {"captured": ["node", {}]}
    assert cursor.matches("node") == ["node", {}]


def test_the_range_setters_are_accepted_and_chainable(install_fake: Any) -> None:
    """Textual does not use them, but rejecting them would turn an unused feature into a
    crash the day something does."""
    module = install_fake(query_cursor=False, query_methods=True, version="0.23.2")
    treesitter.install()
    cursor = module.QueryCursor(module.Query())
    assert cursor.set_max_start_depth(3) is cursor
    assert cursor.set_byte_range((0, 10)) is cursor
    assert cursor.set_point_range(((0, 0), (1, 0))) is cursor


def test_every_outcome_has_a_summary() -> None:
    """The summary is what `capabilities` reports, so an outcome without one is invisible."""
    for outcome in ShimOutcome:
        report = treesitter.ShimReport(outcome, "0.23.2")
        assert report.summary.strip(), outcome


def test_the_package_import_applies_it_and_records_the_result() -> None:
    """The ordering is the whole point, and a package import is the only place that can
    guarantee it: `textual.document._syntax_aware_document` caches the answer at import."""
    import textual_wasm  # noqa: PLC0415

    assert isinstance(textual_wasm.TREE_SITTER_SHIM, treesitter.ShimReport)


def test_capabilities_reports_it() -> None:
    """Whether highlighting works differs between a laptop and a browser for a reason
    neither shows; unreported, it is invisible until someone reads a rendered screen."""
    from textual_wasm.capabilities import detect  # noqa: PLC0415

    assert detect().syntax_highlighting.strip()
