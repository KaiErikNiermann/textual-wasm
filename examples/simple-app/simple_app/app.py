"""A small task list, written as an ordinary Textual app.

The point of this example is what is *not* here: no import of `textual_wasm`, no branch on
`sys.platform`, no capability check. This is the app you would write anyway, and shipping it
as a web page is a build step rather than a port.

Two deliberate choices, both so that `textual-wasm check` can compare the runtimes:

* The screen is **deterministic** - no clock, no network, nothing that differs between two
  runs. The check diffs the rendered grid cell by cell, and it cannot tell a font-width bug
  from an app that simply drew something different.
* Every visible change is driven by a keystroke, so a harness can put the app in a known
  state and say when it got there.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label, ListItem, ListView

TITLE = "Tasks"
"""Shown in the header. `textual-wasm check --ready-marker` looks for this."""

TASK_TEMPLATE = "Task {number}"
"""What a new task is called. Fixed rather than timestamped, so two runs draw the same grid."""


class TaskList(App[None]):
    """Add and remove items with the keyboard. Runs in a terminal and in a browser."""

    CSS_PATH = "app.tcss"
    """A separate stylesheet on purpose: `textual-wasm build` ships `.tcss` alongside `.py`,
    and an app whose CSS lived only in a string would not prove that."""

    TITLE = TITLE

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("a", "add", "Add a task"),
        Binding("d", "remove", "Remove the last"),
        Binding("q", "quit", "Quit"),
    ]

    count: reactive[int] = reactive(0)
    """How many tasks have ever been added, so numbering does not repeat after a removal."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield Label("Press [b]a[/] to add a task.", id="hint")
            yield ListView(id="tasks")
        yield Footer()

    def action_add(self) -> None:
        self.count += 1
        self.query_one("#tasks", ListView).append(
            ListItem(Label(TASK_TEMPLATE.format(number=self.count)))
        )

    def action_remove(self) -> None:
        tasks = self.query_one("#tasks", ListView)
        if tasks.children:
            tasks.children[-1].remove()


def main() -> None:
    """Run the app in a terminal. The `simple-app` console script."""
    TaskList().run()
