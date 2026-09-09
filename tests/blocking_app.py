"""An app that deliberately blocks the interpreter, for measuring what a worker buys.

The claim worker mode makes is not "Python gets faster" - it does not - but "a slow call
stops freezing the page". Demonstrating that needs an app with a call slow enough to see,
and a busy loop rather than `time.sleep` because `textual_wasm.diagnostics` intercepts sleep
precisely for blocking the only thread there is.

Pressing `b` runs it. The work is pure arithmetic so the duration is set by the interpreter
rather than by anything the host does, which is what makes the two modes comparable.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.widgets import Static

ITERATIONS: int = 30_000_000
"""Sized so the block is unmistakable rather than marginal: about a second under Pyodide,
against a 16.7ms frame budget. The measurement compares the longest interval between two
animation frames, so what matters is that the block is far longer than one frame, not that
it is any particular duration."""


class BlockingApp(App[None]):
    """One label, and a key that stops the interpreter answering for about a second."""

    BINDINGS: ClassVar[list[BindingType]] = [("b", "block", "Block")]

    def compose(self) -> ComposeResult:
        yield Static("ready", id="state")

    def action_block(self) -> None:
        """Burn CPU synchronously, which is the entire point of this fixture."""
        total = 0
        for index in range(ITERATIONS):
            total += index * index
        self.query_one("#state", Static).update(f"blocked {total % 1000}")
