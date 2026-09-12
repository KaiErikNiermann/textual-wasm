"""Classify an application's dependencies by whether Pyodide can install them.

The interesting outcomes are the two that involve a *version*. `BUNDLED_NATIVE` means a
package Pyodide compiled itself is available, but at Pyodide's version and no other, which is
a constraint people discover late: `cryptography` is three majors behind PyPI and `polars`
eleven minors, so "it works" and "it works at the version you pinned" are different answers.
`VERSION_CONFLICT` is when those two answers have already diverged - the app's own specifier
excludes the version Pyodide has, so the install cannot succeed and nothing about the source
needs reading to know it.

Requirements arrive as PEP 508 strings, not bare names: `textual-wasm pins` writes `==` pins,
`importlib.metadata.requires()` returns specifiers and markers, and a `requirements.txt` has
both. So they are parsed with `packaging` rather than looked up verbatim - a name matched
literally against the lock file misses every one of those forms.

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

from packaging.markers import UndefinedEnvironmentName
from packaging.requirements import InvalidRequirement, Requirement

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

    VERSION_CONFLICT = "version_conflict"
    """Compiled by Pyodide, at a version the application's own specifier excludes.

    Distinct from `UNAVAILABLE` because the fix is different and the error message is
    misleading: micropip reports "can't find a pure Python wheel", which reads as "nobody has
    built this for wasm" when the truth is that it *is* built, one version too old. Blocks,
    because the install fails outright.
    """

    PLATFORM_EXCLUDED = "platform_excluded"
    """Its environment marker is false under Emscripten, so it is never installed.

    A Windows-only or extra-gated requirement is not a portability problem, and reporting it
    as `UNAVAILABLE` would be a false alarm on a dependency list that is entirely fine.
    """

    UNAVAILABLE = "unavailable"
    """Has a compiled extension and nobody has built it for wasm. The blocking case."""

    UNKNOWN = "unknown"
    """Not in the lock file and not installed locally, so there is nothing to inspect.

    Reported as its own state rather than optimistically as `PURE`. Guessing "probably fine"
    about the one category that blocks is how a doctor loses the right to be trusted.
    """


_GUIDANCE: Final[dict[DependencyState, str]] = {
    DependencyState.VERSION_CONFLICT: (
        "you require {name}{specifier} but Pyodide bundles {pyodide_version}, and a native "
        "package cannot be fetched from PyPI. Relax the pin to accept that version, or drop "
        "the dependency"
    ),
    DependencyState.PLATFORM_EXCLUDED: (
        "its environment marker is false under Emscripten; never installed"
    ),
    DependencyState.UNAVAILABLE: (
        "has a compiled extension and no wasm build. Replace it, or stub the import with "
        "micropip.add_mock_package() if it is only needed natively"
    ),
    DependencyState.UNKNOWN: (
        "not bundled and not installed here, so its wheels could not be inspected. Install "
        "it, or check PyPI for a py3-none-any wheel"
    ),
}
"""Guidance for the states whose text needs the requirement interpolated into it."""


BLOCKING_STATES: Final[frozenset[DependencyState]] = frozenset(
    {DependencyState.UNAVAILABLE, DependencyState.VERSION_CONFLICT}
)
"""States that make the install fail, as opposed to merely constraining it."""


@dataclasses.dataclass(frozen=True, slots=True)
class Dependency:
    """One requirement and what Pyodide can do with it."""

    name: str
    state: DependencyState
    pyodide_version: str | None = None
    """The version Pyodide pins, when it bundles one."""

    specifier: str = ""
    """The application's own version constraint, verbatim, or empty if it gave none.

    Kept so the conflict message can quote both sides. A report that says only "wrong
    version" sends the reader back to the requirements file to find out which.
    """

    extras: tuple[str, ...] = ()
    """Extras the requirement asked for, e.g. `syntax` in `textual[syntax]`.

    Recorded because the doctor resolves one level: it cannot see what an extra pulls in
    without the dependency graph, and saying so is better than implying the extra was
    checked. `textual[syntax]` is the live example - it does not install under Pyodide
    314.0.6, and nothing about `textual` itself shows that.
    """

    @property
    def blocks(self) -> bool:
        return self.state in BLOCKING_STATES

    @property
    def guidance(self) -> str:
        """What the developer should do about it."""
        # One return rather than seven: the arms differ only in their text, and a branch per
        # arm reads to the complexity checker as seven exits from a function with one job.
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
            case _:
                return _GUIDANCE[self.state].format(
                    name=self.name,
                    specifier=self.specifier,
                    pyodide_version=self.pyodide_version,
                )


def emscripten_environment(python_version: str) -> dict[str, str]:
    r"""The PEP 508 marker environment a Pyodide install actually evaluates against.

    Args:
        python_version: Full interpreter version from the lock file, e.g. `3.14.2`.

    Returns:
        An environment to pass to `Marker.evaluate`. `extra` is `""` rather than absent
        because an absent one makes `extra == "..."` raise instead of evaluating false, and
        an extra nobody asked for is exactly a requirement that is not installed.
    """
    return {
        "sys_platform": "emscripten",
        "platform_system": "Emscripten",
        "platform_machine": "wasm32",
        "os_name": "posix",
        "python_version": ".".join(python_version.split(".")[:2]),
        "python_full_version": python_version,
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
        "extra": "",
    }


@dataclasses.dataclass(frozen=True, slots=True)
class Catalogue:
    """Pyodide's package set, as the doctor needs to query it."""

    version: str
    packages: dict[str, Dependency]

    def classify(self, requirement: str) -> Dependency:
        """Classify one PEP 508 requirement.

        Its marker is evaluated first: a requirement Emscripten never installs cannot be a
        portability problem, whatever its wheels look like. Then Pyodide's lock file, since
        it is authoritative for anything Pyodide built - and where it names a version, the
        requirement's own specifier is checked against it, because a pin excluding the
        bundled version is a failed install rather than a constrained one. Anything neither
        bundled nor installed locally is `UNKNOWN`, not assumed fine.

        Args:
            requirement: A name, or any PEP 508 string: `pandas`, `pandas<=2.2.3`,
                `textual[syntax]>=7`, `pywin32; sys_platform == "win32"`.

        Returns:
            The classification, carrying whichever of the version and specifier apply.
        """
        try:
            parsed = Requirement(requirement)
        except InvalidRequirement:
            # Not a requirement this project can read. Deliberately not treated as a name:
            # classifying an unparseable string would report a state about a package that
            # may not exist.
            return Dependency(requirement, DependencyState.UNKNOWN)

        specifier = str(parsed.specifier)
        if not applies_under_emscripten(parsed, self.version):
            return Dependency(parsed.name, DependencyState.PLATFORM_EXCLUDED, specifier=specifier)

        extras = tuple(sorted(parsed.extras))
        normalised = normalise(parsed.name)
        bundled = self.packages.get(normalised)
        if bundled is None:
            installed = _classify_installed(normalised)
            return dataclasses.replace(installed, specifier=specifier, extras=extras)
        state = (
            DependencyState.VERSION_CONFLICT
            if _excludes_bundled_version(parsed, bundled)
            else bundled.state
        )
        return dataclasses.replace(bundled, state=state, specifier=specifier, extras=extras)


