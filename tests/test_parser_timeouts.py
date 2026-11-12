"""The parser's escape timeout: resolved after input, and costing nothing without it.

A lone `Escape` is ambiguous until `ESCDELAY` has passed with nothing after it - it might be
the start of a CSI sequence. The native drivers resolve it with a `select` timeout; this
driver has no blocking read, so it ticks the parser on a timer. That timer used to run for
the app's whole life, and was the entire idle CPU cost of a static app in a browser. It now
runs only for a short window after input, and these are the two halves of that contract.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual import constants, events
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.pilot import Pilot
from textual.widgets import Static

from textual_wasm.driver import CaptureDriver, active_capture


class KeyRecorder(App[None]):
    """Records every key it is sent, and nothing else."""

    BINDINGS: ClassVar[list[BindingType]] = []

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("keys")

    def on_key(self, event: events.Key) -> None:
        self.keys.append(event.key)


def _driver() -> CaptureDriver:
    driver = active_capture()
    assert isinstance(driver, CaptureDriver)
    return driver


async def test_a_lone_escape_resolves_and_the_timer_then_stops() -> None:
    app = KeyRecorder()
    observed: dict[str, object] = {}

    async def drive(pilot: Pilot[object]) -> None:
        driver = _driver()
        observed["idle_timer"] = driver.parser_timer_running
        driver.feed_input("\x1b")
        # The parser holds the byte for ESCDELAY, then the next tick releases it.
        await asyncio.sleep(constants.ESCAPE_DELAY * 3)
        observed["keys"] = list(app.keys)
        await asyncio.sleep(constants.ESCAPE_DELAY * 3)
        observed["timer_after_window"] = driver.parser_timer_running
        pilot.app.exit()

    await app.run_async(size=(40, 10), auto_pilot=drive)

    assert observed["idle_timer"] is False, "an app nobody typed into has a timer running"
    assert observed["keys"] == ["escape"]
    assert observed["timer_after_window"] is False, "the timer outlived its window"


async def test_a_sequence_is_still_one_key() -> None:
    """Ticking less often must not split a sequence that arrives in one piece."""
    app = KeyRecorder()

    async def drive(pilot: Pilot[object]) -> None:
        _driver().feed_input("\x1b[A")
        await asyncio.sleep(constants.ESCAPE_DELAY * 3)
        pilot.app.exit()

    await app.run_async(size=(40, 10), auto_pilot=drive)

    assert app.keys == ["up"]
