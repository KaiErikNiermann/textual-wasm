"""The exception and warning types this module raises in place of Pyodide's own.

Both carry the :class:`~textual_wasm.substitutions.Substitution` that produced them, so the
text a developer reads is the text in the registry rather than a second copy that can drift.

`__rich__` is not decoration. `App._handle_exception` (`textual/app.py:3276`) checks for it and,
when present, routes the exception through `panic()` and renders it itself instead of dumping a
traceback. That is the supported way to put a legible message in front of someone whose only
other channel is a browser console they are not watching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import RenderableType

    from textual_wasm.substitutions import Substitution


def _render(substitution: Substitution, detail: str) -> RenderableType:
    """Build the panel both the exception and the warning display."""
    body = [
        Text(substitution.observed, style="default"),
        Text(""),
        Text("What to do instead", style="bold"),
        Text(substitution.guidance, style="default"),
    ]
    if detail:
        body[0:0] = [Text(detail, style="bold red"), Text("")]
    if substitution.reference:
        body += [Text(""), Text(substitution.reference, style="dim")]
    return Panel(
        Group(*body),
        title=f"[bold]{substitution.id}[/]",
        subtitle=f"[dim]{substitution.severity.value}[/]",
        border_style="red",
    )


class UnsupportedInWasmError(RuntimeError):
    """Raised in place of a failure whose own message would misdirect.

    Also raised pre-emptively for operations that would otherwise not fail at all - the
    silent class, where there is no exception to improve on because there is no exception.
    """

    def __init__(self, substitution: Substitution, detail: str = "") -> None:
        self.substitution = substitution
        self.detail = detail
        super().__init__(f"{substitution.id}: {substitution.guidance}")

    def __rich__(self) -> RenderableType:
        return _render(self.substitution, self.detail)


class WasmCompatibilityWarning(UserWarning):
    """Warned for operations that still produce the right answer, at a cost worth knowing.

    `run_in_executor` returns what it should; it just does the work on the only thread there
    is. Raising would break correct code, and staying silent is how a page ends up frozen
    for reasons nobody can trace.
    """

    def __init__(self, substitution: Substitution, detail: str = "") -> None:
        self.substitution = substitution
        self.detail = detail
        super().__init__(f"{substitution.id}: {substitution.observed}")

    def __rich__(self) -> RenderableType:
        return _render(self.substitution, self.detail)
