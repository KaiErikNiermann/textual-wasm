# Limitations

Organised by **whose constraint each one is**, because that is what decides whether it can
ever change. A browser sandbox rule is permanent; a choice this project made for v1 is not.

The [porting matrix](matrix.md) is the same material as a per-capability table, generated from
the registry the tools themselves read.

---

## The browser sandbox

Not negotiable by anyone. These are the rules a page runs under.

**No raw TCP or UDP.** `socket.connect()` is worse than unavailable: Emscripten backs sockets
with WebSockets, so it *succeeds* and the first `recv` hangs until the timeout — or forever.
Use HTTP. Anything that needs a real socket needs a server.

**No subprocesses, no `fork`, no shell.** `subprocess` raises clearly; `os.system` in a browser
returns `0` and does nothing, which is the most dangerous entry in the whole registry because
it passes every test run under Node.

**CORS applies to every request** your app makes, including from `requests` and `httpx`.

**No persistent filesystem by default.** Pyodide's filesystem is in memory and disappears with
the tab. IDBFS can persist it, but WAL, `mmap` and file locking are the usual failure points
and this project has not measured them — so it does not promise persistence.

**Downloads and clipboard go through browser APIs**, not paths. `App.deliver_binary` needs an
override; `open_url` is already overridden by the driver.

---

## Pyodide

The interpreter. Some of this could change in a future Pyodide; none of it is something this
project can fix.

:::{admonition} Threads are unavailable in any configuration
:class: warning

`@work(thread=True)` cannot work. Pyodide is **not built with `-pthread`**, and its ABI
documentation forbids `-pthread` in any library linked against it — so this is not a flag
anyone can turn on. Measured rather than inferred: `sys._emscripten_info.pthreads` is `False`
and `grep -c SharedArrayBuffer pyodide.asm.mjs` is `0`.

`SharedArrayBuffer` does **not** change this. It buys the interrupt buffer and `urllib3`'s
streaming worker. Contingent on: a forked Pyodide build. Nothing less.
:::

**`loop.run_in_executor()` ignores the executor** and runs the callable inline on the only
thread. It returns the right answer, so nothing fails — the page just freezes for the duration.
This project turns it into a warning naming the substitute.

**A package bundled as a native wheel pins you to Pyodide's version of it.** `cryptography` is
three majors behind PyPI; `polars`, eleven minors. Since Pyodide 314 a package can also publish
a `pyemscripten` wasm wheel to PyPI, which has no such constraint — `doctor` reports which of
the two you are getting.

**Errno numbers differ.** `ENOENT` is **44** under Emscripten, not 2. Code matching on the
number breaks silently.

**JSPI is reported, not depended on.** `pyodide.ffi.run_sync()` lets synchronous Python await a
promise via stack switching, and Chrome has shipped it unflagged since 137 — but its own
docstring still says experimental, so `check` puts it in the runtime facts and nothing here
requires it.

**Boot costs seconds.** Fetching and starting a CPython interpreter is ~10 MB on the first
visit, cached afterwards. `pyodide-pack` and a trimmed `stdLibURL` are the measurable levers;
neither is wired up here yet.

---

## This project

Deliberate v1 choices. These are the ones that could move, and the list is honest about what
that would take.

**Main thread only.** No Web Worker, which means a slow `on_mount` blocks the page, and it also
means **no COOP/COEP headers are needed** — the simplest deployment works, including GitHub
Pages. The driver is written to be worker-agnostic, so this is deferred rather than designed
out.

**The render comparison assumes a deterministic screen.** `check` diffs cells, and it cannot
tell a font-width bug from an app that drew something different. An app whose content depends
on the network or the clock will differ between legs for reasons that have nothing to do with
WebAssembly. Point it at a stable screen.

**Mouse, bracketed paste, clipboard and focus/blur are implemented but not covered by the
cross-runtime check.** They are exercised by hand, not mechanically.

**The stdlib is not trimmed.** A build ships the full closure. Nothing lazily loads.

**Emoji-presentation width is a property of the terminal, not of this project.** Fed the same
bytes, tmux 3.4 places `⚠️` (U+26A0 U+FE0F) one column further along than Chrome does; tmux
3.5a and 3.7c agree with Chrome exactly. A variation selector requests emoji presentation and
emulators only honour it consistently once their Unicode width data is recent enough — so an
app that draws such emoji will occupy different columns in different terminals, and nothing on
the WebAssembly side changes that. `check` refuses to use a tmux older than 3.5 as its
reference rather than reporting a disagreement about tmux as though it were one about the
browser.

**Nerd Font and Powerline glyphs are unmeasured.** They are private-use codepoints whose width
is a property of the font file rather than of the emulator, so the render equivalence result —
which covers box drawing, CJK, combining marks, astral characters, variation selectors and ZWJ
emoji — does not extend to them.

---

## Textual upstream

Things that work today but rest on Textual's current internals. None of them requires a fork,
and each would be a small upstream change.

**`error_console` is a plain attribute.** Routing crash output into the terminal the user is
looking at works by replacing it. A supported hook for "where do tracebacks go" would be
better than an attribute assignment.

**Driver construction is by class name from an environment variable.** That is the mechanism
this whole project rests on, and it is genuinely public — but `App._driver` is the only handle
on the constructed instance, and it is private. This project keeps that risk in one function
and a lint rule stops it spreading.

**`@work(thread=True)` fails at `loop.run_in_executor`**, deep inside the worker machinery,
rather than at decoration time where the mistake is. A capability check at decoration would
turn a confusing runtime symptom into a clear error.

**Textual's version is pinned into the comparison.** Two runtimes are only comparable if they
load the same code, so a Textual release changes what the check is checking. CI against
upstream releases is the mitigation, and the study recommends building it early.

---

## What is *not* a limitation

Worth stating, because these are commonly assumed:

- **`requests` and `httpx` work in a browser.** Bundled `urllib3` ships an Emscripten backend
  routing through JSPI, a worker, or XHR, and Pyodide patches httpx to use a fetch transport.
  Blocking HTTP code does not have to be rewritten async.
- **C-extension dependencies are not limited to what Pyodide bundles**, since `pyemscripten`
  wheels install from PyPI.
- **CJK, emoji and combining characters render correctly.** Measured against a real terminal,
  cell for cell. The width drift everyone expects did not occur.
- **Textual needs no patch.** Everything here is an out-of-tree driver selected through a
  public hook.
