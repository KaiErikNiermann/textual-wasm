"""An app that reports what the channel did to it, for the error-handling browser tests.

Every hostile input the page sends has an observable consequence here, published back on
`report` so a harness can assert on it without reading the rendered grid. The grid is used
for one thing only: proving the application is still running and drawing after each case,
which is the claim that matters most and the one a message cannot make on its own.
"""

from __future__ import annotations

import math
from typing import Any

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from textual_wasm.bridge import Bridge, BridgeMessage, BridgePayloadError

REPORT: str = "report"
"""Everything this app tells the harness goes out on one channel, so the harness has one
listener and the ordering between observations is the order they happened."""


class ErrorApp(App[None]):
    """Two bound reactives - one validated, one not - and a running tally."""

    loose: reactive[int] = reactive(0)
    strict: reactive[int] = reactive(0)

    def __init__(self) -> None:
        super().__init__()
        self.seen = 0

    def compose(self) -> ComposeResult:
        yield Static("errors ready", id="state")
        yield Static("loose=0 strict=0", id="values")

    def on_mount(self) -> None:
        self.bridge = Bridge.connect(self)
        # Deliberately unvalidated: the page can change what type this holds, and the
        # browser test asserts that the application survives it rather than that it is
        # prevented. `strict` is the same channel shape with the fix applied.
        self.bridge.bind("loose", self, "loose", initial=False)
        self.bridge.bind("strict", self, "strict", initial=False, validate=int)

    def watch_loose(self, value: object) -> None:
        self._render(loose=value)

    def watch_strict(self, value: object) -> None:
        self._render(strict=value)

    def _render(self, **_changed: object) -> None:
        for label in self.query("#values").results(Static):
            label.update(f"loose={self.loose!r} strict={self.strict!r}")

    def on_bridge_message(self, message: BridgeMessage) -> None:
        self.seen += 1
        handler = getattr(self, f"_on_{message.channel.replace('-', '_')}", None)
        if handler is not None:
            handler(message)

    def _on_probe(self, _message: BridgeMessage) -> None:
        """Say what the application currently believes, so the harness can compare."""
        self.bridge.send(
            REPORT,
            {
                "kind": "state",
                "loose": repr(self.loose),
                "looseType": type(self.loose).__name__,
                "strict": self.strict,
                "strictType": type(self.strict).__name__,
                "seen": self.seen,
            },
        )

    def _on_decode(self, message: BridgeMessage) -> None:
        """Read `message.data` on purpose, and report what came out or what was raised.

        The interesting half is the error text: in a browser the only diagnostic is a
        console nobody has open, so an error that does not name its channel is useless.
        """
        try:
            value: Any = message.data
        except BridgePayloadError as error:
            self.bridge.send(REPORT, {"kind": "decode", "error": str(error)})
        else:
            self.bridge.send(REPORT, {"kind": "decode", "value": value})

    def _on_send_bad(self, _message: BridgeMessage) -> None:
        """Try to send values JSON cannot carry, and report what stopped it."""
        outcomes: dict[str, str] = {}
        for name, value in (
            ("nan", math.nan),
            ("inf", math.inf),
            ("object", object()),
        ):
            try:
                self.bridge.send("never-arrives", value)
            except BridgePayloadError as error:
                outcomes[name] = str(error)
            else:
                outcomes[name] = "sent, which it should not have been"
        self.bridge.send(REPORT, {"kind": "send-bad", "outcomes": outcomes})

    def _on_echo(self, message: BridgeMessage) -> None:
        """Bounce the raw text, to prove a payload crossed unchanged."""
        self.bridge.send_text("echo-back", message.text)
