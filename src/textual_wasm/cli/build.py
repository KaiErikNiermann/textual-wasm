"""Commands that produce something you can serve.

`build` writes a static directory; `dev` serves one. Between them they are the whole
shipping story - there is no toolchain at the far end and nothing for the deployer to
install.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from textual_wasm.bundler import PYODIDE_VERSION, BuildSpec
from textual_wasm.bundler import build as build_site
from textual_wasm.bundler import serve as serve_site
from textual_wasm.cli._app import app

DEFAULT_PORT: int = 8000


@app.command()
def build(
    entry: Annotated[str, typer.Argument(help="Application, as 'module:AppClass'.")],
    package: Annotated[Path, typer.Argument(help="Directory of the app's Python package.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Where to write.")] = Path("dist"),
    requirement: Annotated[
        list[str] | None,
        typer.Option("--requirement", "-r", help="Extra distribution. Repeatable."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Document title. Default: the application class name."),
    ] = None,
    template: Annotated[
        Path | None,
        typer.Option("--template", help="Directory of files to copy over the default page."),
    ] = None,
    worker: Annotated[
        bool,
        typer.Option("--worker/--main-thread", help="Run Python in a Web Worker."),
    ] = False,
) -> None:
    """Build a Textual app into a static site.

    The output needs no server and no build step to deploy: copy it somewhere that serves
    files. Pyodide and xterm.js come from a pinned CDN, so the directory itself stays small.

    The default page is bare - the terminal fills the viewport and nothing is drawn around
    it, because a Textual app already draws its own header and footer. `--template` replaces
    any part of that page with your own; the contract is an element with `id="terminal"` and
    a module script loading `./main.mjs`.

    `--worker` moves the interpreter off the main thread, so a slow call stops freezing the
    tab. It needs no special headers and deploys to the same static hosts. It does not make
    threads available: Pyodide has none in either mode.
    """
    console = Console()
    result = build_site(
        BuildSpec(
            entry=entry,
            package=package,
            output=output,
            requirements=tuple(requirement or ()),
            title=title,
            template=template,
            worker=worker,
        )
    )
    console.print(f"[bold green]built[/] {result.output} - {result.summary}")
    console.print(f"[dim]packages: {', '.join(result.packages)}[/]")
    console.print(f"[dim]pyodide {PYODIDE_VERSION} from CDN[/]")
    if worker:
        console.print("[dim]python runs in a Web Worker; no COOP/COEP headers required[/]")
    console.print(f"[dim]serve it with: textual-wasm dev {result.output}[/]")


@app.command()
def dev(
    directory: Annotated[Path, typer.Argument(help="A directory produced by `build`.")] = Path(
        "dist"
    ),
    port: Annotated[int, typer.Option("--port", "-p", help="Port to listen on.")] = (DEFAULT_PORT),
) -> None:
    """Serve a built site locally.

    Binds loopback only: a development server is not a deployment target.
    """
    console = Console()
    if not (directory / "app.json").exists():
        console.print(f"[bold red]{directory} is not a build[/]; run `textual-wasm build`")
        raise typer.Exit(2)
    console.print(f"serving [bold]{directory}[/] on http://127.0.0.1:{port}")
    try:
        serve_site(directory, port=port)
    except KeyboardInterrupt:
        console.print("stopped")
