"""Textual CSS: a grid of panels. Try changing grid-size, or a colour."""

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class Panels(App[None]):
    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 2;
        grid-gutter: 1 2;
        padding: 1 2;
    }
    Static {
        height: 100%;
        content-align: center middle;
        border: round $accent;
    }
    #wide { column-span: 2; background: $boost; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("One", id="wide")
        for name in ("Two", "Three", "Four", "Five"):
            yield Static(name)
        yield Footer()


if __name__ == "__main__":
    Panels().run()
