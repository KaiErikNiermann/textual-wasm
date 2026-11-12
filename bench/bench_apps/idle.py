"""An application whose only activity while idle is a blinking cursor.

The probe app is the floor: nothing on it changes, so whatever it costs is hosting. This
is the common case above the floor. A focused `Input` blinks its cursor on a timer, which
redraws part of the screen twice a second, and most real applications have one.
"""

from __future__ import annotations

from typing import Final

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

READY_TEXT: Final[str] = "idle ready"


class BlinkingInput(App[None]):
    """A label and a focused input, and nothing else."""

    def compose(self) -> ComposeResult:
        yield Static(READY_TEXT)
        yield Input(placeholder="type here")

    def on_mount(self) -> None:
        self.query_one(Input).focus()