def applies_under_emscripten(parsed: Requirement, python_version: str) -> bool:
    """Whether a requirement's environment marker is true for a Pyodide install.

    Public for `doctor.closure`, which has to make the same judgement about the requirements
    it expands out of a distribution's metadata.

    An undefined marker name is treated as applying rather than as excluded: guessing
    "not needed" about a requirement whose marker cannot be evaluated is the direction that
    hides a real dependency.
    """
    if parsed.marker is None:
        return True
    try:
        return parsed.marker.evaluate(emscripten_environment(python_version))
    except UndefinedEnvironmentName:
        return True


def _excludes_bundled_version(parsed: Requirement, bundled: Dependency) -> bool:
    """Whether the requirement's pin rules out the only version obtainable.

    Only a *native* wheel traps you at Pyodide's version. A pure wheel Pyodide merely
    happens to bundle can still be fetched from PyPI at any version, which is measured
    rather than assumed: asking micropip for this project's own pinned rich installs that
    version over the older one Pyodide ships. Treating those as conflicts would make the
    whole of `wasm-requirements.txt` fail its own check.
    """
    return (
        bundled.state is DependencyState.BUNDLED_NATIVE
        and bundled.pyodide_version is not None
        and bool(str(parsed.specifier))
        and not parsed.specifier.contains(bundled.pyodide_version, prereleases=True)
    )


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


def normalise(name: str) -> str:
    """PEP 503 name normalisation, so `typing_extensions` and `typing-extensions` agree.

    Public because `doctor.closure` compares names against this module's keys and must
    normalise them the same way; two normalisers is one more than the number that can be
    correct.
    """
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
        name = normalise(str(entry["name"]))
        packages[name] = Dependency(
            name=name,
            state=_state_for(str(entry["file_name"])),
            pyodide_version=str(entry["version"]),
        )
    return Catalogue(version=str(info.get("python", "unknown")), packages=packages)
