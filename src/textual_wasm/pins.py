"""The dependency set the WASM runtime must install, derived from the native environment.

The experiment compares two runtimes; it is only valid if both load the same code. micropip
resolves against Pyodide's own bundled package set before PyPI, so an unpinned install
silently produced a much older `rich` than the native environment had - and that older `rich`
imports `getpass`, hence `termios`, which failed an import-purity check for a reason
unrelated to either Textual or WASM.

So the pins are *generated* from what is actually installed natively, and written to a
committed file. Both the set and the versions: an earlier version of this module generated
the versions but kept the list of distributions by hand, and that hand-written list was
missing `markdown-it-py[linkify]`. Nothing failed until Textual's own `Markdown` widget ran
in a browser and died with "Linkify enabled but not installed" - three layers away from the
list that was wrong. A closure walked from the installed metadata cannot have that gap.
"""

from __future__ import annotations

import importlib.metadata
from typing import TYPE_CHECKING, Final

from packaging.requirements import Requirement

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

ROOT_DISTRIBUTIONS: Final[tuple[str, ...]] = (
    "textual",
    # pyte replays the emitted stream into a grid so the runtimes can be compared on what
    # they render, not only on the bytes they emit. Pure Python, as is its own dependency.
    "pyte",
)
"""What this package needs at runtime *in the browser*. Everything else is walked from here.

Deliberately not `textual-wasm` itself: the CLI's own dependencies - typer, and this
module's `packaging` - run the build, they do not run in the page.
"""

REQUIREMENTS_FILENAME: Final[str] = "wasm-requirements.txt"
"""Committed artifact, so a harness can install the closure without importing this package."""

_NO_EXTRA: Final[frozenset[str]] = frozenset({""})
"""Marker environment for a requirement pulled in without extras.

`extra == "syntax"` has to evaluate False rather than raise, and an absent `extra` key does
the latter.
"""


def _wanted(requirement: Requirement, extras: frozenset[str]) -> bool:
    """Whether `requirement` applies when its dependent was requested with `extras`.

    Markers are evaluated against the *native* interpreter. That is the same environment the
    versions come from, which is the point - but it means a dependency conditional on
    `sys_platform` could differ under Emscripten. micropip re-resolves on install, so the
    consequence is a redundant pin rather than a missing one.
    """
    if requirement.marker is None:
        return True
    return any(requirement.marker.evaluate({"extra": extra}) for extra in extras or _NO_EXTRA)


def _requirements(name: str, extras: frozenset[str]) -> Iterator[tuple[str, frozenset[str]]]:
    """Direct dependencies of one installed distribution, with the extras each was asked for."""
    for raw in importlib.metadata.requires(name) or ():
        requirement = Requirement(raw)
        if _wanted(requirement, extras):
            yield requirement.name, frozenset(requirement.extras)


def closure() -> tuple[str, ...]:
    """Every distribution reachable from the roots, in a stable order.

    Extras are followed, which is the whole reason this is a walk rather than a list:
    `textual` depends on `markdown-it-py[linkify]`, and the `linkify` extra is what pulls in
    `linkify-it-py`. A list of names cannot express that, and its absence surfaces as a
    widget failing at runtime rather than as an install error.

    Returns:
        Distribution names, roots first, then in the order they were discovered.

    Raises:
        importlib.metadata.PackageNotFoundError: If a required distribution is not installed
            natively, which means the native environment cannot define the WASM one.
    """
    requested: dict[str, frozenset[str]] = {}
    pending: list[tuple[str, frozenset[str]]] = [(name, frozenset()) for name in ROOT_DISTRIBUTIONS]
    while pending:
        name, extras = pending.pop(0)
        known = requested.get(name)
        if known is not None and extras <= known:
            continue
        # Re-walk on a *new* extra: the same distribution reached twice with different extras
        # has different dependencies the second time.
        requested[name] = extras if known is None else known | extras
        pending.extend(_requirements(name, requested[name]))
    return tuple(requested)


def resolve_pins() -> tuple[str, ...]:
    """Return `name==version` for the whole closure, as currently installed natively.

    Raises:
        importlib.metadata.PackageNotFoundError: If a distribution in the closure is not
            installed.
    """
    return tuple(f"{name}=={importlib.metadata.version(name)}" for name in closure())


def write_pins(path: Path) -> tuple[str, ...]:
    """Write the resolved pins to `path`, one per line, and return them."""
    pins = resolve_pins()
    header = (
        "# Generated by `textual-wasm pins`. Do not edit by hand.\n"
        "# The closure is walked from the installed metadata, extras included, so that the\n"
        "# two runtimes load identical code.\n"
    )
    path.write_text(header + "\n".join(pins) + "\n", encoding="utf-8")
    return pins
