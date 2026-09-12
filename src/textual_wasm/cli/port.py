"""Commands that help someone port an app: what will break, and what to install.

The doctor, the pin generator and the porting matrix all read the same registry the runtime
diagnostics raise from, so a developer never gets one answer from the docs, another before
running and a third during.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from textual_wasm import doctor as doctor_module
from textual_wasm.cli._app import app
from textual_wasm.cli._render import render_closure, render_dependencies, render_findings
from textual_wasm.docs import LIBRARIES_PATH, MATRIX_PATH, render_libraries, render_matrix
from textual_wasm.pins import REQUIREMENTS_FILENAME, write_pins
from textual_wasm.report import CheckId
from textual_wasm.target import AppTarget


def _source_of(source: str) -> Path:
    """Resolve what to scan: a path, or the package an app reference lives in.

    Both forms are accepted because every other command here names an application as
    `module:AppClass`, and a single command that wants a path instead is the one people get
    wrong - with a `FileNotFoundError` naming the entry string, which reads as a missing file
    rather than as the wrong kind of argument.
    """
    if ":" not in source:
        return Path(source)
    return AppTarget(entry=source).package_directory()


@app.command()
def doctor(
    source: Annotated[
        str, typer.Argument(help="Application as 'module:AppClass', or a file or directory.")
    ],
    requirement: Annotated[
        list[str] | None,
        typer.Option("--requirement", "-r", help="Distribution to classify. Repeatable."),
    ] = None,
) -> None:
    """Report what will behave differently under Pyodide, before you run it there.

    Exits non-zero on anything blocking: a silent failure, a fatal call, an absent module, or
    a dependency with no wasm build. Things that raise honestly are reported but do not fail
    the run - the app will tell you about those itself.
    """
    console = Console()
    report = doctor_module.run(_source_of(source), requirements=requirement or ())
    render_findings(report, console)
    render_dependencies(report, console)
    render_closure(report, console)

    if report.ok:
        console.print("[bold green]no blocking issues[/]")
        raise typer.Exit(0)
    blocking = (
        len(report.blocking_findings)
        + len(report.blocking_dependencies)
        + len(report.closure.conflicts)
    )
    console.print(f"[bold red]{blocking} blocking issue(s)[/]")
    raise typer.Exit(1)


@app.command()
def pins(
    output: Annotated[
        Path | None,
        typer.Option(help=f"Where to write the pins (default: ./{REQUIREMENTS_FILENAME})."),
    ] = None,
) -> None:
    """Regenerate the WASM requirements file from the installed native environment."""
    destination = output or Path(REQUIREMENTS_FILENAME)
    for pin in write_pins(destination):
        typer.echo(pin)


@app.command()
def schema() -> None:
    """Print the check ids the report can contain, for the harness to cross-check against."""
    typer.echo(json.dumps([check.value for check in CheckId], indent=2))


if __name__ == "__main__":
    app()


def _emit(rendered: str, output: Path | None, *, verify: bool, command: str) -> None:
    """Write a generated document, or check the one on disk against it.

    Shared by `matrix` and `libraries` because the three behaviours - print, write, verify -
    are identical for both and only the renderer differs. A second copy of this is exactly
    the kind of thing that grows a `--check` mode on one command and not the other.

    Args:
        rendered: The document.
        output: Where to write, or None to print.
        verify: Compare instead of writing, for CI.
        command: How to regenerate, named in the failure message.

    Raises:
        typer.Exit: Non-zero when `verify` is set and the file is stale.
    """
    if output is None:
        typer.echo(rendered, nl=False)
        return
    if verify:
        current = output.read_text(encoding="utf-8") if output.exists() else ""
        if current != rendered:
            typer.echo(f"{output} is out of date; run `{command} -o {output}`", err=True)
            raise typer.Exit(1)
        typer.echo(f"{output} is up to date")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"wrote {output}")


@app.command()
def matrix(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help=f"Write here instead of stdout, e.g. {MATRIX_PATH}."),
    ] = None,
    verify: Annotated[
        bool,
        typer.Option("--check", help="Exit non-zero if the file on disk is out of date."),
    ] = False,
) -> None:
    """Render the porting matrix from the substitution registry.

    The matrix is generated rather than maintained, because a hand-written porting table is
    the first thing to rot: nothing fails when the runtime changes underneath it. `--check`
    is the CI form, which turns that silence into a failure.
    """
    _emit(render_matrix(), output, verify=verify, command="textual-wasm matrix")


@app.command()
def libraries(
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help=f"Write here instead of stdout, e.g. {LIBRARIES_PATH}."
        ),
    ] = None,
    verify: Annotated[
        bool,
        typer.Option("--check", help="Exit non-zero if the file on disk is out of date."),
    ] = False,
) -> None:
    """Render the add-on library support table from the ecosystem registry.

    Which third-party Textual widget libraries work in a browser, measured by installing
    each one into a real Pyodide and mounting its widgets rather than by reading READMEs.
    Generated for the same reason the porting matrix is: a compatibility table maintained by
    hand is wrong within a release and nothing fails when it drifts.
    """
    _emit(render_libraries(), output, verify=verify, command="textual-wasm libraries")
