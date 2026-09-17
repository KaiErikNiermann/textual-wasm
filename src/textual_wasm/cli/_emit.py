"""Writing a generated document, or checking the one on disk against it.

Three commands generate a file that is committed and then gated: the porting matrix, the
library table and the channel declarations. What makes that work is not the renderers, which
have nothing in common, but this - print, write, verify - and a second copy of it is how one
command grows a `--check` mode and another quietly does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from pathlib import Path


def emit(rendered: str, output: Path | None, *, verify: bool, command: str) -> None:
    """Write a generated document, or check the one on disk against it.

    Shared by `matrix`, `libraries` and `channels` because the three behaviours - print,
    write, verify - are identical for all of them and only the renderer differs. A second
    copy of this is exactly the kind of thing that grows a `--check` mode on one command and
    not the others.

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
