"""Shared rendering for the command modules.

Kept apart from the commands so that what is *measured* and what is *displayed* stay
separable: the JSON forms of these reports are what the runtimes compare, and a rendering
change must never be able to alter them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

from textual_wasm.report import CheckStatus

if TYPE_CHECKING:
    from rich.console import Console

    from textual_wasm import doctor as doctor_module
    from textual_wasm.check import CheckReport
    from textual_wasm.compare import Comparison
    from textual_wasm.report import ProbeReport
    from textual_wasm.screen import LineDiff

STATUS_STYLE: dict[CheckStatus, str] = {
    CheckStatus.PASS: "bold green",
    CheckStatus.FAIL: "bold red",
    CheckStatus.SKIP: "dim",
}


SEVERITY_STYLE: dict[str, str] = {
    "silent_wrong": "bold red",
    "fatal": "bold red",
    "unsupported": "bold red",
    "loud_unclear": "yellow",
    "loud_clear": "dim",
}


def render_report(report: ProbeReport, console: Console) -> None:
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
            f"[{STATUS_STYLE[result.status]}]{result.status.value}[/]",
            result.detail,
        )
    console.print(checks)


def render_comparison(result: Comparison, console: Console) -> None:
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
            f"[{STATUS_STYLE[agreement.native]}]{agreement.native.value}[/]",
            f"[{STATUS_STYLE[agreement.wasm]}]{agreement.wasm.value}[/]",
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


LEG_STYLE: dict[str, str] = {
    "ran": "bold green",
    "skipped": "yellow",
    "failed": "bold red",
}


def render_check(report: CheckReport, console: Console) -> None:
    """Print what each runtime did, then what the ones that ran disagreed about."""
    legs = Table(
        title=f"{report.target} at {report.size[0]}x{report.size[1]}", title_justify="left"
    )
    legs.add_column("runtime")
    legs.add_column("status")
    # Folding, not truncating: for a skipped leg this column holds the command that would
    # enable it, and a shortened install hint is worse than none.
    legs.add_column("detail", overflow="fold")
    for leg in report.legs:
        legs.add_row(
            leg.leg.value,
            f"[{LEG_STYLE[leg.status.value]}]{leg.status.value}[/]",
            leg.detail,
        )
    console.print(legs)

    if report.runtimes is not None:
        render_comparison(report.runtimes, console)
    if report.render_diffs is not None:
        render_screen_diffs(report.render_diffs, console, left="terminal", right="browser")


def render_screen_diffs(
    diffs: tuple[LineDiff, ...], console: Console, *, left: str, right: str
) -> None:
    """Print rows on which two grids disagree, and the column where they stop matching.

    The column is the actionable half: a character-width disagreement moves everything after
    it, so the first divergent column names the character that was measured differently.
    """
    if not diffs:
        console.print(f"[bold green]identical[/]: {left} and {right} render the same")
        return
    table = Table(title="rows that differ", title_justify="left")
    for column in ("row", "col", left, right):
        table.add_column(column)
    for diff in diffs:
        table.add_row(
            str(diff.row),
            str(diff.first_divergent_column),
            repr(diff.left),
            repr(diff.right),
        )
    console.print(table)
    console.print(f"[bold red]{len(diffs)} row(s) differ[/]")


def render_findings(report: doctor_module.DoctorReport, console: Console) -> None:
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
            f"[{SEVERITY_STYLE.get(severity, 'default')}]{severity}[/]",
            finding.substitution.id,
            finding.source,
        )
    console.print(table)
    for finding in report.blocking_findings[:1]:
        # One expansion, not all of them: the point is to show what the guidance looks like
        # without turning the report into a wall the reader skims.
        console.print(finding.substitution.guidance, style="dim", highlight=False)


def render_dependencies(report: doctor_module.DoctorReport, console: Console) -> None:
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
