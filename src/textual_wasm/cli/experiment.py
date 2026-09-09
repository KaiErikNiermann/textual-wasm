"""Commands that run the experiment: probe a runtime, and compare two of them.

These exist to answer "does it behave the same over there", so they deliberately do nothing
clever. Everything they print has a JSON form, and the JSON is what the comparison reads.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console

from textual_wasm.cli._app import app
from textual_wasm.cli._render import render_comparison, render_report, render_screen_diffs
from textual_wasm.cli._target import (
    EntryOption,
    KeysOption,
    ReadyMarkerOption,
    SettledMarkerOption,
)
from textual_wasm.compare import compare as compare_reports
from textual_wasm.compare import compare_screens as diff_screens
from textual_wasm.driver import DEFAULT_SIZE
from textual_wasm.probe import run_probe
from textual_wasm.reference import PLATFORM_DRIVER_LABEL
from textual_wasm.report import ProbeReport, screen_from
from textual_wasm.screen import RenderedScreen
from textual_wasm.target import resolve_target
from textual_wasm.terminal import capture_target
from textual_wasm.terminal import usable as terminal_usable
from textual_wasm.terminal import version as tmux_version


@app.command()
def probe(
    entry: EntryOption = None,
    ready_marker: ReadyMarkerOption = None,
    keys: KeysOption = None,
    settled_marker: SettledMarkerOption = None,
    width: Annotated[int, typer.Option(help="Forced grid width.")] = DEFAULT_SIZE[0],
    height: Annotated[int, typer.Option(help="Forced grid height.")] = DEFAULT_SIZE[1],
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the machine-comparable report instead.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logs.")] = False,
) -> None:
    """Run the feasibility probe natively and exit non-zero if any check failed."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)
    target = resolve_target(
        entry, ready_marker=ready_marker, keys=keys, settled_marker=settled_marker
    )
    report = asyncio.run(run_probe(target=target, size=(width, height)))
    if as_json:
        typer.echo(report.to_json())
    else:
        render_report(report, Console())
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def compare(
    native: Annotated[Path, typer.Argument(help="JSON report from the native run.")],
    wasm: Annotated[Path, typer.Argument(help="JSON report from the Pyodide run.")],
) -> None:
    """Diff two probe reports and exit non-zero unless the runtimes are equivalent."""
    result = compare_reports(
        ProbeReport.from_json(native.read_text(encoding="utf-8")),
        ProbeReport.from_json(wasm.read_text(encoding="utf-8")),
    )
    console = Console()
    render_comparison(result, console)
    verdict = (
        "[bold green]equivalent[/]: every check passed on both runtimes"
        if result.equivalent
        else "[bold red]not equivalent[/]"
    )
    console.print(verdict)
    raise typer.Exit(0 if result.equivalent else 1)


def _load_screen(source: Path) -> RenderedScreen:
    """Read the `screen` object out of any report that carries one.

    Both a probe report and the browser harness's output have a top-level `screen`; the
    browser's has nothing else, since it cannot run the Python checks.
    """
    payload: object = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise typer.BadParameter(f"{source} is not a JSON object")
    screen = cast("dict[str, object]", payload).get("screen")
    if not isinstance(screen, dict):
        raise typer.BadParameter(f"{source} has no 'screen' object")
    return screen_from(cast("dict[str, object]", screen))


@app.command()
def compare_screens(
    left: Annotated[Path, typer.Argument(help="Report carrying the reference grid.")],
    right: Annotated[Path, typer.Argument(help="Report carrying the grid to check.")],
) -> None:
    """Diff two rendered grids and exit non-zero if any row differs.

    The grids come from different terminal emulators with different character-width tables,
    so a difference here is the font-metric risk showing itself - reported by row and by the
    column at which the two stop agreeing.
    """
    console = Console()
    diffs = diff_screens(_load_screen(left), _load_screen(right))
    render_screen_diffs(diffs, console, left=left.name, right=right.name)
    raise typer.Exit(1 if diffs else 0)


@app.command()
def capture_terminal(
    entry: EntryOption = None,
    ready_marker: ReadyMarkerOption = None,
    keys: KeysOption = None,
    settled_marker: SettledMarkerOption = None,
    width: Annotated[int, typer.Option(help="Pane width.")] = DEFAULT_SIZE[0],
    height: Annotated[int, typer.Option(help="Pane height.")] = DEFAULT_SIZE[1],
) -> None:
    """Render the app in a real terminal via tmux and emit the grid as JSON.

    The reference the other runtimes are checked against: Textual's own platform driver on a
    real pty, with nothing from this project in the path. Emits the same `{runtime, screen}`
    shape the browser harness does, so `compare-screens` reads either.
    """
    ready, reason = terminal_usable()
    if not ready:
        typer.echo(reason, err=True)
        raise typer.Exit(2)

    target = resolve_target(
        entry, ready_marker=ready_marker, keys=keys, settled_marker=settled_marker
    )
    grid = capture_target(target, columns=width, rows=height)
    payload = {
        "target": target.entry,
        "runtime": {"terminal": tmux_version(), "driver": PLATFORM_DRIVER_LABEL},
        "screen": dataclasses.asdict(grid),
    }
    typer.echo(json.dumps(payload, indent=2))
