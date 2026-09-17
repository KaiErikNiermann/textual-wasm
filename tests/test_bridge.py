"""The data channel, and the contract it shares with the page at the other end of it.

Everything here runs natively, which is the interesting constraint and the same one
`test_storage` works under: the browser half cannot be exercised from pytest. What *is*
testable without a browser turns out to be almost all of it, because the module was written
so that the page is an object with two methods - so a fake one is four lines, and the
message pump, the codec, the bindings and the echo guard are all reachable through it.

The two things a fake cannot prove - that the shipped page satisfies the contract, and that
it does so identically in a worker - are pinned here as string-drift assertions and measured
for real in `test_bridge_browser.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from textual_wasm import bridge
from textual_wasm.bridge import BRIDGE_MODULE, Bridge, BridgeMessage, JsonCodec

if TYPE_CHECKING:
    from collections.abc import Callable

BOOT_ASSET: Final[Path] = Path(bridge.__file__).parent / "assets" / "boot.mjs"
MAIN_ASSET: Final[Path] = Path(bridge.__file__).parent / "assets" / "main.mjs"
WORKER_ASSET: Final[Path] = Path(bridge.__file__).parent / "assets" / "worker.mjs"


class FakePage:
    """A page, in four lines, because the contract is two methods.

    `sent` is what the application put on the wire - raw text, never a decoded value, so a
    test asserting on it is asserting about the thing that actually crosses.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._receive: Callable[[str, str], None] | None = None

    def send(self, channel: str, text: str) -> None:
        self.sent.append((channel, text))

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        self._receive = callback

    def deliver(self, channel: str, text: str) -> None:
        """Stand in for the page sending to the application."""
        assert self._receive is not None, "the bridge never subscribed"
        self._receive(channel, text)


class Mixer(App[None]):
    """An app with one reactive to bind and a record of what arrived."""

    gain: reactive[int] = reactive(0)

    def __init__(self) -> None:
        super().__init__()
        self.received: list[BridgeMessage] = []

    def compose(self) -> ComposeResult:
        yield Static("mixer", id="state")

    def on_bridge_message(self, message: BridgeMessage) -> None:
        self.received.append(message)


@pytest.fixture
def page() -> FakePage:
    return FakePage()


# --- the pipe ---------------------------------------------------------------


def test_text_goes_out_exactly_as_written(page: FakePage) -> None:
    """`send_text` is the layer with no opinion, so anything that is not a round trip here
    is this module inserting itself into a protocol it was asked to stay out of."""
    Bridge(Mixer(), host=page).send_text("raw", "\x00not json at all\x1b[31m")
    assert page.sent == [("raw", "\x00not json at all\x1b[31m")]


def test_a_terminal_run_has_no_page_and_sends_nowhere() -> None:
    """The property that keeps a runtime branch out of application code: an app written
    against the bridge runs in a terminal, and finds out by asking rather than by catching."""
    channel = Bridge(Mixer())
    assert not channel.available
    channel.send("levels", {"gain": 3})  # must not raise


def test_a_value_the_codec_cannot_render_fails_without_a_page() -> None:
    """Encoding happens whether or not anyone is listening, which costs a `json.dumps` on a
    terminal and buys the thing worth having: a bad payload fails in every runtime rather
    than only in a browser, where nobody is looking at the console."""
    with pytest.raises(TypeError):
        Bridge(Mixer()).send("levels", object())


def test_connect_without_a_registered_module_yields_an_unavailable_bridge() -> None:
    """`connect` is the discovery path `__init__` deliberately does not take."""
    assert not Bridge.connect(Mixer()).available


# --- the codec --------------------------------------------------------------


def test_send_encodes_with_the_codec(page: FakePage) -> None:
    Bridge(Mixer(), host=page).send("levels", {"gain": 3, "muted": False})
    channel, text = page.sent[0]
    assert channel == "levels"
    assert json.loads(text) == {"gain": 3, "muted": False}


