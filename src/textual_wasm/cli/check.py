"""The command that runs one app on every runtime and reports whether they agreed.

The whole project in one line: `textual-wasm check --app myapp:App`.
"""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from rich.console import Console

from textual_wasm.check import BROWSERS, DEFAULT_BROWSER, LegStatus, run_check
from textual_wasm.cli._app import app
from textual_wasm.cli._render import render_check
from textual_wasm.cli._target import (
    EntryOption,
    KeysOption,
    ReadyMarkerOption,
    SettledMarkerOption,
)
from textual_wasm.driver import DEFAULT_SIZE
from textual_wasm.target import resolve_target


@app.command()
def check(
    entry: EntryOption = None,
    ready_marker: ReadyMarkerOption = None,
    keys: KeysOption = None,
    settled_marker: SettledMarkerOption = None,
    width: Annotated[int, typer.Option(help="Grid width every runtime is forced to.")] = (
        DEFAULT_SIZE[0]
    ),
    height: Annotated[int, typer.Option(help="Grid height every runtime is forced to.")] = (
        DEFAULT_SIZE[1]
    ),
    browser: Annotated[
        str,
        typer.Option(
            "--browser",
            help=(
                "Engine for the browser leg: chromium, firefox or webkit for Playwright's "
                "own builds, chrome or msedge for the ones installed here."
            ),
        ),
    ] = DEFAULT_BROWSER,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Also fail if a runtime could not be checked at all."),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logs.")] = False,
) -> None:
    """Run an app natively, under Pyodide, in a browser and in a real terminal, and compare.

    Every runtime this machine cannot offer is reported as skipped with the command that
    would enable it, and the rest still produce a verdict. `--strict` is for CI, where a
    silently narrower check is the thing you are trying to prevent.
    """
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)
    if browser not in BROWSERS:
        raise typer.BadParameter(f"expected one of {', '.join(BROWSERS)}", param_hint="--browser")
    console = Console()
    report = run_check(
        resolve_target(entry, ready_marker=ready_marker, keys=keys, settled_marker=settled_marker),
        size=(width, height),
        browser=browser,
    )
    render_check(report, console)

    if not report.ok:
        console.print("[bold red]not equivalent[/]")
        raise typer.Exit(1)
    if strict and report.skipped:
        names = ", ".join(leg.leg.value for leg in report.skipped)
        console.print(f"[bold red]incomplete[/]: --strict was given and {names} did not run")
        raise typer.Exit(2)

    ran = sum(leg.status is LegStatus.RAN for leg in report.legs)
    console.print(f"[bold green]equivalent[/] across {ran} runtime(s)")
