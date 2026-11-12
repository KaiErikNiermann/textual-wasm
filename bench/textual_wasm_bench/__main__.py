"""`python -m textual_wasm_bench`: run the benchmarks, or render a result file as tables."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.logging import RichHandler

from textual_wasm_bench import paths
from textual_wasm_bench.plan import PROFILES, Engine, Mode

app = typer.Typer(no_args_is_help=True, add_completion=False)

DEFAULT_OUT = paths.SCRATCH / "results.json"


@app.command()
def run(
    profile: Annotated[str, typer.Option(help=f"One of {', '.join(PROFILES)}.")] = "full",
    out: Annotated[Path, typer.Option(help="Result file; resumed if it exists.")] = DEFAULT_OUT,
    engine: Annotated[list[Engine] | None, typer.Option(help="Repeatable.")] = None,
    mode: Annotated[list[Mode] | None, typer.Option(help="main and/or worker.")] = None,
    only: Annotated[list[str] | None, typer.Option(help="Cases whose name contains this.")] = None,
    force: Annotated[bool, typer.Option(help="Rerun cases the file already has.")] = False,
    native: Annotated[bool, typer.Option(help="Also run the CPython controls.")] = True,
    browser: Annotated[bool, typer.Option(help="Run the browser cases.")] = True,
) -> None:
    """Run every selected case and write the results, resuming an interrupted run."""
    from textual_wasm_bench.runner import Selection  # noqa: PLC0415 - heavy imports
    from textual_wasm_bench.runner import run as run_all  # noqa: PLC0415

    if profile not in PROFILES:
        raise typer.BadParameter(f"unknown profile {profile!r}")
    run_all(
        profile,
        out,
        Selection(
            engines=tuple(engine or (Engine.CHROMIUM, Engine.FIREFOX)),
            modes=tuple(m for m in (mode or (Mode.MAIN, Mode.WORKER)) if m is not Mode.NONE),
            only=tuple(only or ()),
            force=force,
            include_native=native,
            include_browser=browser,
        ),
    )
    typer.echo(f"wrote {out}")


@app.command()
def report(
    results: Annotated[Path, typer.Argument(help="A result file from `run`.")],
    out: Annotated[Path, typer.Option("-o", help="Markdown to write.")] = paths.DOCS_TABLES,
    check: Annotated[
        bool, typer.Option(help="Fail if `out` is not already this rendering.")
    ] = False,
    baseline: Annotated[
        Path | None, typer.Option(help="An earlier result file to compare idle CPU against.")
    ] = None,
) -> None:
    """Render a result file as the tables the documentation includes."""
    from textual_wasm_bench.report import render  # noqa: PLC0415 - heavy imports

    rendered = render(results, baseline)
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != rendered:
            typer.echo(f"{out} is stale; run `just bench-report`", err=True)
            raise typer.Exit(1)
        return
    out.write_text(rendered, encoding="utf-8")
    typer.echo(f"wrote {out}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, handlers=[RichHandler(show_path=False)])
    app()


if __name__ == "__main__":
    main()
