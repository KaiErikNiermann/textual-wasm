"""The minimal Textual application the probe drives.

Deliberately tiny, and deliberately ordinary: it uses nothing a WASM host has to special-case,
so that any failure the probe reports is a failure of the *runtime*, not of the app.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Resize
from textual.geometry import Size
from textual.widgets import Label, Static

MARKER: Final[str] = "TEXTUAL-WASM-SPIKE"
"""Text the probe looks for in the captured stream to prove the compositor ran."""

EXIT_CODE: Final[int] = 7
"""Arbitrary non-zero, non-default value, so `run_async` returning it cannot be a coincidence."""

TIMER_DELAY: Final[float] = 0.05
"""Short enough to keep the probe quick, long enough to be a real `call_later` round trip."""


class SpikeApp(App[int]):
    """A one-widget app with a keybinding and a timer — the three things a host must support."""

    CSS = """
    Screen { align: center middle; }
    #marker { color: $success; border: round $accent; padding: 1 2; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # `priority` so the binding fires from the app regardless of what holds focus; the
        # probe is testing the input path, not Textual's focus resolution.
        Binding("a", "bump", "Bump the counter", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.bump_count: int = 0
        """Incremented by the `a` binding, i.e. by bytes that went through `XTermParser`."""

        self.timer_fired: bool = False
        """Set by `set_timer`, i.e. by the host event loop's timer implementation."""

        self.observed_size: Size | None = None
        """The size carried by the `Resize` the driver synthesised."""

    def compose(self) -> ComposeResult:
        yield Label(MARKER, id="marker")
        yield Static("press 'a'", id="hint")

    def on_mount(self) -> None:
        self.set_timer(TIMER_DELAY, self._mark_timer_fired)

    def on_resize(self, event: Resize) -> None:
        self.observed_size = event.size

    def action_bump(self) -> None:
        self.bump_count += 1

    def _mark_timer_fired(self) -> None:
        self.timer_fired = True
