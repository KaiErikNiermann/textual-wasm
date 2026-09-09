"""Native runner for the feasibility probe.

The WASM runner (`scripts/run_pyodide_node.mjs`) calls the same
:func:`textual_wasm.probe.run_probe`; this module adds only argument parsing and rendering,
so that nothing runtime-specific can leak into what is being measured.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from textual_wasm.compare import Comparison
from textual_wasm.compare import compare as compare_reports
from textual_wasm.driver import DEFAULT_SIZE
from textual_wasm.pins import REQUIREMENTS_FILENAME, write_pins
from textual_wasm.probe import run_probe
from textual_wasm.report import CheckId, CheckStatus, ProbeReport

app = typer.Typer(add_completion=False, help=__doc__)

_STATUS_STYLE: dict[CheckStatus, str] = {
    CheckStatus.PASS: "bold green",
    CheckStatus.FAIL: "bold red",
    CheckStatus.SKIP: "dim",
}


def _render(report: ProbeReport, console: Console) -> None:
    """Print the report as a table; the JSON form is what the two runtimes compare."""
    facts = Table(title="runtime", show_header=False, title_justify="left")
    for field, value in (
        ("platform", report.runtime.platform),
        ("python", report.runtime.python_version),
        ("textual", report.runtime.textual_version),
        ("event loop", report.runtime.event_loop),
        ("threads available", str(report.runtime.threads_available)),
        ("eager task factory", str(report.runtime.eager_task_factory_accepted)),
        ("polyfills applied", ", ".join(report.runtime.polyfills_applied) or "none"),
    ):
        facts.add_row(field, value)
    console.print(facts)

    checks = Table(title="checks", title_justify="left")
    checks.add_column("check")
    checks.add_column("status")
    checks.add_column("detail")
    for result in report.checks:
        checks.add_row(
            result.check.value,
            f"[{_STATUS_STYLE[result.status]}]{result.status.value}[/]",
            result.detail,
        )
    console.print(checks)


@app.command()
def probe(
    width: Annotated[int, typer.Option(help="Forced grid width.")] = DEFAULT_SIZE[0],
    height: Annotated[int, typer.Option(help="Forced grid height.")] = DEFAULT_SIZE[1],
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the machine-comparable report instead.")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logs.")] = False,
) -> None:
    """Run the feasibility probe natively and exit non-zero if any check failed."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING)
    report = asyncio.run(run_probe(size=(width, height)))
    if as_json:
        typer.echo(report.to_json())
    else:
        _render(report, Console())
    raise typer.Exit(0 if report.ok else 1)


def _render_comparison(result: Comparison, console: Console) -> None:
    """Print the agreement matrix; disagreement is the only thing that matters here."""
    table = Table(title="native vs wasm", title_justify="left")
    table.add_column("check")
    table.add_column("native")
    table.add_column("wasm")
    table.add_column("agrees")
    for agreement in result.agreements:
        mark = "[bold green]yes[/]" if agreement.agrees else "[bold red]NO[/]"
        table.add_row(
            agreement.check.value,
            f"[{_STATUS_STYLE[agreement.native]}]{agreement.native.value}[/]",
            f"[{_STATUS_STYLE[agreement.wasm]}]{agreement.wasm.value}[/]",
            mark,
        )
    console.print(table)

    differences = Table(title="runtime differences", title_justify="left")
    differences.add_column("field")
    differences.add_column("native")
    differences.add_column("wasm")
    differences.add_column("expected")
    for difference in result.runtime_differences:
        differences.add_row(
            difference.field,
            difference.native,
            difference.wasm,
            "yes" if difference.expected else "[bold red]NO[/]",
        )
    console.print(differences)


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
    _render_comparison(result, console)
    verdict = (
        "[bold green]equivalent[/]: every check passed on both runtimes"
        if result.equivalent
        else "[bold red]not equivalent[/]"
    )
    console.print(verdict)
    raise typer.Exit(0 if result.equivalent else 1)


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
