"""Make Textual's syntax highlighting work on the tree-sitter Pyodide actually ships.

`TextArea` is not optional furniture - it is how a Textual application edits text - and on
Pyodide its highlighting is unavailable for a reason that has nothing to do with WebAssembly.
Measured rather than inferred:

* Textual's `syntax` extra requires `tree-sitter>=0.25.0`. That floor is a hard API
  requirement, not caution: `textual/document/_syntax_aware_document.py` imports
  `QueryCursor`, a class 0.25 introduced when it split query *execution* out of `Query`.
* Pyodide bundles tree-sitter 0.23.2, whose `Query` still carries `captures` and `matches`
  itself. Its recipe was written on 2025-04-22 at what was then the current version and has
  not been touched since; it builds from an unpatched sdist, so the pin is staleness rather
  than a porting problem.
* None of the sixteen tree-sitter distributions publishes a wasm wheel to PyPI, so micropip
  cannot route around Pyodide's copy.

The whole gap is therefore one class. `QueryCursor(query).captures(node)` in 0.25 is
`query.captures(node)` in 0.23, and this module supplies the former in terms of the latter.

What that buys, measured in Chromium and Firefox: `TextArea.code_editor(..., language=...)`
goes from raising to producing a real `SyntaxAwareDocument` with highlighting, for every
grammar Pyodide bundles - `python`, `go` and `java`. The other twelve languages in Textual's
extra have no Pyodide recipe at all, so they remain unavailable and this changes nothing
about them.

The shim is not a fix for the underlying problem, and it is deliberately easy to remove: it
applies only when `QueryCursor` is genuinely absent, so a Pyodide that bundles 0.25 or newer
turns it off by itself and the real API is used.

:::{admonition} Why this is a shim and not a patch of Textual
Nothing here touches Textual. The missing name is added to `tree_sitter`, which is the
library that actually lost it, before anything imports the Textual module that looks for it -
`textual.document._syntax_aware_document` decides at *import* time whether tree-sitter is
usable and caches that in a module-level flag.
:::
"""

from __future__ import annotations

import dataclasses
import enum
import logging
from typing import Any, Final

_log: Final = logging.getLogger(__name__)

REQUIRED_BY_TEXTUAL: Final[str] = "0.25.0"
"""The floor Textual's `syntax` extra declares, and the version that introduced
`QueryCursor`."""

SHIMMABLE_FROM: Final[str] = "0.23.0"
"""The oldest tree-sitter whose `Query` carries `captures` and `matches` directly.

Below this the methods were on a different object again, and the shim would produce a
`QueryCursor` that does not work - which is worse than not having one, because Textual would
then believe highlighting is available.
"""