def test_a_replacement_codec_is_used_for_both_directions(page: FakePage) -> None:
    """The extension point, exercised rather than described: a codec is two methods, and
    swapping it must not require touching anything else."""

    class Reversed:
        def encode(self, value: object) -> str:
            return str(value)[::-1]

        def decode(self, text: str) -> object:
            return text[::-1]

    channel = Bridge(Mixer(), codec=Reversed(), host=page)
    channel.send("odd", "abc")
    assert page.sent == [("odd", "cba")]
    assert BridgeMessage("odd", "cba", Reversed()).data == "abc"


def test_a_message_keeps_the_raw_text_alongside_the_decoded_value() -> None:
    message = BridgeMessage("levels", '{"gain": 3}', JsonCodec())
    assert message.text == '{"gain": 3}'
    assert message.data == {"gain": 3}


def test_decoding_happens_once() -> None:
    """A handler reading `data` twice must not pay for it twice, and a codec with side
    effects must not see two calls."""
    calls = 0

    class Counting:
        def encode(self, value: object) -> str:
            return json.dumps(value)

        def decode(self, text: str) -> object:
            nonlocal calls
            calls += 1
            return json.loads(text)

    message = BridgeMessage("levels", "null", Counting())
    assert message.data is None
    assert message.data is None
    assert calls == 1, "a payload that decodes to None was decoded twice"


def test_a_malformed_payload_raises_where_it_is_read_rather_than_where_it_arrives() -> None:
    """The pipe does not pretend bad text is an empty value. `text` survives either way, so
    a handler that wants to recover has something to recover from."""
    message = BridgeMessage("levels", "{not json", JsonCodec())
    assert message.text == "{not json"
    with pytest.raises(json.JSONDecodeError):
        _ = message.data


# --- delivery into the app --------------------------------------------------


async def test_an_inbound_payload_arrives_as_a_message(page: FakePage) -> None:
    app = Mixer()
    async with app.run_test() as pilot:
        Bridge(app, host=page)
        page.deliver("levels", '{"gain": 7}')
        await pilot.pause()

    assert [(m.channel, m.data) for m in app.received] == [("levels", {"gain": 7})]


async def test_a_bound_channel_still_posts_its_message(page: FakePage) -> None:
    """Binding is a convenience, not an interception: an app may want the value applied
    *and* to react to its arrival, and having to choose would be a reason not to use bind."""
    app = Mixer()
    async with app.run_test() as pilot:
        Bridge(app, host=page).bind("gain", app, "gain")
        page.deliver("gain", "4")
        await pilot.pause()

    assert app.gain == 4
    assert [m.channel for m in app.received] == ["gain"]


# --- bind -------------------------------------------------------------------


async def test_bind_sends_the_current_value_immediately(page: FakePage) -> None:
    """A page that loads against a running app has to start in step, and the only value it
    can start from is the one the app already holds."""
    app = Mixer()
    app.gain = 5
    async with app.run_test() as pilot:
        Bridge(app, host=page).bind("gain", app, "gain")
        await pilot.pause()

    assert ("gain", "5") in page.sent


async def test_bind_does_not_send_an_initial_value_when_asked_not_to(page: FakePage) -> None:
    app = Mixer()
    async with app.run_test() as pilot:
        Bridge(app, host=page).bind("gain", app, "gain", initial=False)
        await pilot.pause()

    assert page.sent == []


async def test_a_change_in_the_app_reaches_the_page(page: FakePage) -> None:
    app = Mixer()
    async with app.run_test() as pilot:
        Bridge(app, host=page).bind("gain", app, "gain", initial=False)
        app.gain = 9
        await pilot.pause()

    assert page.sent == [("gain", "9")]


