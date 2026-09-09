"""Native runner for the feasibility probe.

The WASM runner (`scripts/run-pyodide-node.mjs`) calls the same
:func:`textual_wasm.probe.run_probe`; this module adds only argument parsing and rendering,
so that nothing runtime-specific can leak into what is being measured.
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
from rich.table import Table

from textual_wasm import doctor as doctor_module
from textual_wasm.compare import Comparison
from textual_wasm.compare import compare as compare_reports
from textual_wasm.compare import compare_screens as diff_screens
from textual_wasm.driver import DEFAULT_SIZE
from textual_wasm.pins import REQUIREMENTS_FILENAME, write_pins
from textual_wasm.probe import run_probe
from textual_wasm.report import CheckId, CheckStatus, ProbeReport, screen_from
from textual_wasm.screen import RenderedScreen
from textual_wasm.terminal import TMUX, capture_spike
from textual_wasm.terminal import version as tmux_version

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
        ("eager task factory", str(report.runtime.eager_task_factory_accepted)),
        ("runtime", report.runtime.runtime),
        ("threads available", str(report.runtime.threads_available)),
        ("jspi (run_sync)", str(report.runtime.jspi)),
        ("shared memory", str(report.runtime.shared_memory)),
        ("cross-origin isolated", str(report.runtime.cross_origin_isolated)),
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
    if not diffs:
        console.print(f"[bold green]identical[/]: {left.name} and {right.name} render the same")
        raise typer.Exit(0)

    table = Table(title="rows that differ", title_justify="left")
    table.add_column("row")
    table.add_column("col")
    table.add_column(left.name)
    table.add_column(right.name)
    for diff in diffs:
        table.add_row(
            str(diff.row),
            str(diff.first_divergent_column),
            repr(diff.left),
            repr(diff.right),
        )
    console.print(table)
    console.print(f"[bold red]{len(diffs)} row(s) differ[/]")
    raise typer.Exit(1)


@app.command()
def capture_terminal(
    width: Annotated[int, typer.Option(help="Pane width.")] = DEFAULT_SIZE[0],
    height: Annotated[int, typer.Option(help="Pane height.")] = DEFAULT_SIZE[1],
) -> None:
    """Render the app in a real terminal via tmux and emit the grid as JSON.

    The reference the other runtimes are checked against: Textual's own platform driver on a
    real pty, with nothing from this project in the path. Emits the same `{runtime, screen}`
    shape the browser harness does, so `compare-screens` reads either.
    """
    if TMUX is None:
        typer.echo("tmux is not installed; cannot capture a real terminal", err=True)
        raise typer.Exit(2)

    grid = capture_spike(columns=width, rows=height)
    payload = {
        "runtime": {"terminal": tmux_version(), "driver": "textual.drivers.linux_driver"},
        "screen": dataclasses.asdict(grid),
    }
    typer.echo(json.dumps(payload, indent=2))


_SEVERITY_STYLE: dict[str, str] = {
    "silent_wrong": "bold red",
    "fatal": "bold red",
    "unsupported": "bold red",
    "loud_unclear": "yellow",
    "loud_clear": "dim",
}


def _render_findings(report: doctor_module.DoctorReport, console: Console) -> None:
    """Print source findings, worst first."""
    if not report.findings:
        console.print("[bold green]no source findings[/]")
        return
    table = Table(title="source", title_justify="left")
    # The location is the actionable half; folding rather than truncating keeps it
    # clickable in a terminal, which a middle-elided path is not.
    table.add_column("location", overflow="fold")
    for column in ("severity", "issue", "code"):
        table.add_column(column)
    for finding in report.findings:
        severity = finding.substitution.severity.value
        table.add_row(
            finding.location,
            f"[{_SEVERITY_STYLE.get(severity, 'default')}]{severity}[/]",
            finding.substitution.id,
            finding.source,
        )
    console.print(table)
    for finding in report.blocking_findings[:1]:
        # One expansion, not all of them: the point is to show what the guidance looks like
        # without turning the report into a wall the reader skims.
        console.print(finding.substitution.guidance, style="dim", highlight=False)


def _render_dependencies(report: doctor_module.DoctorReport, console: Console) -> None:
    """Print dependency classifications, if any were requested."""
    if not report.dependencies:
        return
    table = Table(title="dependencies", title_justify="left")
    for column in ("package", "state", "notes"):
        table.add_column(column)
    for dependency in report.dependencies:
        style = "bold red" if dependency.blocks else "default"
        table.add_row(
            dependency.name,
            f"[{style}]{dependency.state.value}[/]",
            dependency.guidance,
        )
    console.print(table)


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
    _render_findings(report, console)
    _render_dependencies(report, console)

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
