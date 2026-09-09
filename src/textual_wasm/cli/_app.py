"""The Typer application, alone in a module so command modules can register against it.

Splitting this out avoids the cycle that otherwise appears: the package `__init__` has to
import every command module for its commands to exist, and each command module has to import
the app to decorate against.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    add_completion=False,
    help="Build, check and ship a Textual app as both a terminal TUI and a web page.",
)
