"""Which application to run, and how a harness knows it drew.

Every runtime leg needs the same four facts: what to import, what text means the first
render finished, what to type, and what text means the typing was handled. A terminal
capture polls a pane for them, the browser harness waits on the buffer for them, and the
probe asserts on them - so they are defined once here rather than three times in three
languages.

The two markers are what make a check meaningful on an app this project has never seen.
Without a ready marker a harness cannot distinguish "the app has drawn" from "the runtime
has not started yet", and it would race the app rather than measure it.
"""

from __future__ import annotations

import contextlib
import dataclasses
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from textual.app import App

SPIKE_ENTRY: Final[str] = "textual_wasm.app:SpikeApp"
"""The bundled demo, used when no application is named."""


class EntryError(ValueError):
    """Raised when a `module:AppClass` reference cannot be resolved."""


@contextlib.contextmanager
def working_directory_importable() -> Generator[None]:
    """Put the working directory on `sys.path`, as `python -m` does.

    A console script does not do this and `python -m` does, which would otherwise make
    `textual-wasm probe --app myapp:App` fail on an application that `python -m myapp` runs
    perfectly - and fail with a bare `ModuleNotFoundError`, which sends the reader looking
    for a packaging mistake that is not there.

    Applied wherever this package resolves an app reference, so every leg of a check reaches
    the same application by the same rule.
    """
    cwd = str(Path.cwd())
    if cwd in sys.path:
        yield
        return
    sys.path.insert(0, cwd)
    try:
        yield
    finally:
        sys.path.remove(cwd)


@dataclasses.dataclass(frozen=True, slots=True)
class AppTarget:
    """An application under test, and the observations that prove it is running."""

    entry: str
    """`module:AppClass`, the same form Textual's own runner and `build` accept."""

    ready_marker: str | None = None
    """Text that appears once the first render is complete.

    Optional, and its absence downgrades rather than breaks: a harness then waits for any
    non-blank screen, which is weaker but still an observation.
    """

    keys: str = ""
    """Literal keystrokes to feed once ready. Empty means the input path is not exercised."""

    settled_marker: str | None = None
    """Text that appears once those keystrokes have been handled.

    Required for `keys` to be checkable at all: a screen captured immediately after typing
    is a screen that may not have processed the input, and the harness would be measuring
    its own timing.
    """

    def __post_init__(self) -> None:
        if ":" not in self.entry:
            raise EntryError(f"expected 'module:AppClass', got {self.entry!r}")
        if self.keys and self.settled_marker is None:
            raise EntryError(
                "keys were given without a settled marker; there would be no way to tell a "
                "screen that handled them from one that has not yet"
            )

    @property
    def module_name(self) -> str:
        return self.entry.partition(":")[0]

    @property
    def attribute(self) -> str:
        return self.entry.partition(":")[2]

    @property
    def exercises_input(self) -> bool:
        """Whether this target can settle the key-input question."""
        return bool(self.keys) and self.settled_marker is not None

    @classmethod
    def from_mapping(cls, source: Mapping[str, object]) -> AppTarget:
        """Rebuild a target that crossed a process or FFI boundary as JSON.

        Validated here rather than trusted: the Pyodide harness marshals this through
        JavaScript, and a marker that arrives as the wrong type would otherwise surface as a
        harness that waits out its timeout.

        Raises:
            TypeError: If a field is present with the wrong JSON type.
        """
        return cls(
            entry=_as_str(source, "entry"),
            ready_marker=_as_optional_str(source, "ready_marker"),
            keys=_as_optional_str(source, "keys") or "",
            settled_marker=_as_optional_str(source, "settled_marker"),
        )

    def package_directory(self) -> Path:
        """The directory of the package the app lives in, which a build has to copy.

        Found through the import system rather than guessed from the entry string, so a
        package installed anywhere works the same as one in the working directory.

        Raises:
            EntryError: If the app's top-level module is not a package. A single module has
                no directory to copy, and the browser build needs one to reconstruct the
                import path.
        """
        import importlib.util  # noqa: PLC0415 - deferred, like `load`

        top_level = self.module_name.partition(".")[0]
        with working_directory_importable():
            spec = importlib.util.find_spec(top_level)
        search = None if spec is None else spec.submodule_search_locations
        locations = list(search) if search is not None else []
        if not locations:
            raise EntryError(
                f"{top_level!r} is not a package, so there is no directory to build from; "
                f"put the app in a package, or name the directory explicitly"
            )
        return Path(locations[0])

    def load(self) -> type[App[object]]:
        """Import the application class.

        Returns:
            The class named by `entry`.

        Raises:
            EntryError: If the module imports but has no such attribute. An import failure
                is left to propagate as itself, because a missing dependency reported as a
                bad entry point sends the reader to the wrong place.
        """
        import importlib  # noqa: PLC0415 - deferred so importing this module stays cheap

        with working_directory_importable():
            module = importlib.import_module(self.module_name)
        try:
            attribute = getattr(module, self.attribute)
        except AttributeError as error:
            raise EntryError(f"{self.module_name} has no {self.attribute!r}") from error
        # An arbitrary app is `App[Whatever]`, and nothing here reads its return value as
        # anything but an object, so this narrows a genuinely unknown parameter rather than
        # papering over one that could be inferred.
        return cast("type[App[object]]", attribute)


def _as_str(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key!r} must be a string, got {type(value).__name__}")
    return value


def _as_optional_str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{key!r} must be a string or null, got {type(value).__name__}")
    return value


SPIKE_TARGET: Final[AppTarget] = AppTarget(
    entry=SPIKE_ENTRY,
    ready_marker="TEXTUAL-WASM-SPIKE",
    keys="a",
    settled_marker="pressed 1",
)
"""The default target: this project's own demo app.

The markers are the app's own strings, restated here rather than imported, because
`textual_wasm.app` imports Textual and this module is loaded by hosts that must not import
Textual yet. `tests/test_target.py` pins them to the app so the copy cannot drift.
"""


def resolve_target(
    entry: str | None,
    *,
    ready_marker: str | None = None,
    keys: str | None = None,
    settled_marker: str | None = None,
) -> AppTarget:
    """Build a target from command-line options, filling in the demo's own markers.

    Naming no application, or naming the bundled demo without markers, yields
    :data:`SPIKE_TARGET` - so `textual-wasm check` with no arguments is a complete run
    rather than a run with two checks skipped.

    Args:
        entry: `module:AppClass`, or None for the bundled demo.
        ready_marker: Text meaning the first render finished.
        keys: Keystrokes to feed once ready.
        settled_marker: Text meaning those keystrokes were handled.

    Returns:
        The target to hand to every leg of the check.
    """
    resolved = entry or SPIKE_ENTRY
    defaults = SPIKE_TARGET if resolved == SPIKE_ENTRY else AppTarget(entry=resolved)
    return AppTarget(
        entry=resolved,
        ready_marker=ready_marker if ready_marker is not None else defaults.ready_marker,
        keys=keys if keys is not None else defaults.keys,
        settled_marker=settled_marker if settled_marker is not None else defaults.settled_marker,
    )
