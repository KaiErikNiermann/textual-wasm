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
from rich.markup import escape

from textual_wasm.bundler import (
    PYODIDE_VERSION,
    BuildResult,
    BuildSpec,
    UnsatisfiableRequirementsError,
)
from textual_wasm.bundler import build as build_site
from textual_wasm.bundler import serve as serve_site
from textual_wasm.cli._app import app
from textual_wasm.target import EntryError

DEFAULT_PORT: int = 8000


def _report_conflicts(error: UnsatisfiableRequirementsError, console: Console) -> None:
    """Name every unsatisfiable requirement, one per line.

    Listed rather than wrapped into the exception's single sentence: this is the one failure
    whose fix is a decision per dependency, and a paragraph of three of them is unreadable
    in a terminal.
    """
    console.print("[bold red]cannot build[/]: the closure cannot be installed as written")
    for conflict in error.conflicts:
        console.print(
            f"  [bold]{escape(conflict.name + conflict.specifier)}[/] - "
            f"{escape(conflict.guidance)}",
            emoji=False,
        )
    for clash in error.closure_conflicts:
        console.print(
            f"  [bold]{escape(clash.dependent)}[/] - {escape(clash.guidance)}", emoji=False
        )
    console.print(
        "[dim]run `textual-wasm doctor` with -r for each requirement to see the whole "
        "picture, or --no-check-dependencies to build anyway[/]"
    )


def _report_entry_failure(error: Exception, console: Console, entry: str) -> None:
    """Report a mistake in what the user typed, without a traceback through our own frames.

    Both halves are user input, and Rich rewrites two different things in it. `escape`
    handles square brackets; emoji shortcodes are a separate pass that it does not touch, so
    an entry of `pkg.mod:X` prints as `pkg.mod` plus an emoji unless it is turned off here.
    """
    console.print(f"[bold red]cannot build[/] {escape(entry)}: {escape(str(error))}", emoji=False)
    if isinstance(error, ModuleNotFoundError):
        console.print(
            "[dim]the app is imported to check the entry resolves; pass "
            "--no-verify-entry if it can only be imported inside Pyodide[/]"
        )


def _report_success(
    result: BuildResult, console: Console, *, worker: bool, storage: bool, asked_to_check: bool
) -> None:
    """Say what was built, and on what terms.

    The terms matter as much as the result: a build that could not classify its dependencies
    is weaker than one that could, and this is the only place that can tell the user which
    of the two they just got.
    """
    for note in result.notes:
        console.print(f"[bold yellow]warning[/] {escape(note)}", emoji=False)
    console.print(f"[bold green]built[/] {result.output} - {result.summary}")
    console.print(f"[dim]packages: {', '.join(result.packages)}[/]")
    console.print(f"[dim]pyodide {PYODIDE_VERSION} from CDN[/]")
    if worker:
        console.print("[dim]python runs in a Web Worker; no COOP/COEP headers required[/]")
    if storage:
        console.print(
            "[dim]persistent storage mounted at /persist (IndexedDB); call "
            "textual_wasm.storage.Store.flush() to make writes durable[/]"
        )
    if not result.dependencies_checked:
        # Two different reasons, and saying the wrong one is worse than saying nothing: a
        # build that skipped the check on request must not be told to install a runtime.
        reason = (
            "no local Pyodide runtime to read a package set from (`pnpm add -D pyodide` "
            "enables the check)"
            if asked_to_check
            else "--no-check-dependencies was passed"
        )
        console.print(f"[dim]dependencies not classified against Pyodide: {reason}[/]")
    console.print(f"[dim]serve it with: textual-wasm dev {result.output}[/]")


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
    storage: Annotated[
        bool,
        typer.Option(
            "--storage/--no-storage",
            help="Mount a persistent browser filesystem for textual_wasm.storage to use.",
        ),
    ] = False,
    verify_entry: Annotated[
        bool,
        typer.Option(
            "--verify-entry/--no-verify-entry",
            help="Import the app first, to check the entry resolves. Off for apps that only "
            "import inside Pyodide.",
        ),
    ] = True,
    check_dependencies: Annotated[
        bool,
        typer.Option(
            "--check-dependencies/--no-check-dependencies",
            help="Refuse to build a closure Pyodide cannot install. Off skips the check.",
        ),
    ] = True,
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

    `--storage` mounts a persistent filesystem, which is what `textual_wasm.storage` writes
    into. Without it an app that uses the module still runs, reporting its store as
    ephemeral rather than raising.
    """
    console = Console()
    try:
        result = build_site(
            BuildSpec(
                entry=entry,
                package=package,
                output=output,
                requirements=tuple(requirement or ()),
                title=title,
                template=template,
                worker=worker,
                storage=storage,
                verify_entry=verify_entry,
                check_dependencies=check_dependencies,
            )
        )
    except (EntryError, ModuleNotFoundError) as error:
        # A mistake in what the user typed, not a fault in this program, and a sixty-line
        # traceback through our own frames buries the one line naming the wrong word.
        # Anything unexpected still propagates and still gets its traceback.
        _report_entry_failure(error, console, entry)
        raise typer.Exit(2) from error
    except UnsatisfiableRequirementsError as error:
        _report_conflicts(error, console)
        raise typer.Exit(2) from error
    except (FileNotFoundError, NotADirectoryError) as error:
        # The exception carries only the path, so the message has to supply what it was.
        problem = (
            "is not a directory" if isinstance(error, NotADirectoryError) else "does not exist"
        )
        console.print(f"[bold red]cannot build[/]: the package directory {package} {problem}")
        console.print("[dim]name the directory holding the app's Python package[/]")
        raise typer.Exit(2) from error
    _report_success(
        result, console, worker=worker, storage=storage, asked_to_check=check_dependencies
    )


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
