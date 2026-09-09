"""Classify an application's dependencies by whether Pyodide can install them.

Four outcomes, and only one of them blocks. The interesting one is `BUNDLED_NATIVE`: a
package Pyodide compiled itself is available, but at *Pyodide's* version and no other, which
is a constraint people discover late. `cryptography` is three majors behind PyPI and `polars`
eleven minors, so "it works" and "it works at the version you pinned" are different answers.

Reads Pyodide's own lock file through `pyodide-lock` rather than parsing the JSON here - it
is a maintained, typed model of a format this project does not own.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib.metadata
import json
from pathlib import Path
from typing import Final

DEFAULT_LOCKFILE: Final[Path] = Path("node_modules/pyodide/pyodide-lock.json")
"""Where the vendored runtime keeps its lock file, relative to a project root."""

PURE_WHEEL_TAG: Final[str] = "-py3-none-any.whl"
"""Marks a wheel micropip can fetch from PyPI at any version."""

WASM_WHEEL_TAG: Final[str] = "wasm32.whl"
"""Marks a `pyemscripten` wheel - new in Pyodide 314, and the reason "C extensions are
impossible" is no longer true. Such a wheel can be published to PyPI and micropip installs it
without Pyodide having bundled anything."""


class DependencyState(enum.StrEnum):
    """Whether, and on what terms, a distribution is usable under Pyodide."""

    PURE = "pure"
    """Pure Python. micropip fetches any version from PyPI."""

    BUNDLED_NATIVE = "bundled_native"
    """Compiled by Pyodide. Available, but pinned to the runtime's version."""

    WASM_WHEEL = "wasm_wheel"
    """Published as a `pyemscripten` wheel. Installable without a Pyodide build."""

    UNAVAILABLE = "unavailable"
    """Has a compiled extension and nobody has built it for wasm. The blocking case."""

    UNKNOWN = "unknown"
    """Not in the lock file and not installed locally, so there is nothing to inspect.

    Reported as its own state rather than optimistically as `PURE`. Guessing "probably fine"
    about the one category that blocks is how a doctor loses the right to be trusted.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class Dependency:
    """One distribution and what Pyodide can do with it."""

    name: str
    state: DependencyState
    pyodide_version: str | None = None
    """The version Pyodide pins, when it bundles one."""

    @property
    def blocks(self) -> bool:
        return self.state is DependencyState.UNAVAILABLE

    @property
    def guidance(self) -> str:
        """What the developer should do about it."""
        match self.state:
            case DependencyState.PURE:
                return "pure Python; micropip installs any version"
            case DependencyState.WASM_WHEEL:
                return "publishes a pyemscripten wasm wheel; micropip installs it"
            case DependencyState.BUNDLED_NATIVE:
                return (
                    f"bundled by Pyodide at {self.pyodide_version}; you cannot choose a "
                    "different version"
                )
            case DependencyState.UNAVAILABLE:
                return (
                    "has a compiled extension and no wasm build. Replace it, or stub the "
                    "import with micropip.add_mock_package() if it is only needed natively"
                )
            case DependencyState.UNKNOWN:
                return (
                    "not bundled and not installed here, so its wheels could not be "
                    "inspected. Install it, or check PyPI for a py3-none-any wheel"
                )


@dataclasses.dataclass(frozen=True, slots=True)
class Catalogue:
    """Pyodide's package set, as the doctor needs to query it."""

    version: str
    packages: dict[str, Dependency]

    def classify(self, name: str) -> Dependency:
        """Classify one distribution by name.

        Pyodide's lock file first, since it is authoritative for anything Pyodide built.
        Otherwise the locally installed distribution is inspected for compiled extensions,
        which is both offline and exact for the dependencies an app actually has. Anything
        neither bundled nor installed is `UNKNOWN`, not assumed fine.
        """
        normalised = _normalise(name)
        bundled = self.packages.get(normalised)
        return bundled if bundled is not None else _classify_installed(normalised)


COMPILED_SUFFIXES: Final[tuple[str, ...]] = (".so", ".pyd", ".dylib")
"""Extension-module suffixes. A distribution shipping one is not pure Python, so micropip
cannot install it from PyPI however new the version is."""


def _classify_installed(name: str) -> Dependency:
    """Inspect a locally installed distribution for compiled extensions."""
    try:
        files = importlib.metadata.files(name)
    except importlib.metadata.PackageNotFoundError:
        return Dependency(name, DependencyState.UNKNOWN)
    if files is None:
        return Dependency(name, DependencyState.UNKNOWN)
    compiled = any(str(item).endswith(COMPILED_SUFFIXES) for item in files)
    state = DependencyState.UNAVAILABLE if compiled else DependencyState.PURE
    return Dependency(name, state)


def _normalise(name: str) -> str:
    """PEP 503 name normalisation, so `typing_extensions` and `typing-extensions` agree."""
    return name.lower().replace("_", "-")


def _state_for(file_name: str) -> DependencyState:
    if file_name.endswith(PURE_WHEEL_TAG):
        return DependencyState.PURE
    if file_name.endswith(WASM_WHEEL_TAG):
        return DependencyState.BUNDLED_NATIVE
    return DependencyState.UNAVAILABLE


def load_catalogue(lockfile: Path | None = None) -> Catalogue:
    """Read Pyodide's lock file.

    Args:
        lockfile: Path to `pyodide-lock.json`, or None for the vendored runtime's.

    Raises:
        FileNotFoundError: If the lock file is missing, which means the runtime has not been
            installed and the doctor cannot answer dependency questions at all.
    """
    path = lockfile or DEFAULT_LOCKFILE
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found; install the Pyodide runtime before asking about dependencies"
        )
    # pyodide-lock's model is the right reader, but it validates strictly against the schema
    # version it was built for, and this project deliberately tracks a newer runtime than the
    # released model. Reading the two fields the doctor needs is the honest middle: still no
    # hand-rolled schema, and no failure when the runtime moves ahead of the library.
    document = json.loads(path.read_text(encoding="utf-8"))
    info = document.get("info", {})
    packages: dict[str, Dependency] = {}
    for entry in document.get("packages", {}).values():
        name = _normalise(str(entry["name"]))
        packages[name] = Dependency(
            name=name,
            state=_state_for(str(entry["file_name"])),
            pyodide_version=str(entry["version"]),
        )
    return Catalogue(version=str(info.get("python", "unknown")), packages=packages)
