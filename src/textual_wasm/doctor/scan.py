"""Find, in source, the things that will behave differently under Pyodide.

Two passes, because they catch different classes of problem and only one of them is
adequately served by existing tools.

Import scanning is cheap and has good recall for absent modules. It is also blind to the
class this project cares most about: `os.system`, `time.sleep` and `run_in_executor` all live
in modules that import perfectly well, and the failure is at the call site. So there is a
second pass over call targets, which is the part with no equivalent elsewhere - there is no
ruff plugin and no `pyodide-compat` for it.

Uses the stdlib `ast` rather than `pyodide.code.find_imports`. That function is the obvious
reuse and was the first choice, but it ships in `pyodide-py`, which requires Python 3.14+ -
too high a floor for a library, in exchange for a fifteen-line walk.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from typing import TYPE_CHECKING, Final

from textual_wasm.substitutions import (
    HARMLESS_ZERO_CALLS,
    Substitution,
    for_call,
    for_import,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SOURCE_GLOB: Final[str] = "**/*.py"

ALLOW_PRAGMA: Final[str] = "textual-wasm: allow"
"""Suppression comment, on the offending line or the one above it::

    os.system("git rev-parse")  # textual-wasm: allow os.system - native-only tooling

A doctor with no suppression gets suppressed wholesale, and legitimate native-only code is
normal: a project ships one codebase that runs in two places. A reason is required for the
same reason this repository requires one on every `nosemgrep`.
"""

_ALLOW_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"{re.escape(ALLOW_PRAGMA)}\s+(?P<ids>[\w.,\s-]+?)\s*(?:-\s*(?P<reason>.+))?$"
)


@dataclasses.dataclass(frozen=True, slots=True)
class Finding:
    """One place in the source that a substitution applies to."""

    substitution: Substitution
    path: Path
    line: int
    column: int
    source: str
    """The offending expression, as written, so the report can be read without the file."""

    @property
    def location(self) -> str:
        """`file:line` - clickable in most terminals and editors."""
        return f"{self.path}:{self.line}"


def _dotted_name(node: ast.expr) -> str | None:
    """Render an attribute chain as it was written, or None if it is not a plain name.

    `os.system` yields "os.system"; `get_module().system` yields None, because a rule cannot
    honestly claim to know what that call resolves to.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return None if prefix is None else f"{prefix}.{node.attr}"
    return None


def _imported_modules(tree: ast.AST) -> Iterator[tuple[str, ast.stmt]]:
    """Every module named by an import, paired with the statement that named it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            # `from os import system` names both the module and, in effect, the call target;
            # the call pass catches the second half when the bare name is used.
            yield node.module, node


def _is_harmless_zero_call(dotted: str, node: ast.Call) -> bool:
    """Whether this is the zero-valued form the runtime guard also lets through.

    Mirrors `guards._guard_time_sleep`, which compares the value rather than the literal.
    `tests/test_doctor.py` asserts the two still agree.

    Written as plain control flow rather than a `match` with a class pattern: semgrep's
    Python parser cannot read that construct and silently skips the whole file, which the
    rule selftest correctly reported as a scan error. Losing gate coverage of a file to a
    stylistic preference is a bad trade.
    """
    if dotted.rsplit(".", 1)[-1] not in {c.rsplit(".", 1)[-1] for c in HARMLESS_ZERO_CALLS}:
        return False
    if len(node.args) != 1:
        return False
    argument = node.args[0]
    if not isinstance(argument, ast.Constant):
        return False
    value = argument.value
    # `bool` is an `int`, and `time.sleep(False)` is not the yield idiom - it is a mistake,
    # and one worth reporting rather than quietly exempting.
    return isinstance(value, int | float) and not isinstance(value, bool) and value == 0


def _bound_names(tree: ast.AST) -> dict[str, frozenset[str]]:
    """Names bound by `from MODULE import NAME`, mapped to the modules that bound them.

    Without this a bare call can only be matched by guessing, and guessing meant treating
    every `open(...)` as `webbrowser.open`. `from os import system as run` binds "run" to
    "os", so the alias is what the call site will actually say.
    """
    bound: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bound.setdefault(alias.asname or alias.name, set()).add(node.module)
    return {name: frozenset(modules) for name, modules in bound.items()}


def _called_names(tree: ast.AST) -> Iterator[tuple[str, ast.expr]]:
    """Every call target that can be written as a dotted name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (dotted := _dotted_name(node.func)):
            if _is_harmless_zero_call(dotted, node):
                continue
            yield dotted, node


def scan_source(source: str, path: Path) -> tuple[Finding, ...]:
    """Find every substitution that applies to one file's source.

    Args:
        source: The file's text.
        path: Where it came from, for the report.

    Returns:
        Findings in source order.

    Raises:
        SyntaxError: If the source does not parse. Left to the caller: a file that cannot be
            parsed is a fact worth reporting, not one to swallow.
    """
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()

    def allowed(substitution_id: str, lineno: int) -> bool:
        """Whether a pragma on this line, or the one above, exempts this substitution."""
        for row in (lineno - 1, lineno - 2):
            if not 0 <= row < len(lines):
                continue
            match = _ALLOW_PATTERN.search(lines[row])
            if match and not match.group("reason"):
                continue
            if match and substitution_id in {
                item.strip() for item in match.group("ids").split(",")
            }:
                return True
        return False

    def build(substitution: Substitution, node: ast.stmt | ast.expr) -> Finding:
        row = node.lineno - 1
        return Finding(
            substitution=substitution,
            path=path,
            line=node.lineno,
            column=node.col_offset,
            source=lines[row].strip() if 0 <= row < len(lines) else "",
        )

    findings = [
        build(substitution, node)
        for module, node in _imported_modules(tree)
        for substitution in for_import(module)
        if not allowed(substitution.id, node.lineno)
    ]
    bound = _bound_names(tree)
    findings += [
        build(substitution, node)
        for dotted, node in _called_names(tree)
        for substitution in for_call(dotted, bound_from=bound.get(dotted, frozenset()))
        if not allowed(substitution.id, node.lineno)
    ]
    # Deduplicated because one line can match twice - `import threading` plus
    # `threading.Thread(...)` is the same advice reported at two sites, and repeating it
    # trains people to skim.
    unique = {(f.substitution.id, f.line, f.column): f for f in findings}
    return tuple(sorted(unique.values(), key=lambda f: (f.line, f.column, f.substitution.id)))


def scan_path(root: Path) -> tuple[Finding, ...]:
    """Scan a file, or every `.py` file under a directory.

    Raises:
        FileNotFoundError: If `root` does not exist.
    """
    if not root.exists():
        raise FileNotFoundError(root)
    paths = [root] if root.is_file() else sorted(root.glob(SOURCE_GLOB))
    return tuple(
        finding for path in paths for finding in scan_source(path.read_text(encoding="utf-8"), path)
    )
