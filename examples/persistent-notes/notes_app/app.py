"""A notebook whose notes survive, in a terminal and in a browser, from one code path.

The whole point of this example is what is *absent*: there is no `if in_browser()` anywhere,
no second storage backend, and no serialisation layer. `textual_wasm.storage.Store` hands
back a directory, `sqlite3` writes to it, and `await store.flush()` is a no-op on a terminal
and the durability point in a browser. Reading this file top to bottom, the only hint that a
browser is involved at all is that `flush` is awaited rather than ignored.

SQLite rather than a JSON file, deliberately. It is the load-bearing claim: a real database,
with a real schema and real queries, inside a page, on the standard library alone. `sqlite3`
is in Pyodide's distribution, and an IDBFS mount makes the file persist.

Two settings matter and are both here rather than in prose:

* `journal_mode=DELETE` - WAL wants shared memory and file locking that Emscripten does not
  provide. Durability here comes from `flush()`, not from the journal.
* `synchronous=OFF` - `fsync` has nothing to sync to under a memory-backed filesystem, so
  paying for it buys latency and no safety.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, ClassVar, Final

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView
from textual_wasm.storage import Store

if TYPE_CHECKING:
    from collections.abc import Sequence

APP_NAME: Final[str] = "persistent-notes"
"""Becomes a directory name on both runtimes, so a slug rather than a title."""

DATABASE: Final[str] = "notes.db"

SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS notes (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    body  TEXT NOT NULL
)
"""


class NoteStore:
    """The notes, and the two lines of Pyodide-specific setup they need.

    A class rather than free functions so the connection and the store are opened once and
    owned by one object - the repetition this example is about is not the SQL, it is the
    "work out where the file goes, open it, remember to flush" sequence that otherwise
    appears at every call site.
    """

    def __init__(self, store: Store) -> None:
        self._store = store
        # A path from the store, not a bare filename: this is the single line that differs
        # between a terminal and a browser, and it differs only in what the path is.
        self._connection = sqlite3.connect(store.path(DATABASE))
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute(SCHEMA)
        self._connection.commit()

    @classmethod
    def open(cls) -> NoteStore:
        return cls(Store.open(APP_NAME))

    @property
    def durable(self) -> bool:
        """Whether these notes will still be here next time. False in an unmounted build."""
        return self._store.durable

    @property
    def where(self) -> str:
        return f"{self._store.location.kind} at {self._store.location.root}"

    def all(self) -> tuple[tuple[int, str], ...]:
        """Every note, oldest first."""
        rows = self._connection.execute("SELECT id, body FROM notes ORDER BY id").fetchall()
        return tuple((int(row[0]), str(row[1])) for row in rows)

    def add(self, body: str) -> None:
        self._connection.execute("INSERT INTO notes (body) VALUES (?)", (body,))
        self._connection.commit()

    def remove(self, note_ids: Sequence[int]) -> None:
        self._connection.executemany(
            "DELETE FROM notes WHERE id = ?", [(note_id,) for note_id in note_ids]
        )
        self._connection.commit()

    async def flush(self) -> None:
        """Make the committed rows outlive the tab.

        `commit()` is not enough in a browser and is everything on a terminal, which is
        exactly why this is one call that means "durable now" on both.
        """
        await self._store.flush()


class NoteItem(ListItem):
    """A row that carries its own database id.

    A subclass rather than an attribute stuck onto a plain `ListItem`: the id has to survive
    from render to deletion, and an untyped attribute on a framework widget is the version
    of this that needs a `type: ignore` and stops being checked.
    """

    def __init__(self, note_id: int, body: str) -> None:
        super().__init__(Label(body))
        self.note_id = note_id


class Notes(App[None]):
    """A notebook. Ordinary Textual, plus one awaited `flush`."""

    CSS_PATH = "app.tcss"
    TITLE = "Persistent notes"

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("d", "delete", "Delete selected"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.notes = NoteStore.open()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(self._banner(), id="banner")
        with Horizontal(id="entry"):
            yield Input(placeholder="Write a note and press enter…", id="body")
            yield Button("Add", variant="primary", id="add")
        yield ListView(id="notes")
        yield Footer()

    def on_mount(self) -> None:
        self._reload()

    def _banner(self) -> str:
        if self.notes.durable:
            return f"Saved: {self.notes.where}"
        return (
            "NOT saved - this build has no mounted storage, so notes die with the tab. "
            "Rebuild with `textual-wasm build --storage`."
        )

    def _reload(self) -> None:
        listing = self.query_one("#notes", ListView)
        listing.clear()
        # The row id travels on the widget, so deletion does not depend on the list's order
        # matching the table's.
        for note_id, body in self.notes.all():
            listing.append(NoteItem(note_id, body))

    @on(Input.Submitted, "#body")
    @on(Button.Pressed, "#add")
    def add_note(self) -> None:
        field = self.query_one("#body", Input)
        body = field.value.strip()
        if not body:
            return
        self.notes.add(body)
        field.value = ""
        self._reload()
        self._persist()

    def action_delete(self) -> None:
        listing = self.query_one("#notes", ListView)
        highlighted = listing.highlighted_child
        if not isinstance(highlighted, NoteItem):
            return
        self.notes.remove([highlighted.note_id])
        self._reload()
        self._persist()

    @work(exclusive=True)
    async def _persist(self) -> None:
        """Flush after a change, off the path that handled the keystroke.

        `exclusive=True` is doing real work here: a flush rewrites the whole database file
        into IndexedDB, so a burst of edits should produce one write and not one per
        keystroke. Textual cancels the previous worker, which coalesces them for free.

        A thread is not involved and could not be - Pyodide has none - so this is a
        coroutine on the one event loop, which is also why it must not be a blocking call.
        """
        await self.notes.flush()

    async def on_unmount(self) -> None:
        """The last flush, for the edits the debounced one may have been sitting on.

        Not sufficient on its own in a browser: a closed tab never unmounts the app. The
        page's own `pagehide` handler covers that, and the two together are why neither has
        to be perfect.
        """
        await self.notes.flush()


def main() -> None:
    Notes().run()


if __name__ == "__main__":
    main()
