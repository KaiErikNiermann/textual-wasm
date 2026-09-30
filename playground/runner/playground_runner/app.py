"""Turn the program in the page's URL fragment into a running Textual app.

The playground page puts the editor's contents into this frame's fragment and reloads it, so
every run is a fresh interpreter: nothing a previous program imported, patched or left
running can leak into the next one, and the runtime needs no teardown path it was never
designed to have. Pyodide's files come from the browser cache after the first run.

The build's entry is `create`, which ``start()`` calls with no arguments and runs the result
of - so it can hand back either the user's app or one that explains why there is none.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar
from unittest import mock

from rich.traceback import Traceback
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from playground_runner import share

PROGRAM_NAME = "app.py"
"""What the program is saved as, and so what its tracebacks name. Matches the editor's tab."""


class NoAppError(LookupError):
    """The program ran to the end without defining or running a Textual app."""


class Failure(App[None]):
    """Shown instead of the program when there is nothing to run."""

    CSS: ClassVar[str] = """
    #heading { padding: 1 2; background: $error; color: $text; text-style: bold; }
    #detail { padding: 1 2; }
    """

    def __init__(self, heading: str, detail: str | Traceback) -> None:
        super().__init__()
        self._heading = heading
        self._detail = detail

    def compose(self) -> ComposeResult:
        yield Static(self._heading, id="heading")
        with VerticalScroll():
            yield Static(self._detail, id="detail")


def _is_app_class(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, App) and value.__module__ == "__main__"


def _app_in(namespace: dict[str, Any]) -> App[Any]:
    """The app a program left behind without running it: an instance, else the last class."""
    values = tuple(namespace.values())
    instances: list[App[Any]] = [value for value in values if isinstance(value, App)]
    if instances:
        return instances[-1]
    if classes := [value for value in values if _is_app_class(value)]:
        return classes[-1]()
    raise NoAppError(
        "the program defines no Textual app: subclass textual.app.App, or end with MyApp().run()"
    )


def program_frames(trace: TracebackType | None, path: Path) -> TracebackType | None:
    """The traceback from the program's first frame on, without the runner's own."""
    while trace is not None and trace.tb_frame.f_code.co_filename != str(path):
        trace = trace.tb_next
    return trace


def load(source: str, directory: Path) -> App[Any]:
    """Run ``source`` as ``__main__`` and return the app it builds.

    Run as ``__main__`` so the idiomatic ``if __name__ == "__main__": MyApp().run()`` ending
    works unchanged. ``App.run`` is intercepted while the program executes - its blocking
    ``asyncio.run`` cannot work inside the page's already-running event loop - and the app
    it was called on is the one returned. A program that never calls it is searched for an
    app instead.

    Raises:
        NoAppError: If the program neither runs nor defines an app.
        Exception: Whatever the program itself raises while executing.
    """
    path = directory / PROGRAM_NAME
    path.write_text(source)
    started: list[App[Any]] = []

    def capture(self: App[Any], *_args: object, **_kwargs: object) -> None:
        started.append(self)

    with mock.patch.object(App, "run", capture):
        namespace = runpy.run_path(str(path), run_name="__main__")
    return started[-1] if started else _app_in(namespace)


def create() -> App[Any]:
    """The build's entry: the program in this frame's URL fragment, ready to run."""
    import js  # noqa: PLC0415 - exists only inside Pyodide

    try:
        source = share.decode(js.location.hash)
    except share.ShareError as error:
        return Failure("No program to run", str(error))
    try:
        return load(source, Path.cwd())
    except NoAppError as error:
        return Failure("Nothing to run", str(error))
    except Exception as error:
        # A SyntaxError has no frame in the program - it never started - so its trace would
        # be empty; the exception itself names the line, and rich renders that.
        trace = program_frames(error.__traceback__, Path.cwd() / PROGRAM_NAME)
        return Failure(
            f"{PROGRAM_NAME} raised {type(error).__name__}",
            Traceback.from_exception(type(error), error, trace),
        )
