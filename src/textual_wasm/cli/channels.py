"""Generate the page's type declarations from the application's channel declarations.

The same shape as `matrix` and `libraries`: render, write, and `--check` to fail a build when
what is committed no longer matches what generated it. That gate is the point. A `.d.ts`
written by hand beside a Python module describing the same channels is two declarations that
agree until one of them is edited, and nothing fails when they stop - the page keeps
type-checking against a shape the application no longer sends.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from textual_wasm.channels import collect
from textual_wasm.cli._app import app
from textual_wasm.cli._emit import emit
from textual_wasm.typegen import UnsupportedTypeError, build, render_schema, render_typescript

if TYPE_CHECKING:
    import types

DEFAULT_OUTPUT: str = "channels.d.ts"
"""Named in the help text so the command reads as a thing with an obvious use."""


def _import(module_name: str, search_path: Path | None) -> types.ModuleType:
    """Import a module of channel declarations, optionally from a directory.

    `--path` exists because the declarations usually live in an application package that is
    not installed - the same package `build` reads straight off disk. Requiring
    `pip install -e .` before a code generator will run is the kind of friction that gets a
    generator replaced with a hand-written file.

    Raises:
        typer.Exit: Non-zero with the import error, which is almost always a missing
            `--path` and reads as nonsense without being told so.
    """
    if search_path is not None:
        sys.path.insert(0, str(search_path.resolve()))
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        typer.echo(f"could not import {module_name}: {error}", err=True)
        if search_path is None:
            typer.echo("if it is not installed, point --path at the directory holding it", err=True)
        raise typer.Exit(1) from error


@app.command()
def channels(
    module: Annotated[
        str,
        typer.Argument(help="The module declaring the channels, e.g. myapp.channels."),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help=f"Write here instead of stdout, e.g. page/{DEFAULT_OUTPUT}."
        ),
    ] = None,
    search_path: Annotated[
        Path | None,
        typer.Option("--path", help="A directory to import from, for a package not installed."),
    ] = None,
    schema: Annotated[
        bool,
        typer.Option("--schema", help="Emit JSON Schema instead of TypeScript declarations."),
    ] = False,
    verify: Annotated[
        bool,
        typer.Option("--check", help="Exit non-zero if the file on disk is out of date."),
    ] = False,
) -> None:
    """Render TypeScript declarations for every channel an application declares.

    One declaration in Python types both sides: `bridge.send("gian", …)` becomes a type error
    on the page rather than a message nobody receives, and a payload that gained a field is a
    type error until the page handles it.

    `--schema` emits the same model as JSON Schema, for runtime validation or for feeding a
    different generator. Both come off one walk of the Python types, so they cannot disagree.
    """
    declarations = collect(_import(module, search_path))
    try:
        model = build(declarations)
    except UnsupportedTypeError as error:
        typer.echo(f"{module}: {error}", err=True)
        raise typer.Exit(1) from error

    rendered = (
        f"{json.dumps(render_schema(model), indent=2)}\n" if schema else render_typescript(model)
    )
    # Every option that changes the output goes into the hint, because the hint is what a
    # failing gate tells someone to run and a command that is missing `--path` does not work
    # when pasted.
    options = "".join(
        part
        for part in (
            f" --path {search_path}" if search_path is not None else "",
            " --schema" if schema else "",
        )
        if part
    )
    emit(rendered, output, verify=verify, command=f"textual-wasm channels {module}{options}")
