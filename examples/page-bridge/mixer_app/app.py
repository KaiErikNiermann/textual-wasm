"""A mixer whose levels are shared with the page around it, both ways.

The point of this example is the thing a keystroke cannot do. `examples/embedded-page` drives
an application from a page by sending it the key it is already listening for, which is the
right answer for a button meaning "press 2" and no answer at all for a slider: there is no
keyboard spelling of "gain is now 63", and no keystroke the application can send *back* when
it changes a level itself.

So the levels live on a channel. Three reactives are bound to three channels with
`Bridge.bind`, and from then on neither side is the owner: a page slider moves the meter, the
keyboard moves the slider, and the initial values come from whichever of the two started
first - which is always the application, because the page cannot subscribe until it exists.

The `clipping` channel shows the other half, the half with no page control behind it. Nothing
on the page can set it. It is the application telling the page something the page had no way
to ask about, which before the bridge could only be done by scraping the rendered grid.

Everything here also runs in a terminal, unchanged and with no branch: `Bridge.connect` on a
runtime with no page returns a bridge whose `available` is False, whose sends go nowhere, and
whose bindings simply never receive. That is the property that keeps this an ordinary Textual
app rather than a web app that happens to be written in Python.
"""

from __future__ import annotations

from typing import ClassVar, Final, cast

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, ProgressBar, Static
from textual_wasm.bridge import Bridge, BridgeMessage

from mixer_app.channels import CLIPPING, LEVELS, NOTE, Clipping, LevelName

CLIP_AT: Final[int] = 85
"""Where the mixer calls a level too hot. Arbitrary, and the arbitrariness is the point: it
is a decision the application makes and the page has no way to compute for itself."""

STEP: Final[int] = 5


class Meter(Static):
    """One level, as a bar and a number."""

    level: reactive[int] = reactive(0)

    def __init__(self, name: str) -> None:
        super().__init__(id=f"meter-{name}")
        self.level_name = name

    def compose(self) -> ComposeResult:
        yield Label(self._caption(), classes="meter-name")
        yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="bar")

    def watch_level(self, value: int) -> None:
        # Queried rather than held: a reactive fires before `compose` has mounted anything,
        # and `query_one` on an empty tree raises rather than returning None.
        for bar in self.query("#bar").results(ProgressBar):
            bar.update(progress=value)
        for label in self.query(".meter-name").results(Label):
            label.update(self._caption())
        self.set_class(value >= CLIP_AT, "hot")

    def _caption(self) -> str:
        """The number beside the name, because a bar alone cannot be compared to a slider."""
        return f"{self.level_name} {self.level}"


class Mixer(App[None]):
    """Three levels, a selection, and a channel to the page for each of them."""

    CSS_PATH = "app.tcss"
    TITLE = "Mixer"

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up,k", "adjust(1)", "Louder"),
        ("down,j", "adjust(-1)", "Quieter"),
        # Not `tab`: Textual spends that one on focus navigation, and rebinding a key the
        # framework owns is a fight this example has no reason to pick.
        ("right,l", "select(1)", "Next level"),
        ("left,h", "select(-1)", "Previous level"),
    ]

    gain: reactive[int] = reactive(40)
    bass: reactive[int] = reactive(30)
    treble: reactive[int] = reactive(55)
    selected: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="panel"):
            with Horizontal(id="meters"):
                for channel in LEVELS:
                    yield Meter(channel.name)
            yield Static("", id="note")
            yield Static("", id="link")
        yield Footer()

    def on_mount(self) -> None:
        self.bridge = Bridge.connect(self)
        for channel in LEVELS:
            # One line per shared value, and the same line whether the page is driving it or
            # the keyboard is. Sending the current value immediately is what lets a page that
            # loads against a running app start in step rather than at whatever its markup
            # happened to declare.
            self.bridge.bind(channel.name, self, channel.name)
        self.query_one("#link", Static).update(
            "page connected" if self.bridge.available else "no page: running in a terminal"
        )
        self._refresh_meters()
        self._report_clipping()

    def watch_gain(self, value: int) -> None:
        self._on_level_changed("gain", value)

    def watch_bass(self, value: int) -> None:
        self._on_level_changed("bass", value)

    def watch_treble(self, value: int) -> None:
        self._on_level_changed("treble", value)

    def watch_selected(self) -> None:
        self._refresh_meters()

    def on_bridge_message(self, message: BridgeMessage) -> None:
        """Everything the page sends arrives here, bound channels included.

        The bound levels have already been applied by the time this runs - binding a channel
        does not consume it - so this only has to deal with the one channel that has no
        binding behind it.
        """
        if NOTE.matches(message):
            # `text` rather than `data`: the page is sending a line of prose, and running it
            # through a JSON decoder would be ceremony around a string.
            self.query_one("#note", Static).update(message.text)

    def action_adjust(self, direction: int) -> None:
        """Move the selected level, which is the direction a page cannot fake.

        The page hears about this because the level is bound, and it hears about it without
        having asked - no polling, and nothing scraping the rendered grid.
        """
        name = LEVELS[self.selected].name
        setattr(self, name, max(0, min(100, int(getattr(self, name)) + direction * STEP)))

    def action_select(self, direction: int) -> None:
        self.selected = (self.selected + direction) % len(LEVELS)

    def _on_level_changed(self, name: str, value: int) -> None:
        for meter in self.query(f"#meter-{name}").results(Meter):
            meter.level = value
        self._report_clipping()

    def _refresh_meters(self) -> None:
        for index, channel in enumerate(LEVELS):
            for meter in self.query(f"#meter-{channel.name}").results(Meter):
                meter.set_class(index == self.selected, "selected")
                meter.level = int(getattr(self, channel.name))

    def _report_clipping(self) -> None:
        """Tell the page which levels are too hot.

        Sent unconditionally rather than only on a change: the receiving side is a page that
        may have loaded at any moment, and a channel carrying current state is easier to
        reason about than one carrying edges. `Bridge.send` on a terminal encodes and drops,
        which is why this needs no `if self.bridge.available` around it.
        """
        hot: list[LevelName] = [
            cast("LevelName", channel.name)
            for channel in LEVELS
            if int(getattr(self, channel.name)) >= CLIP_AT
        ]
        report: Clipping = {"threshold": CLIP_AT, "hot": hot}
        # Through the channel rather than the bridge, so the payload is checked against the
        # same declaration the page's `.d.ts` was generated from.
        CLIPPING.send(self.bridge, report)


def main() -> None:
    Mixer().run()
