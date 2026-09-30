"""A to-do list: type, press Enter, and tick items off with Space."""

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Input, SelectionList


class Todo(App[None]):
    TITLE = "To do"
    CSS = """
    Input { margin: 1 1 0 1; }
    SelectionList { margin: 1; height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="Something to do, then Enter")
        yield SelectionList[str](("Try the playground", "first"))
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if text := event.value.strip():
            items = self.query_one(SelectionList)
            items.add_option((text, f"item-{items.option_count}"))
        event.input.clear()


if __name__ == "__main__":
    Todo().run()
