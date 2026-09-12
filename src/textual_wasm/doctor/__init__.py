"""Tell someone what will break before they find out in a browser.

The porting matrix as a command rather than a table nobody reads. Two halves, because they
answer different questions: :mod:`~textual_wasm.doctor.scan` reads the application's source
for behaviour that differs under Pyodide, and :mod:`~textual_wasm.doctor.deps` decides whether
its dependencies can be installed there at all.

Both render the same registry the runtime diagnostics raise from, so the advice a developer
gets before running is the advice they get while running.

A third question sits between them and is answered by :mod:`~textual_wasm.doctor.closure`:
whether the requirements can coexist *with each other*. Pyodide will install a library that
caps Textual below the version the build pins - by resolving Textual down to suit it, and
saying nothing.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from textual_wasm.doctor import closure as closure_module
from textual_wasm.doctor.closure import ClosureConflict, ClosureReport
from textual_wasm.doctor.deps import (
    DEFAULT_LOCKFILE,
    Catalogue,
    Dependency,
    DependencyState,
    load_catalogue,
)
from textual_wasm.doctor.scan import Finding, scan_path
from textual_wasm.substitutions import Severity

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

BLOCKING: frozenset[Severity] = frozenset(
    {Severity.SILENT_WRONG, Severity.FATAL, Severity.UNSUPPORTED}
)
"""Severities that make an app wrong rather than merely different.

`LOUD_UNCLEAR` and `LOUD_CLEAR` are excluded on purpose: they raise, so the app fails
honestly and the developer finds out. What blocks is the code that keeps running while doing
the wrong thing, and the code that cannot run at all.
"""


@dataclasses.dataclass(frozen=True, slots=True)
class DoctorReport:
    """Everything the doctor found."""

    findings: tuple[Finding, ...]
    dependencies: tuple[Dependency, ...]
    closure: ClosureReport = dataclasses.field(default_factory=ClosureReport)
    """What the requirements say about each other, as opposed to about Pyodide.

    Its own field rather than more `dependencies`, because it is a different question with a
    different answer: a cap conflict is between two things the developer chose, and neither
    of them is individually wrong.
    """

    @property
    def blocking_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.substitution.severity in BLOCKING)

    @property
    def blocking_dependencies(self) -> tuple[Dependency, ...]:
        return tuple(d for d in self.dependencies if d.blocks)

    @property
    def pinned_dependencies(self) -> tuple[Dependency, ...]:
        """Dependencies that work, at a version the app does not get to choose."""
        return tuple(d for d in self.dependencies if d.state is DependencyState.BUNDLED_NATIVE)

    @property
    def ok(self) -> bool:
        return not self.blocking_findings and not self.blocking_dependencies and self.closure.ok


def run(
    source: Path,
    *,
    requirements: Sequence[str] = (),
    catalogue: Catalogue | None = None,
) -> DoctorReport:
    """Examine an application for WASM portability.

    Args:
        source: A file or directory of application source.
        requirements: Distribution names to classify. Empty skips the dependency half, which
            is the right default for a source-only check.
        catalogue: Pyodide's package set, or None to read the vendored runtime's lock file.

    Returns:
        The findings, sorted most severe first so a truncated report shows the worst.
    """
    findings = scan_path(source)
    resolved = catalogue
    if requirements and resolved is None:
        resolved = load_catalogue()
    dependencies = tuple(resolved.classify(name) for name in requirements) if resolved else ()
    order = list(Severity)
    return DoctorReport(
        findings=tuple(
            sorted(findings, key=lambda f: (order.index(f.substitution.severity), f.line))
        ),
        dependencies=dependencies,
        closure=closure_module.check(requirements) if requirements else ClosureReport(),
    )


__all__ = [
    "BLOCKING",
    "DEFAULT_LOCKFILE",
    "Catalogue",
    "ClosureConflict",
    "ClosureReport",
    "Dependency",
    "DependencyState",
    "DoctorReport",
    "Finding",
    "load_catalogue",
    "run",
    "scan_path",
]
