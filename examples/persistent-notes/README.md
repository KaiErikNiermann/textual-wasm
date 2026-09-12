# persistent-notes

A Textual notebook backed by **SQLite**, whose database survives a terminal restart *and* a
browser reload — from one code path.

```
notes_app/
  app.py      the whole application; `sqlite3` plus one awaited `flush()`
  app.tcss    its stylesheet, shipped to the browser alongside the Python
```

## The point

There is no storage abstraction here, and that is deliberate. Pyodide can mount IndexedDB
*as a filesystem*, so `sqlite3.connect(...)` and `open(...)` already work in a page and
already persist. A `Store` protocol with two backends would be a worse reimplementation of
something the runtime already provides — and it would lose SQL.

What actually differs between the two runtimes is not the API but **when a write becomes
durable**:

| | terminal | browser |
|---|---|---|
| after `write()` / `commit()` | durable | in memory only |
| after `await store.flush()` | durable (no-op) | durable |

So the app calls `flush()` unconditionally. It is a no-op natively, which is what lets the
application code have no runtime branch in it at all.

```python
from textual_wasm.storage import Store

store = Store.open("persistent-notes")
connection = sqlite3.connect(store.path("notes.db"))  # the one line that differs
...
await store.flush()  # no-op natively
```

## Run it in a terminal

```bash
poetry install
poetry run persistent-notes      # or: poetry run python -m notes_app
```

Type a note and press enter; `d` deletes the highlighted one, `q` quits. The banner shows
where the database went — `~/.local/share/persistent-notes` on Linux, via `platformdirs`.
Quit and restart: the notes are still there.

## Run it in a browser

`--storage` is what mounts IndexedDB. Without it the app still runs, and says so in its
banner rather than pretending:

```bash
textual-wasm build notes_app.app:Notes notes_app -o dist/ --storage
textual-wasm dev dist/
```

Add a note, then **reload the page**. It is still there. Then try the same build without
`--storage` and reload: the banner turns into a warning and the note is gone.

Worth doing both, because the difference is the whole lesson: the Python is identical.

## Three things that will bite you

**`commit()` is not durability.** In a browser the row is in an in-memory filesystem until
`syncfs` runs. A closed tab between commit and flush loses it. The app flushes after each
change (debounced with `@work(exclusive=True)`, since a flush rewrites the whole file) and
again on unmount — and the generated page flushes on `pagehide`, because a closed tab never
unmounts the app.

**WAL is not available.** `journal_mode=WAL` wants shared memory and file locking Emscripten
does not provide. This app sets `journal_mode=DELETE` and `synchronous=OFF`: durability comes
from `flush()`, and `fsync` has nothing to sync to under a memory-backed filesystem.

**A flush is whole-file.** IDBFS stores each file as one blob, so syncing a 50 MB database
rewrites 50 MB. Fine for notes and settings; pick something else for bulk data.

## Measured

Pyodide 314.0.6, Chromium and Firefox, main thread and Web Worker: a SQLite database written
to an IDBFS mount, flushed, and read back after a fresh page load — in all four
combinations. `localStorage` was *not* used, and could not have been: it is absent from a
Web Worker's global scope, where `js.localStorage` raises `AttributeError`. IndexedDB is
present in both contexts, which is why the mount is the portable choice.

See [Managing persistent storage](https://kaierikniermann.github.io/textual-wasm/storage.html)
for the full table.
