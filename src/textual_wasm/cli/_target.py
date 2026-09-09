"""The four options that name an application, shared by every command that runs one.

Declared once because `probe` and `check` have to agree exactly: a marker that means one
thing to the native leg and another to the browser leg would produce a disagreement that is
about the harness rather than about the runtime.
"""

from __future__ import annotations

from typing import Annotated

import typer

EntryOption = Annotated[
    str | None,
    typer.Option("--app", help="Application to run, as 'module:AppClass'. Default: the demo."),
]

ReadyMarkerOption = Annotated[
    str | None,
    typer.Option("--ready-marker", help="Text that appears once the app has drawn."),
]

KeysOption = Annotated[
    str | None,
    typer.Option("--keys", help="Keystrokes to feed once the app is ready."),
]

SettledMarkerOption = Annotated[
    str | None,
    typer.Option("--settled-marker", help="Text that appears once those keys were handled."),
]
