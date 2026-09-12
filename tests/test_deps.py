"""Requirement classification, and the build pre-flight that depends on it.

Written against the bug it fixes. Before this, `Catalogue.classify` matched the requirement
string against the lock file verbatim, so *every* requirement carrying a version specifier -
which is every requirement `textual-wasm pins` emits, and every one
`importlib.metadata.requires()` returns - classified as `UNKNOWN` with `blocks=False`. The
dependency half of the doctor was therefore inert on real input while reporting success, and
nothing failed.

The two real-world cases that motivated it are here by name: `textual-pandas` pins
`pandas<=2.2.3` against Pyodide's bundled 3.0.2, and `textual-textarea` reaches
`tree-sitter>=0.25.0` against its bundled 0.23.2. Both were measured to fail under micropip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from textual_wasm.doctor.deps import (
    Catalogue,
    Dependency,
    DependencyState,
    emscripten_environment,
)

PYODIDE_PYTHON: Final[str] = "3.14.2"


@pytest.fixture
def catalogue() -> Catalogue:
    """A catalogue with one native package and one pure one, both older than PyPI's latest.

    Hand-built rather than read from the vendored lock file: the point of most of these tests
    is the *relationship* between a specifier and a bundled version, and a fixture makes that
    relationship explicit instead of depending on whatever Pyodide ships this month.
    """
    return Catalogue(
        version=PYODIDE_PYTHON,
        packages={
            "pandas": Dependency("pandas", DependencyState.BUNDLED_NATIVE, "3.0.2"),
            "tree-sitter": Dependency("tree-sitter", DependencyState.BUNDLED_NATIVE, "0.23.2"),
            "rich": Dependency("rich", DependencyState.PURE, "14.3.3"),
        },
    )


def test_a_bare_name_still_classifies(catalogue: Catalogue) -> None:
    """The old calling convention has to keep working; it is just no longer the only one."""
    assert catalogue.classify("pandas").state is DependencyState.BUNDLED_NATIVE


@pytest.mark.parametrize(
    "requirement",
    ["pandas==3.0.2", "pandas>=2.0", "pandas", "pandas<4", "pandas~=3.0"],
)
def test_a_specifier_that_admits_the_bundled_version_is_not_a_conflict(
    catalogue: Catalogue, requirement: str
) -> None:
    """The regression guard. Every one of these used to come back `UNKNOWN`."""
    dependency = catalogue.classify(requirement)
    assert dependency.state is DependencyState.BUNDLED_NATIVE
    assert not dependency.blocks


@pytest.mark.parametrize(
    ("requirement", "bundled"),
    [("pandas<=2.2.3", "3.0.2"), ("tree-sitter>=0.25.0", "0.23.2"), ("pandas<3", "3.0.2")],
)
def test_a_specifier_that_excludes_the_bundled_version_blocks(
    catalogue: Catalogue, requirement: str, bundled: str
) -> None:
    """A native package cannot be fetched from PyPI, so an excluding pin is a failed install."""
    dependency = catalogue.classify(requirement)
    assert dependency.state is DependencyState.VERSION_CONFLICT
    assert dependency.blocks
    # Both halves in the message: a report naming only one sends the reader back to the file.
    assert bundled in dependency.guidance
    assert dependency.specifier in dependency.guidance


def test_a_pure_wheel_is_never_a_version_conflict(catalogue: Catalogue) -> None:
    """Measured, not assumed: `micropip.install` fetches a pure wheel from PyPI at whatever
    version you ask for, over the top of the one Pyodide bundles. Flagging these would make
    this project's own pin list fail its own check - which it did, on the first attempt."""
    dependency = catalogue.classify("rich==15.0.0")
    assert dependency.state is DependencyState.PURE
    assert not dependency.blocks


def test_a_marker_that_is_false_under_emscripten_excludes_the_requirement(
    catalogue: Catalogue,
) -> None:
    """A Windows-only dependency is not a portability problem, and reporting it as one is a
    false alarm on a dependency list that is entirely fine."""
    dependency = catalogue.classify('pywin32; sys_platform == "win32"')
    assert dependency.state is DependencyState.PLATFORM_EXCLUDED
    assert not dependency.blocks


def test_an_extra_nobody_asked_for_is_excluded(catalogue: Catalogue) -> None:
    """`extra` is `""` in the environment rather than absent: absent makes the marker raise,
    and an unrequested extra is precisely a requirement that is not installed."""
    assert (
        catalogue.classify('tree-sitter>=0.25.0; extra == "syntax"').state
        is DependencyState.PLATFORM_EXCLUDED
    )


def test_requested_extras_are_recorded(catalogue: Catalogue) -> None:
    """The doctor resolves one level. Saying which extras it could not look inside is better
    than implying they were checked - `textual[syntax]` is the case that matters."""
    assert catalogue.classify("rich[jupyter]>=13").extras == ("jupyter",)


def test_an_unparseable_requirement_is_unknown_not_a_name(catalogue: Catalogue) -> None:
    """Classifying garbage as a package name would report a state about a nonexistent thing."""
    assert catalogue.classify("this is not a requirement!!").state is DependencyState.UNKNOWN


def test_the_marker_environment_says_emscripten() -> None:
    environment = emscripten_environment(PYODIDE_PYTHON)
    assert environment["sys_platform"] == "emscripten"
    assert environment["platform_machine"] == "wasm32"
    assert environment["python_version"] == "3.14"
    assert environment["extra"] == ""


def test_this_projects_own_pins_do_not_conflict() -> None:
    """The end-to-end regression: `wasm-requirements.txt` is `==`-pinned throughout, it is
    what every build installs, and it must classify as installable against the real runtime.

    Skipped rather than failed where the vendored runtime is absent - the lock file only
    exists in a checkout that ran `pnpm install`, and a missing one is an unchecked build
    rather than a broken one.
    """
    from textual_wasm.doctor import load_catalogue  # noqa: PLC0415

    root = Path(__file__).resolve().parent.parent
    try:
        real = load_catalogue(root / "node_modules" / "pyodide" / "pyodide-lock.json")
    except FileNotFoundError:
        pytest.skip("no vendored Pyodide runtime to classify against")

    requirements = [
        line.strip()
        for line in (root / "wasm-requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    blocking = [
        dependency
        for dependency in (real.classify(requirement) for requirement in requirements)
        if dependency.blocks
    ]
    assert not blocking, f"own closure would not install: {[d.name for d in blocking]}"
