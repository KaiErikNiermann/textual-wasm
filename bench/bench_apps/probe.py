"""The application the benchmarks talk to: a static screen with a data channel behind it.

Static on purpose. With nothing animating, anything it costs while idle is the cost of
being hosted, which is the number the idle benchmark wants; and every busy workload is
started by a message, so the benchmark decides exactly when work happens.

The channels split into two kinds. `echo` and `flood` are the hot paths, kept to a single
comparison and a send so that their cost is the channel's and not this file's. Everything
else is a JSON command on `bench`, answered on `bench-reply` - slower, and only ever used
between measurements or for workloads that time themselves from inside Python.

The commands that time themselves (`self-flood`, `spin`, `churn`) are the controls. Each is
a method that also runs natively under `App.run_test`, so the same code is measured on
CPython and on Pyodide and the ratio says how much of a browser number is the interpreter.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from typing import ClassVar, Final, cast

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static

from bench_apps.runtime import interpreter_memory, spin
from textual_wasm.bridge import Bridge, BridgeHost, BridgeMessage

ECHO: Final[str] = "echo"
ECHO_REPLY: Final[str] = "echo-back"
FLOOD: Final[str] = "flood"
FLOOD_END: Final[str] = "flood-end"
FLOOD_REPLY: Final[str] = "flood-done"
COMMAND: Final[str] = "bench"
COMMAND_REPLY: Final[str] = "bench-reply"

READY_TEXT: Final[str] = "bench ready"
"""On the grid once the app has mounted. The harness waits for it before measuring."""


class Tick(Message):
    """A message the application posts to itself, for timing Textual's message pump alone."""


@dataclasses.dataclass(slots=True)
class _SelfFlood:
    """The state of one self-flood: how many ticks are still to arrive, and who is waiting."""

    remaining: int
    done: asyncio.Event


class BenchProbe(App[None]):
    """Labels, a container to churn widgets in, and the channel handlers."""

    BINDINGS: ClassVar[list[BindingType]] = []

    def __init__(self, host: BridgeHost | None = None) -> None:
        """Create the app, optionally against a host other than the page's.

        Args:
            host: A channel to use instead of the page's. The native control passes one, so
                that the same handlers run under CPython with the browser taken out.
        """
        super().__init__()
        self.flood_count = 0
        self._self_flood: _SelfFlood | None = None
        self._host = host
        self.bridge: Bridge | None = None

    def compose(self) -> ComposeResult:
        yield Static(READY_TEXT, id="state")
        yield Static("flood=0", id="flood")
        yield Vertical(id="churn")

    def on_mount(self) -> None:
        self.bridge = Bridge.connect(self) if self._host is None else Bridge(self, host=self._host)

    # --- workloads, shared by the browser run and the native control ------------------

    async def self_flood(self, count: int) -> float:
        """Post `count` messages to this app and wait for the last; return milliseconds.

        The control for the channel's throughput ceiling. Each tick is a Textual message
        through the same queue a `BridgeMessage` travels, but nothing crosses from the page,
        so the difference between this and a flood of `count` page messages is what the
        channel itself costs.
        """
        flood = _SelfFlood(remaining=count, done=asyncio.Event())
        self._self_flood = flood
        started = time.perf_counter()
        for _ in range(count):
            self.post_message(Tick())
        await flood.done.wait()
        self._self_flood = None
        return (time.perf_counter() - started) * 1000

    def on_tick(self, _message: Tick) -> None:
        flood = self._self_flood
        if flood is None:
            return
        flood.remaining -= 1
        if flood.remaining == 0:
            flood.done.set()

    async def churn(self, widgets: int) -> float:
        """Mount `widgets` labels, then remove them all; return milliseconds.

        The UI-side leak workload: if mounting and removing leaves anything behind - a
        reference in a style cache, a timer, a node the compositor kept - repeating it grows
        the object count, and the browser has nothing to do with that.
        """
        container = self.query_one("#churn", Vertical)
        started = time.perf_counter()
        await container.mount_all(Static(f"row {index}") for index in range(widgets))
        await container.remove_children()
        return (time.perf_counter() - started) * 1000

    @staticmethod
    def spin(iterations: int) -> float:
        """Run the pure-arithmetic loop; return milliseconds. The interpreter-speed control."""
        started = time.perf_counter()
        spin(iterations)
        return (time.perf_counter() - started) * 1000

    # --- the channel --------------------------------------------------------------------

    def on_bridge_message(self, message: BridgeMessage) -> None:
        """Dispatch, with the hot paths first and cheapest.

        Commands run in a worker rather than being awaited here. A handler that awaits holds
        the app's message queue, and `self-flood` and `churn` wait on messages that queue
        behind it - awaited in place, both deadlock.
        """
        bridge = self.bridge
        if bridge is None:
            return
        if message.channel == FLOOD:
            self.flood_count += 1
        elif message.channel == ECHO:
            bridge.send_text(ECHO_REPLY, message.text)
        elif message.channel == FLOOD_END:
            bridge.send_text(FLOOD_REPLY, str(self.flood_count))
            self.query_one("#flood", Static).update(f"flood={self.flood_count}")
            self.flood_count = 0
        elif message.channel == COMMAND:
            self.run_worker(self._answer(bridge, message.text), exclusive=False)

    async def _answer(self, bridge: Bridge, text: str) -> None:
        bridge.send_text(COMMAND_REPLY, json.dumps(await self._command(text)))

    async def _command(self, text: str) -> dict[str, object]:
        """Run one JSON command and describe the result."""
        request = cast("dict[str, object]", json.loads(text))
        operation = request.get("op")
        count = request.get("n", 0)
        size = count if isinstance(count, int) else 0
        match operation:
            case "stats":
                return {"op": operation, **dataclasses.asdict(interpreter_memory())}
            case "self-flood":
                return {"op": operation, "ms": await self.self_flood(size)}
            case "churn":
                return {"op": operation, "ms": await self.churn(size)}
            case "spin":
                return {"op": operation, "ms": self.spin(size)}
            case _:
                return {"op": operation, "error": "unknown command"}
