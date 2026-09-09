"""An app with no probe instrumentation at all, for checking that none is needed.

Deliberately the least a Textual app can be: one widget, no bindings, no timer, no markers
and no knowledge that this project exists. If the probe can measure this, it can measure
someone else's application.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static


class BareApp(App[None]):
    """One static widget and nothing else."""

    def compose(self) -> ComposeResult:
        yield Static("bare")
