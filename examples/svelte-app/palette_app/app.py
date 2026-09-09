"""A Textual app whose theme is switched from the Svelte page hosting it.

The interesting part is what the app does *not* have: no JavaScript bridge, no message
protocol, no awareness that a framework is involved. It binds keys to theme changes, the way
any Textual app might, and the Svelte component sends those keys.

The keyboard is the integration surface. Anything a user could do to a terminal app, a page
can do to it too.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, ProgressBar, Sparkline, Static

THEMES: Final[tuple[str, ...]] = ("textual-dark", "nord", "gruvbox", "catppuccin-mocha")
"""A few of Textual's own themes, cycled with the number keys.

Chosen because they repaint every widget on screen, which makes the point that the page is
not restyling anything - Textual is, and the browser is showing the result.
"""

SAMPLE: Final[tuple[int, ...]] = (3, 8, 4, 9, 6, 12, 7, 14, 9, 18, 11, 21, 13, 17, 10, 6)
"""Fixed data. A random series would make the rendered grid differ between runs, and the
cross-runtime check compares grids."""


class Palette(App[None]):
    """A handful of widgets, so a theme change is visible in more than one place."""

    CSS_PATH = "app.tcss"
    TITLE = "Palette"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(str(index + 1), f"use_theme('{name}')", name, priority=True)
        for index, name in enumerate(THEMES)
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield Label("Press [b]1[/]-[b]4[/], or use the buttons beside this terminal.")
            yield Sparkline(list(SAMPLE), summary_function=max, id="chart")
            yield ProgressBar(total=100, show_eta=False, id="progress")
            with Horizontal(id="buttons"):
                yield Button("Primary", variant="primary")
                yield Button("Success", variant="success")
                yield Button("Warning", variant="warning")
            yield Static(id="current")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#progress", ProgressBar).update(progress=64)
        self._show_theme()

    def action_use_theme(self, name: str) -> None:
        self.theme = name
        self._show_theme()

    def _show_theme(self) -> None:
        self.query_one("#current", Static).update(f"theme: {self.theme}")


def main() -> None:
    """Run the app in a terminal. The `palette-app` console script."""
    Palette().run()
