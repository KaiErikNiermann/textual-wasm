"""Check a set of requirements against each other, not only against Pyodide.

:mod:`~textual_wasm.doctor.deps` answers "can Pyodide install this one distribution". That
question is necessary and not sufficient, because the failure it cannot see is between two
requirements that are each individually fine.

The case that motivated this is the largest single category in the add-on survey. Five
libraries - `textual-slidecontainer`, `textual-coloromatic`, `textual-pyfiglet`,
`textual-window`, `textual-spinbox` - cap Textual below the version this project pins.
Each classifies as `PURE` and installs cleanly on its own, because `micropip` satisfies the
cap by quietly resolving Textual *down*. Nothing raises. The developer finds out later, as a
widget that no longer exists or an import that moved, in a browser.

So the check here is: expand each requirement one level using its declared metadata, and
test those declared requirements against the versions the closure pins. One level, not the
whole graph, and deliberately:

* it is offline and exact for anything installed, which is the case that matters - you are
  developing against these libraries, so they are on your machine;
* it needs no resolver, and a wrong resolver is worse than none;
* the conflicts it does find are certain rather than probable, because they compare a
  declared specifier against a pin already written down.

A distribution that is not installed locally cannot be expanded, and that is reported rather
than passed over - the whole point of the module is to stop treating "nothing was checked"
as "nothing is wrong".
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
from typing import TYPE_CHECKING, Final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from textual_wasm.doctor.deps import applies_under_emscripten, normalise

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

PYODIDE_PYTHON: Final[str] = "3.14.2"
"""Only used to evaluate environment markers when no catalogue is supplied."""


@dataclasses.dataclass(frozen=True, slots=True)
class ClosureConflict:
    """One requirement the closure pins at a version something else in it forbids."""

    dependent: str
    """The distribution whose metadata declared the incompatible requirement."""

    dependency: str
    """The distribution they disagree about."""

    declared: str
    """What `dependent` asks for, verbatim, e.g. `textual>=3.0.0,<6.0.0`."""

    pinned: str
    """The version the closure actually installs."""

    @property
    def guidance(self) -> str:
        return (
            f"{self.dependent} requires {self.declared}, but the build installs "
            f"{self.dependency}=={self.pinned}. Installing {self.dependent} on its own appears "
            f"to work because micropip resolves {self.dependency} *down* to satisfy it - which "
            "silently changes the version your application runs against. Pin "
            f"{self.dependency} to a version both accept, or drop {self.dependent}"
        )


@dataclasses.dataclass(frozen=True, slots=True)
class ClosureReport:
    """What checking the requirements against each other found."""

    conflicts: tuple[ClosureConflict, ...] = ()
    unexpanded: tuple[str, ...] = ()
    """Distributions whose metadata is not installed here, so nothing could be expanded.

    Named rather than counted, because the right response is to install one and re-run, and
    that needs to know which.
    """

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _pins(requirements: Sequence[str]) -> dict[str, Version]:
    """Exact versions the closure fixes, by normalised name.

    Only `==` counts. A range is not a pin: `textual>=8` and `textual<6` are a conflict the
    resolver will report on its own terms, whereas a pin is a fact that something else can
    be checked against with certainty.
    """
    pinned: dict[str, Version] = {}
    for raw in requirements:
        try:
            parsed = Requirement(raw)
        except InvalidRequirement:
            continue
        exact = [
            specifier.version
            for specifier in parsed.specifier
            if specifier.operator in {"==", "==="}
        ]
        if len(exact) != 1:
            continue
        try:
            pinned[normalise(parsed.name)] = Version(exact[0])
        except InvalidVersion:
            continue
    return pinned


def installed_requirements(distribution: str) -> tuple[str, ...] | None:
    """What `distribution` says it needs, or None if it is not installed here."""
    try:
        return tuple(importlib.metadata.requires(distribution) or ())
    except importlib.metadata.PackageNotFoundError:
        return None


def check(
    requirements: Sequence[str],
    *,
    python_version: str = PYODIDE_PYTHON,
    declared: Callable[[str], tuple[str, ...] | None] = installed_requirements,
) -> ClosureReport:
    """Find requirements in `requirements` that contradict each other.

    Args:
        requirements: The resolved closure, as PEP 508 strings.
        python_version: Interpreter version for marker evaluation.
        declared: How to find what a distribution requires. Injectable so a test can state
            the metadata it is reasoning about rather than depending on what happens to be
            installed in the environment running it.

    Returns:
        The conflicts, and the distributions that could not be expanded because their
        metadata is not installed locally.
    """
    pinned = _pins(requirements)
    conflicts: list[ClosureConflict] = []
    unexpanded: list[str] = []

    for raw in requirements:
        try:
            parsed = Requirement(raw)
        except InvalidRequirement:
            continue
        requires = declared(parsed.name)
        if requires is None:
            unexpanded.append(parsed.name)
            continue
        conflicts += _conflicts_for(parsed.name, requires, pinned, python_version)

    return ClosureReport(conflicts=tuple(conflicts), unexpanded=tuple(dict.fromkeys(unexpanded)))


def _conflicts_for(
    dependent: str,
    declared: Sequence[str],
    pinned: dict[str, Version],
    python_version: str,
) -> list[ClosureConflict]:
    """Every declared requirement of `dependent` that the closure's pins contradict."""
    found: list[ClosureConflict] = []
    for raw in declared:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            continue
        # An extra nobody asked for, or a marker false under Emscripten, is not installed -
        # so its specifier cannot conflict with anything.
        if not applies_under_emscripten(requirement, python_version):
            continue
        version = pinned.get(normalise(requirement.name))
        if version is None or not str(requirement.specifier):
            continue
        if not requirement.specifier.contains(version, prereleases=True):
            found.append(
                ClosureConflict(
                    dependent=dependent,
                    dependency=requirement.name,
                    declared=raw,
                    pinned=str(version),
                )
            )
    return found