class ShimOutcome(enum.StrEnum):
    """What `install()` did, and why."""

    APPLIED = "applied"
    """`QueryCursor` was missing and has been supplied."""

    NOT_NEEDED = "not_needed"
    """tree-sitter already has `QueryCursor`; the real implementation is in use."""

    NO_TREE_SITTER = "no_tree_sitter"
    """tree-sitter is not installed at all, so there is nothing to highlight with."""

    TOO_OLD = "too_old"
    """tree-sitter is old enough that `Query` does not carry the methods either.

    Refused rather than applied: a shim that cannot work would make Textual believe
    highlighting is available and fail later, further from the cause.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class ShimReport:
    """What happened, for `capabilities` and the doctor to report rather than guess."""

    outcome: ShimOutcome
    version: str | None = None
    """The tree-sitter version found, or None if it is not installed."""

    @property
    def highlighting_available(self) -> bool:
        return self.outcome in {ShimOutcome.APPLIED, ShimOutcome.NOT_NEEDED}

    @property
    def summary(self) -> str:
        match self.outcome:
            case ShimOutcome.APPLIED:
                return (
                    f"tree-sitter {self.version} is older than the {REQUIRED_BY_TEXTUAL} "
                    "Textual asks for; QueryCursor has been supplied so highlighting works "
                    "for the grammars Pyodide bundles (python, go, java)"
                )
            case ShimOutcome.NOT_NEEDED:
                return f"tree-sitter {self.version} has QueryCursor; no shim applied"
            case ShimOutcome.NO_TREE_SITTER:
                return "tree-sitter is not installed; TextArea works without highlighting"
            case ShimOutcome.TOO_OLD:
                return (
                    f"tree-sitter {self.version} is older than {SHIMMABLE_FROM}, whose Query "
                    "carries the methods the shim needs; highlighting left unavailable"
                )


class _QueryCursor:
    """`tree_sitter.QueryCursor` from 0.25, expressed in the 0.23 API.

    0.25 moved execution off `Query` and onto a cursor so that one compiled query can be run
    with different limits. Nothing in Textual uses those limits - it constructs a cursor,
    calls `captures` once, and discards it - so holding the query and forwarding is the whole
    of it. The optional keyword arguments are accepted and ignored rather than rejected,
    because rejecting them would turn a feature Textual does not use into a crash if it ever
    did.
    """

    __slots__ = ("_query",)

    def __init__(self, query: Any, **_: Any) -> None:
        self._query = query

    def captures(self, node: Any, **kwargs: Any) -> Any:
        return self._query.captures(node, **kwargs)

    def matches(self, node: Any, **kwargs: Any) -> Any:
        return self._query.matches(node, **kwargs)

    def set_max_start_depth(self, depth: int) -> _QueryCursor:
        """Accepted and ignored: 0.23 has no equivalent, and no caller here sets it."""
        return self

    def set_byte_range(self, byte_range: Any) -> _QueryCursor:
        return self

    def set_point_range(self, point_range: Any) -> _QueryCursor:
        return self


def _tree_sitter() -> Any | None:
    """The tree-sitter module, or None when it is not installed.

    Optional by nature: present inside Pyodide, and natively only for someone who installed
    `textual[syntax]`. Absent in this project's own environment, which is why the missing
    import is ignored rather than stubbed - a stub would claim an API this module exists
    precisely because the real one varies.
    """
    try:
        import tree_sitter  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
    except ImportError:
        return None
    return tree_sitter


def _classify(module: Any) -> ShimOutcome:
    """Decide what this tree-sitter needs, without changing it."""
    if hasattr(module, "QueryCursor"):
        return ShimOutcome.NOT_NEEDED
    query = getattr(module, "Query", None)
    usable = query is not None and all(hasattr(query, name) for name in ("captures", "matches"))
    return ShimOutcome.APPLIED if usable else ShimOutcome.TOO_OLD


def install() -> ShimReport:
    """Supply `tree_sitter.QueryCursor` if this tree-sitter is too old to have it.

    Must run before anything imports `textual.document._syntax_aware_document`, which decides
    at import time whether tree-sitter is usable and caches the answer in a module-level
    flag. `textual_wasm.bootstrap` calls it for that reason, in the same place it sets the
    Textual environment.

    Returns:
        What was done, so the runtime can report it rather than leaving a developer to
        wonder why highlighting works in a browser and not on their machine, or the reverse.
    """
    module = _tree_sitter()
    if module is None:
        return ShimReport(ShimOutcome.NO_TREE_SITTER)

    version = str(getattr(module, "__version__", "") or _installed_version())
    outcome = _classify(module)
    if outcome is ShimOutcome.APPLIED:
        module.QueryCursor = _QueryCursor
        _log.info("supplied tree_sitter.QueryCursor for tree-sitter %s", version or "(unknown)")
    return ShimReport(outcome, version or None)


def _installed_version() -> str:
    """tree-sitter 0.23 exposes no `__version__`, so fall back to its metadata."""
    import importlib.metadata  # noqa: PLC0415

    try:
        return importlib.metadata.version("tree-sitter")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - installed by then
        return ""
