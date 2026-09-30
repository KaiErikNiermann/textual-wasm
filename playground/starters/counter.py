"""A counter. Edit anything, then press Run (or Ctrl+Enter)."""

from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal
from textual.reactive import reactive
from textual.widgets import Button, Digits, Footer, Header


class Counter(App[None]):
    CSS = """
    Screen { align: center middle; }
    Digits { width: auto; margin: 1 0; }
    Horizontal { width: auto; height: auto; }
    Button { margin: 0 1; }
    """

    BINDINGS = [("up", "change(1)", "More"), ("down", "change(-1)", "Less")]

    count = reactive(0)

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            yield Digits("0")
        with Center(), Horizontal():
            yield Button("-1", id="less", variant="error")
            yield Button("+1", id="more", variant="success")
        yield Footer()

    def watch_count(self, count: int) -> None:
        self.query_one(Digits).update(str(count))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_change(1 if event.button.id == "more" else -1)

    def action_change(self, by: int) -> None:
        self.count += by


if __name__ == "__main__":
    Counter().run()
