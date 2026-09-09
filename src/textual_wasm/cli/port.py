"""Commands that help someone port an app: what will break, and what to install.

The doctor and the pin generator both read the same registry the runtime diagnostics raise
from, so a developer never gets one answer before running and a different one during.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from textual_wasm import doctor as doctor_module
from textual_wasm.cli._app import app
from textual_wasm.cli._render import render_dependencies, render_findings
from textual_wasm.pins import REQUIREMENTS_FILENAME, write_pins
from textual_wasm.report import CheckId


@app.command()
def doctor(
    source: Annotated[Path, typer.Argument(help="Application file or package directory.")],
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
    report = doctor_module.run(source, requirements=requirement or ())
    render_findings(report, console)
    render_dependencies(report, console)

    if report.ok:
        console.print("[bold green]no blocking issues[/]")
        raise typer.Exit(0)
    blocking = len(report.blocking_findings) + len(report.blocking_dependencies)
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
