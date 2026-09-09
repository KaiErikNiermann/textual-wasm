"""A Textual app designed to be embedded in a page, and driven from outside it.

The app itself knows nothing about that. It has three panels and number-key bindings to
switch between them, which is an ordinary Textual thing to do - and because the page can feed
those same keystrokes through `globalThis.textualWasm.input()`, buttons in the surrounding
HTML drive the app without it exposing an API to JavaScript at all.

That is the embedding story in one sentence: the seam is the keyboard, which every terminal
app already has.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, Static

PANELS: Final[tuple[tuple[str, str], ...]] = (
    (
        "Overview",
        "A Textual app, compiled to nothing.\n\n"
        "This is CPython running in your browser through WebAssembly. There is no server\n"
        "and no JavaScript reimplementation of Textual - the same source runs in a terminal.",
    ),
    (
        "Rendering",
        "Every cell you see was produced by Textual's compositor as an ANSI stream and\n"
        "executed by xterm.js.\n\n"
        "Box drawing:  ─ │ ┌ ┐ └ ┘ ├ ┤\n"
        "Wide glyphs:  世界 日本語\n"
        "Emoji:        \U0001f680 \U0001f469‍\U0001f4bb ⚠️",
    ),
    (
        "Control",
        "The buttons beside this terminal are ordinary HTML.\n\n"
        'They call `globalThis.textualWasm.input("1")`, which is xterm\'s own\n'
        "user-input entry point - so the app receives a keystroke and cannot tell the\n"
        "difference between a button and a keyboard.",
    ),
)
"""Panel titles and bodies. Static text, so the page renders the same on every visit."""

TITLE: Final[str] = "textual-wasm"


class Dashboard(App[None]):
    """Three panels, switched with the number keys."""

    CSS_PATH = "app.tcss"
    TITLE = TITLE

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(str(index + 1), f"show({index})", title, priority=True)
        for index, (title, _body) in enumerate(PANELS)
    ]

    panel: reactive[int] = reactive(0)
    """Which panel is showing. A reactive, so `watch_panel` redraws on any change."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield Label(id="panel-title")
            yield Static(id="panel-body")
        yield Footer()

    def on_mount(self) -> None:
        self._render_panel()

    def action_show(self, index: int) -> None:
        self.panel = index

    def watch_panel(self) -> None:
        if self.is_running:
            self._render_panel()

    def _render_panel(self) -> None:
        title, body = PANELS[self.panel]
        self.query_one("#panel-title", Label).update(f"[b]{title}[/]")
        self.query_one("#panel-body", Static).update(body)


def main() -> None:
    """Run the app in a terminal. The `dashboard-app` console script."""
    Dashboard().run()
