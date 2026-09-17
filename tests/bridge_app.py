"""An app that exercises every direction of the data channel, for the browser harness.

Deliberately not a demo: the example under `examples/page-bridge` is the one written to be
read. This one is written to be *asserted on*, so every observable is a literal string on
the grid and every channel does one thing.

* `gain` is bound to a reactive, which is the round trip an application actually writes.
* `echo` is the raw pipe: whatever text arrives goes back out on `echo-back` unchanged, so
  the harness can prove the transport is not reinterpreting a payload on the way through.
* pressing `u` changes the reactive from the application side, which is the direction a
  page cannot fake by echoing its own message.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.reactive import reactive
from textual.widgets import Static

from textual_wasm.bridge import Bridge, BridgeMessage

GAIN_CHANNEL: str = "gain"
ECHO_CHANNEL: str = "echo"
ECHO_REPLY_CHANNEL: str = "echo-back"


class BridgeApp(App[None]):
    """One reactive, one echo, and a line of text saying what the channel has done."""

    BINDINGS: ClassVar[list[BindingType]] = [("u", "bump", "Bump")]

    gain: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static("ready", id="state")
        yield Static("gain=0", id="gain")

    def on_mount(self) -> None:
        self.bridge = Bridge.connect(self)
        self.bridge.bind(GAIN_CHANNEL, self, "gain")
        self.query_one("#state", Static).update(f"ready available={self.bridge.available}")

    def watch_gain(self, value: int) -> None:
        # Queried rather than asserted: a reactive fires before `compose` has mounted
        # anything, and `query_one` on an empty tree raises rather than returning None.
        for label in self.query("#gain").results(Static):
            label.update(f"gain={value}")

    def on_bridge_message(self, message: BridgeMessage) -> None:
        """Bounce the raw text back, which is the pipe with nothing built on it."""
        if message.channel == ECHO_CHANNEL:
            self.bridge.send_text(ECHO_REPLY_CHANNEL, message.text)

    def action_bump(self) -> None:
        self.gain += 10