async def test_an_applied_value_is_not_echoed_back(page: FakePage) -> None:
    """The echo guard, which is the only non-obvious part of `bind`. Without it the page
    sends 9, the assignment fires the watcher, and 9 goes straight back to the page that
    just sent it - a loop that happens to terminate and is still wrong."""
    app = Mixer()
    async with app.run_test() as pilot:
        Bridge(app, host=page).bind("gain", app, "gain", initial=False)
        page.deliver("gain", "9")
        await pilot.pause()

    assert app.gain == 9
    assert page.sent == [], f"the applied value was echoed: {page.sent}"


async def test_a_binding_survives_a_payload_it_cannot_apply(page: FakePage) -> None:
    """Called from JavaScript, so an exception here lands in a console nobody reads. The
    binding is skipped, the message is still posted, and the next good value still applies."""
    app = Mixer()
    async with app.run_test() as pilot:
        Bridge(app, host=page).bind("gain", app, "gain", initial=False)
        page.deliver("gain", "{not json")
        await pilot.pause()
        page.deliver("gain", "3")
        await pilot.pause()

    assert app.gain == 3
    assert [m.text for m in app.received] == ["{not json", "3"]


async def test_a_round_trip_through_a_widget_reactive(page: FakePage) -> None:
    """Bindings take a `DOMNode` rather than the app, so a widget can own its own channel
    without routing every value through the application object."""

    class Meter(Static):
        level: reactive[int] = reactive(0)

    class Host(App[None]):
        def compose(self) -> ComposeResult:
            yield Meter(id="meter")

    app = Host()
    async with app.run_test() as pilot:
        meter = app.query_one("#meter", Meter)
        Bridge(app, host=page).bind("level", meter, "level", initial=False)
        page.deliver("level", "12")
        await pilot.pause()
        assert meter.level == 12

        meter.level = 30
        await pilot.pause()

    assert page.sent == [("level", "30")]


# --- lifecycle --------------------------------------------------------------


def test_close_is_safe_without_a_proxy_to_release(page: FakePage) -> None:
    """There is no `create_proxy` outside Pyodide, so `close` has nothing to destroy and
    must still work - this is the path every native test exits through."""
    channel = Bridge(Mixer(), host=page)
    channel.close()
    channel.close()


# --- the contract with the page ---------------------------------------------


def test_the_page_and_python_agree_on_the_module_name() -> None:
    """One string, two languages. If they drift nothing raises: the import in `_host` fails,
    `available` reads False, and every message an application sends vanishes into a build
    that looks like it is working."""
    source = BOOT_ASSET.read_text(encoding="utf-8")
    declared = re.search(r'BRIDGE_MODULE = "([^"]+)"', source)
    assert declared is not None, "boot.mjs no longer declares BRIDGE_MODULE"
    assert declared.group(1) == BRIDGE_MODULE


def test_the_page_registers_the_channel_before_the_app_starts() -> None:
    """Ordering that is invisible when it breaks: the entry module imports the driver and
    the application connects during `on_mount`, so a channel registered afterwards would be
    absent exactly when an app looks for it."""
    source = BOOT_ASSET.read_text(encoding="utf-8")
    assert source.index("registerJsModule(BRIDGE_MODULE") < source.index("runPythonAsync")


@pytest.mark.parametrize("asset", [MAIN_ASSET, WORKER_ASSET])
def test_both_transports_implement_the_same_two_members(asset: Path) -> None:
    """`BridgeHost` is two methods, and a transport that implements one of them is a
    transport that fails in one direction only - the hardest kind of failure to see."""
    source = asset.read_text(encoding="utf-8")
    assert "send" in source
    assert "subscribe: (callback)" in source


def test_the_worker_protocol_carries_the_channel_in_both_directions() -> None:
    """The worker's message vocabulary is documented in its own header, and a type that is
    handled but undocumented is how the next person learns the contract is unreliable."""
    source = WORKER_ASSET.read_text(encoding="utf-8")
    assert source.count('{type:"bridge", channel, text}') == 2, "the header lost a direction"
    assert 'case "bridge"' in source
    assert 'postMessage({ type: "bridge", channel, text })' in source
