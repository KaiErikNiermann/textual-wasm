# Managing persistent storage

A TUI that remembers something — a theme, a cursor position, a list of notes — needs a place
to put it. On a terminal that place is a file. In a browser the instinct is to reach for
`localStorage` and write a storage abstraction with two backends.

**Both halves of that instinct are wrong here**, and this page is the measurement that says
so.

---

## What was measured

Pyodide 314.0.6, Chromium and Firefox, on the main thread and inside a Web Worker. WebKit
would not launch on the machine that ran this, so Safari is **unmeasured** — see
[browser support](browsers.md) for what that does and does not imply.

| | main thread | Web Worker |
|---|---|---|
| `js.localStorage` read/write | works | **`AttributeError: localStorage`** |
| `js.sessionStorage` | present | **absent** |
| `js.indexedDB` | present | present |
| `js.caches` | present | present |
| OPFS (`navigator.storage.getDirectory`) | present | present |
| IDBFS mount + `sqlite3`, surviving a reload | works | works |

## Why not `localStorage`

`localStorage` is a property of `Window`. A Web Worker has no window, so it has no
`localStorage` — `js.localStorage` raises `AttributeError` there, measured in both engines.
`textual_wasm.capabilities` already detects that context by the absence of `window`
(`capabilities.py:125`), and `localStorage` is one of the things that absence takes with it.

Since a worker build is the one worth recommending — it is the difference between a 1333 ms
and a 16.8 ms worst-case main-thread stall, see [workers](workers.md) — a store that only
works on the main thread is not a store. It is also 5 MB, string-only, and synchronous on
the thread that paints.

## Why not a storage abstraction either

Pyodide can mount IndexedDB **as a filesystem**. So this works, in a page, in a worker:

```python
import sqlite3

connection = sqlite3.connect("/persist/notes.db")
connection.execute("CREATE TABLE IF NOT EXISTS notes (body TEXT)")
connection.execute("INSERT INTO notes VALUES ('hello')")
connection.commit()
```

`sqlite3` is in Pyodide's distribution (3.39.0). Plain `open()` works too. A `Store` protocol
with a SQLite backend for the terminal and an IndexedDB backend for the browser would be a
worse reimplementation of what the runtime already provides — and it would throw away SQL to
get there.

:::{warning}
`dbm` is **not** in the distribution. `shelve` therefore imports cleanly and fails when you
call `shelve.open`, which is the worst available ordering.
:::

## What actually differs: when a write becomes durable

Not the API. The durability model.

| | terminal | browser |
|---|---|---|
| after `write()` / `commit()` | durable | in memory only |
| after `flush()` | durable (no-op) | durable |

Under IDBFS, writes live in an in-memory filesystem until something calls Emscripten's
`syncfs`, which is asynchronous, whole-file, and nobody's default. A closed tab between the
commit and the sync loses the data.

So `textual_wasm.storage` is deliberately thin. It supplies the two things that genuinely
differ — where the files go, and the one call a browser needs — and leaves the rest to
`pathlib` and the standard library.

## Using it

```python
from textual_wasm.storage import Store

store = Store.open("my-app")          # a directory, on whichever runtime this is
connection = sqlite3.connect(store.path("notes.db"))
...
await store.flush()                    # no-op natively; the durability point in a browser
```

`flush()` is safe and cheap to call unconditionally, which is the point: **application code
has no runtime branch in it.** Build the site with `--storage` to mount the filesystem:

```console
$ textual-wasm build my_app.app:MyApp my_app -o dist/ --storage --worker
built dist - 11 files, 396 KiB, 11 requirement(s)
persistent storage mounted at /persist (IndexedDB); call
textual_wasm.storage.Store.flush() to make writes durable
```

### Where the files go

`Store.open` reports which of three situations you are in, so an app can tell the user rather
than silently losing their work:

| `location().kind` | when | durable |
|---|---|---|
| `native` | a terminal; `platformdirs.user_data_path` | yes |
| `persistent` | a browser build with `--storage` | after `flush()` |
| `ephemeral` | a browser build **without** `--storage`; MEMFS | no |

`ephemeral` is a state rather than an exception on purpose. An app that writes a config
should still run in a build that did not ask for persistence — and it finds out by asking
`store.durable`, not by catching something from `open()`.

### Three flush points, none of them sufficient alone

1. **After a change**, debounced. A flush rewrites the whole file, so a burst of edits should
   produce one write. `@work(exclusive=True)` gets you that for free — Textual cancels the
   previous worker.
2. **On unmount**, for whatever the debounce was still sitting on.
3. **On `pagehide`**, which the generated page does for you. A closed tab never unmounts the
   app, so without this the last edit is lost.

In a worker build (3) needs the page to forward the event to the worker, because only the
page can hear it and only the worker owns the mount. `main.mjs` and `worker.mjs` do this
between them — it is the same shape as `PageCapabilities` in `browser.py:67`, the operations
a worker cannot perform for itself.

`pagehide` rather than `beforeunload`: a backgrounded tab may be discarded without ever
firing `beforeunload`.

## Constraints worth knowing before you design around them

**WAL is not available.** `journal_mode=WAL` wants shared memory and file locking Emscripten
does not provide. Use `journal_mode=DELETE` (or `MEMORY`) and `synchronous=OFF`: durability
comes from `flush()`, and `fsync` has nothing to sync to under a memory-backed filesystem.

:::{note}
`PRAGMA journal_mode=wal` *returns* `"wal"` under Pyodide rather than refusing, so it looks
like it worked. Whether a WAL database survives a `syncfs` round trip was **not measured**
here; treat the setting as unsupported rather than as broken.
:::

**A flush is whole-file.** IDBFS stores each file as one blob, so syncing a 50 MB database
rewrites 50 MB. On a small database the cost is invisible — 1–2 ms in both engines. Plan
differently for bulk data.

**`ENOENT` is 44, not 2.** Code that matches on errno numbers rather than exception types
gets this wrong. Already in [limitations](limitations.md), and storage code is where it bites.

## The other option: OPFS

`navigator.storage.getDirectory()` was present in every context probed, returns a
`FileSystemDirectoryHandle`, and `pyodide.mountNativeFS` accepts one — which would give
byte-range writes instead of whole-file blobs, with no picker and no user gesture.

That is the better long-term floor. It is **not measured here**, so it is a direction rather
than a result, and `--storage` uses IDBFS today.

## A worked example

[`examples/persistent-notes`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/persistent-notes)
is a notebook backed by a real SQLite database with a real schema. Add a note, reload the
page, it is still there. Build it without `--storage` and the banner turns into a warning
instead of quietly forgetting.
