# Textual → WASM: feasibility study

**Date:** 2026-09-06
**Audited against:** `textual` 8.2.8 (`/usr/lib/python3.14/site-packages/textual`)
**Question:** can one Textual app be shipped *both* as a classic terminal TUI *and* as a
fully client-side web app (no server, no PTY, no WebSocket back to a Python process)?

---

## 0. Verdict

**Feasible, and cleaner than the ecosystem survey suggests.** The absence of a WASM story
upstream is a *product* decision, not an architectural constraint. The audit below finds no
place where Textual's design fundamentally opposes an in-browser runtime.

Three facts carry the whole argument:

1. **`Driver` is a 4-method ABC** (`textual/driver.py:135,146,150,154`) with a handful of
   optional capability hooks. Everything platform-specific is behind it.
2. **`TEXTUAL_DRIVER=pkg.mod:MyDriver` is a supported, documented env hook**
   (`textual/app.py:1585`, `textual/constants.py:113`) that imports an arbitrary out-of-tree
   `Driver` subclass. **A WASM driver needs zero upstream changes to be selected.**
3. **The entire dependency closure is pure Python.** `rich`, `markdown-it-py`,
   `mdit-py-plugins`, `platformdirs`, `pygments`, `typing-extensions` — no C extensions
   anywhere. Nothing needs to be cross-compiled; it's a `micropip.install` away.

The realistic effort is **a single out-of-tree package of roughly 400–700 LOC Python plus a
JS host shim**, not a fork. The hard parts are not Textual — they are font metrics, the
`@work(thread=True)` API, and payload size.

---

## 1. What the survey already established (context, unchanged)

- Zero occurrences of `wasm`/`emscripten`/`pyodide` in Textual 8.2.8.
- Drivers shipped: `linux`, `linux_inline`, `windows`, `win32`, `web` (subprocess+WebSocket),
  `headless`.
- Textualize committed publicly to the **server-side** model; `App.open_url`,
  `App.deliver_text`/`deliver_binary` exist to *abstract over* the server constraint rather
  than remove it.
- Community discussion #2764 open since 2022; PyScript / pygbag / wasmtime attempts, nothing
  landed, **no maintainer participation**.
- `textual-web` (the public-URL variant) has had no release in ~2 years; `textual-serve`
  maintained slowly.

Read that as: *upstream will not build this, and probably will not accept a large patch for
it.* The design below is therefore explicitly structured to need **no upstream patch at all**
in v1, and only small optional ones later.

---

## 2. Architecture audit — where the seams actually are

### 2.1 The `Driver` contract is small

`textual/driver.py`:

| Kind | Member | WASM story |
|---|---|---|
| abstract | `write(data: str)` | → `xterm.js` `term.write()` |
| abstract | `start_application_mode()` | attach JS listeners, emit initial `Resize` |
| abstract | `disable_input()` | detach listeners |
| abstract | `stop_application_mode()` | detach + restore |
| optional | `flush()` | no-op (xterm.js buffers itself) |
| optional | `close()` | no-op |
| capability | `is_headless` / `is_inline` / `is_web` / `can_suspend` | `is_web=True`, `can_suspend=False` |
| plumbing | `send_message` / `process_message` | inherit unchanged |
| capability | `open_url(url, new_tab)` (`:195`) | `js.window.open` |
| capability | `deliver_binary(...)` (`:208`) | Blob + object URL download |

That's the whole surface. Note `process_message()` — the mouse-button-tracking and
cursor-origin logic — is already platform-independent and **inherits for free**.

One wart: `send_message()` (`driver.py:67`) uses `asyncio.run_coroutine_threadsafe`. In a
single-threaded browser runtime that's a needlessly heavy path but it is *correct* — it
degrades to `call_soon_threadsafe` on the running loop. It works; overriding it with a
direct `loop.create_task(...)` is a cheap optimisation, not a requirement.

### 2.2 Platform syscalls are quarantined in `drivers/`

Full sweep for POSIX/Windows-only stdlib imports across the package:

```
app.py:16                     import signal          # only used by suspend(), app.py:4785
drivers/_input_reader_linux.py  selectors
drivers/linux_driver.py         selectors, signal, termios, tty
drivers/linux_inline_driver.py  selectors, signal, termios, tty
drivers/web_driver.py           signal
drivers/win32.py                ctypes / wintypes
_win_sleep.py                   ctypes (Windows-only branch)
```

**Nothing outside `drivers/` touches `termios`, `tty`, `selectors`, `fcntl`, `pty`,
`curses`, `socket`, or `subprocess`.** No `time.sleep` in the core. `import signal` at
`app.py:16` is fine — the module exists under Emscripten; only `os.kill(SIGTSTP)` at
`app.py:4785` would fail, and that path is `App.suspend()`, which is gated on
`Driver.can_suspend`.

`drivers/__init__.py` is **empty**, and `get_driver_class()` imports `linux_driver` lazily
(`app.py:1602`). So `import textual.app` under Emscripten never pulls `termios`. This is the
difference between "works" and "needs a fork", and it happens to already be right.

### 2.3 Timing is plain asyncio

`textual/_time.py` is `monotonic` + `asyncio.sleep` (with a 0.5 ms fudge). `timer.py:167`
awaits it. Pyodide's `WebLoop` implements `call_later` via `setTimeout`; browsers clamp
nested timeouts to ~4 ms, well under Textual's 60 fps / 16 ms default (`TEXTUAL_FPS`,
`constants.py:146`). No change needed.

### 2.4 `run_async` is a real coroutine

`App.run_async()` (`app.py:2220`) does all the work; `App.run()` (`app.py:2308`) is only a
`asyncio.run` wrapper. Under Pyodide you never call `run()` — you `await app.run_async()`
from `runPythonAsync` / a top-level-await module. Nothing needs to change for this.

One thing to verify empirically: `run_async` calls
`loop.set_task_factory(asyncio.eager_task_factory)` (`app.py:2283`, guarded by `hasattr`).
Pyodide's `WebLoop` is a hand-written `AbstractEventLoop`; if it does not honour a task
factory this is silently ignored (behavioural difference only, eager tasks are an
optimisation). **Flag as a smoke test, not a blocker.**

### 2.5 Input parsing is pure and synchronous

`XTermParser.feed(data: str) -> Iterable[Message]` (`_xterm_parser.py:80`). No I/O, no
threads, no fd. The native drivers wrap it in a reader thread purely because `read()`
blocks; in the browser the data arrives as a JS callback on the only thread, so:

```python
term.onData(lambda s: [self.process_message(m) for m in self._parser.feed(s)])
```

`parser.tick()` still needs a periodic pump for the ESC-vs-escape-sequence timeout
(`ESCDELAY`, `constants.py:155`) — a `setInterval` or a small asyncio task, ~10 lines.

Debug wart: `XTermParser.__init__` does `open("keys.log","at")` when `debug=True`
(`_xterm_parser.py:71`). Under MEMFS that's harmless but pointless. Pass `debug=False`.

### 2.6 Prior art in-tree: `web_driver.py`

354 lines, and it is already "a driver that is not a tty". Most of its bulk is the
`D`/`M`/`P` length-prefixed stdout framing to the parent process, plus the input thread and
the file-delivery bookkeeping. A WASM driver is that file **minus** the framing, **minus**
the threads, with `os.write` swapped for a JS callable. Realistically **~250 LOC**.

---

## 3. What has to be built

### 3.1 `textual_wasm.driver:WasmDriver` (~250 LOC)

```
WasmDriver(Driver)
  __init__          : grab js host object, XTermParser(debug=False), size from host
  is_web            : True
  can_suspend       : False
  write(str)        : host.write(str)         -> term.write()
  flush             : pass
  start_application_mode:
      emit \x1b[?1049h (alt screen), mouse SET_ANY_EVENT + SGR-ext, bracketed paste
      host.on_data(self._on_data)             -> parser.feed -> process_message
      host.on_resize(self._on_resize)         -> events.Resize
      post initial Resize
  disable_input     : host.off_data()
  stop_application_mode: restore modes, detach
  open_url          : js.window.open(url, "_blank")
  deliver_binary    : accumulate -> Blob -> URL.createObjectURL -> anchor click
                      (override; base impl spawns threading.Thread, driver.py:280)
```

Only two base methods genuinely *must* be overridden beyond the abstract four:
`open_url` (base calls `webbrowser.open`) and `deliver_binary` (base spawns a thread and
writes to a real path). Both are already virtual. **That is the whole coupling surface.**

### 3.2 JS host shim (~150 LOC TS)

xterm.js instance + `FitAddon` + `WebglAddon`/`CanvasAddon`, exposing an object into
Python via `pyodide.registerJsModule` or a `globalThis` handle:

```ts
{ write(s), onData(cb), onResize(cb), cols, rows, focus(), dispose() }
```

xterm.js is *the* right sink: it already speaks the exact escape-sequence dialect Textual
emits (alt screen, SGR mouse, truecolor SGR, bracketed paste, OSC 52). No renderer needs
writing. Textual's OSC-52 clipboard write at `app.py:1786` even works out of the box if you
enable xterm.js clipboard handling.

### 3.3 Bootstrap + packaging

```
index.html → pyodide.js → loadPyodide
           → micropip.install(["textual", "textual-wasm", <app wheel>])
           → registerJsModule("textual_wasm_host", hostObject)
           → os.environ["TEXTUAL_DRIVER"] = "textual_wasm.driver:WasmDriver"
           → await runPythonAsync("from myapp import MyApp; await MyApp().run_async()")
```

Nicer: ship the app + deps as a **single pre-built Pyodide filesystem image / bundled
wheelset**, so it's one fetch rather than N `micropip` round-trips.

### 3.4 The dual-target story

This is the part that comes out best. Because the driver is selected by env var, the app
source is **byte-identical** between targets:

| | terminal | browser |
|---|---|---|
| entry | `app.run()` | `await app.run_async()` |
| driver | `LinuxDriver` (auto) | `WasmDriver` (via `TEXTUAL_DRIVER`) |
| app code | *same* | *same* |
| CSS/TCSS | *same* | *same* |
| widgets | *same* | *same* |

The only thing an app author must avoid to be dual-targetable is the capability list in §4.
A `textual_wasm.compat` module with a `IS_WASM` flag and a `@work` shim covers most of it.

---

## 4. What breaks, and whether it can be shimmed

| # | Breakage | Severity | Shim? |
|---|---|---|---|
| 1 | `@work(thread=True)` — `worker.py:326` calls `loop.run_in_executor` | **hard** | No (single-threaded). Best effort: raise a clear `WorkerError` at decoration time under WASM, and document "use `@work` async". |
| 2 | Blocking sync I/O — `requests`, `urllib`, `socket` | **hard** | No. Apps must use `pyodide.http.pyfetch` / `httpx` async. Standard Pyodide tax, not a Textual problem. |
| 3 | `subprocess`, `os.fork` | **hard** | No. |
| 4 | `App.suspend()` / `Ctrl+Z` (`app.py:4785`) | trivial | `can_suspend = False` already gates it. |
| 5 | `App.run()` blocking | trivial | Use `run_async`. |
| 6 | `webbrowser.open` | trivial | Override `open_url`. |
| 7 | File delivery to a real path | small | Override `deliver_binary` → Blob download. |
| 8 | Filesystem (`DirectoryTree`, `CSS_PATH`, `App.save_screenshot`) | small | MEMFS works; mount IDBFS or a virtual FS for real content. `DirectoryTree` over MEMFS is genuinely useful. |
| 9 | `platformdirs.user_downloads_path` (`app.py:56`) | small | Called lazily; only in the delivery path you're overriding anyway. |
| 10 | **Font metrics / grapheme width** | **the real one** | See below. |
| 11 | Payload size | medium | See §6. |

### 4.1 The font-width problem (the actual hard bug)

Every reported community attempt hit this, and it is *not* a Textual bug. Textual computes
cell widths with `rich`'s `cell_len` (a Unicode East-Asian-Width table). xterm.js computes
its own widths, and the browser then renders glyphs at whatever the chosen font actually
provides. Three ways to disagree:

- **Wide/ambiguous CJK** — Python says 2 cells, font renders 1.9 → drift across a row.
- **Emoji / ZWJ sequences** — Python's table vs the browser's font fallback.
- **Powerline / Nerd Font glyphs** — only agree if the *exact* patched font is loaded.

Mitigations, in order of effort:
1. Ship a pinned, subsetted **Nerd Font** as a WOFF2 and set it on xterm.js. Removes the
   fallback ambiguity for the glyph set your app uses.
2. Force xterm.js `allowProposedApi` + its Unicode v11/v15 addon so both sides use a
   comparable table.
3. Accept minor drift; Textual repaints whole lines, so drift doesn't accumulate the way it
   would in a diff-based renderer.

This is a *polish* problem, not a *feasibility* problem, but it is the one that made prior
demos look broken.

---

## 5. Runtime choice: Pyodide vs pygbag vs WASI

| | **Pyodide** | **pygbag** | **wasmtime / WASI** |
|---|---|---|---|
| Python | CPython, mature | CPython, game-oriented | CPython or component model |
| JS interop | first class (`js`, `pyodide.ffi`) | limited | **none in-browser** |
| asyncio | `WebLoop` on `setTimeout` | own loop | needs `wasi:io` poll |
| Threads | no (without SAB+worker) | no | no |
| Package install | `micropip` (pure-Python wheels) | bundle-time | bundle-time |
| Fit for this | **yes** | workable, awkward | **no** — no DOM |

**Pyodide is the only sensible target.** The wasmtime/WASI attempt reported in #2764 hitting
"platform driver import failures with socket permission errors" is exactly what you'd
expect: WASI has no DOM, so you'd be reinventing xterm.js inside WASM for no reason. Kill
that branch.

Optional later refinement: run Python in a **Web Worker** with the xterm.js instance on the
main thread, `postMessage`-bridged. Keeps a heavy `on_mount` from freezing the page, and
with `SharedArrayBuffer` (needs COOP/COEP headers) it also unlocks real threads and
therefore `@work(thread=True)`. Non-goal for v1.

---

## 6. Payload budget

Measured source (`.py` + `.css`/`.tcss`, this machine):

```
textual            2.76 MB
rich               1.22 MB
pygments           4.58 MB   <- 90%+ is lexers
markdown-it-py     0.23 MB
mdit-py-plugins    0.15 MB
platformdirs       0.12 MB
                   -------
                   ~9.1 MB source
```

Plus the Pyodide runtime (`pyodide.asm.wasm` ≈ 9 MB raw, ~4 MB brotli — *approximate, verify
against the version you pin*).

Rough first-load: **~12–15 MB raw, ~5–7 MB over the wire with brotli.** Cold start on the
order of 2–4 s; cached, well under a second.

Levers, in order of payoff:
1. **Drop / subset `pygments`** — it is only reachable via syntax highlighting in
   `TextArea`, `Markdown` code fences and `RichLog`. If your app doesn't highlight code,
   stubbing it saves half the Python payload.
2. Strip `mdit-py-plugins` + `markdown-it-py` if no `Markdown` widget.
3. Precompile to `.pyc` in the bundle image — skips parse on every cold start.
4. Serve brotli, long `Cache-Control`, and preload the wasm.

None of this needs upstream cooperation; it's bundler work.

---

## 7. Maintainability against upstream

### 7.1 The coupling surface is genuinely small

An out-of-tree `WasmDriver` depends on exactly:

- `textual.driver.Driver` (ABC, 4 abstract methods)
- `textual._xterm_parser.XTermParser.feed()` — **private**, leading underscore
- `textual.events.Resize`, `textual.geometry.Size`
- the `TEXTUAL_DRIVER` env contract
- `App.run_async()`

Four of those five are public and stable. The one real hazard is `_xterm_parser` — private
API, and the input-parsing code is where Textual actually churns (kitty protocol, mouse
modes, bracketed paste). That's your version-pin risk.

### 7.2 Cost of tracking upstream

Textual ships frequently but the `Driver` ABC has been stable for years — the last drivers
added (`web`, `linux_inline`) *extended* it rather than reshaping it. Realistic maintenance:

- **Pin a tested range** (`textual>=8.2,<9`) and bump deliberately.
- Run the Textual snapshot/`Pilot` test suite against `WasmDriver` in headless-under-node
  CI. `Pilot` is driver-agnostic, so **most of Textual's own tests become your regression
  suite for free** — this is the single highest-leverage thing you can do.
- Expect to touch `_xterm_parser` glue **maybe once or twice a year**.

Budget: **a few hours per minor release.** Comparable to maintaining any driver-shaped
plugin.

### 7.3 Upstream posture

Assume **no help**. Design accordingly:

- v1 must be a pure add-on package (`pip install textual-wasm`) with **zero patches**. The
  audit says this is achievable.
- If it works and gets traction, the asks upstream would be *small* and independently
  defensible, which is the only kind that lands:
  - make `XTermParser` public (or add a thin `textual.input.parse_input()`);
  - add an `emscripten`/`wasm` branch in `get_driver_class()` (~4 lines) so
    `TEXTUAL_DRIVER` isn't required;
  - a `Driver.supports_threads` capability flag so `@work(thread=True)` can fail loudly
    instead of obscurely.

Each is a <20-line PR. None require Textualize to own or support a WASM target — which is
precisely why they might be accepted, and why the project doesn't depend on it.

### 7.4 Bus factor

The real maintainability risk isn't Textual's API churn — it's **Pyodide**, xterm.js addon
churn, and the fact that community WASM attempts have historically been one-person demos
that stalled. Mitigate with: pinned versions across the board, CI that runs the real app in
headless Chrome on every Textual/Pyodide bump, and a deliberately boring scope.

---

## 8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Font/cell-width drift looks broken | **high** | medium | pinned subsetted Nerd Font + xterm.js Unicode addon |
| `_xterm_parser` private-API break | medium | medium | pin range, CI on Textual releases |
| Payload too heavy for target users | medium | medium | drop pygments, brotli, precompiled bundle |
| App uses `@work(thread=True)` | medium | **high** for that app | fail loudly + document; Worker+SAB later |
| Pyodide `WebLoop` misses `set_task_factory` | low | low | already `hasattr`-guarded upstream |
| Textualize refuses even the small PRs | medium | low | v1 needs none of them |
| Deep-in-Textual assumption discovered late | low | high | de-risk with the day-1 spike below |

---

## 9. Recommended path

**Spike (½–1 day).** `HeadlessDriver` subclass under Pyodide whose `write()` pushes to a
JS array; render one `Static("hello")`; confirm `import textual.app` doesn't drag in
`termios`, that `run_async` starts, and that `Resize` reaches the app. This kills or
confirms the whole thesis for almost nothing.

**v0 (~1 week).** Real `WasmDriver` + xterm.js host. Keyboard, mouse, resize, alt screen.
Target: `code_browser.py` and the Textual demo running interactively.

**v0.1.** `open_url`, `deliver_binary`, clipboard, MEMFS `DirectoryTree`, a font that
matches, the `@work(thread=True)` loud failure, `textual_wasm.compat.IS_WASM`.

**v0.2.** Bundler CLI: `textual-wasm build myapp:MyApp -o dist/` → static directory. This is
the actual product; the driver is just the enabler.

**v0.3.** CI running Textual's own `Pilot` tests under headless Chrome. Web Worker mode.
Then, and only then, open the small upstream PRs.

---

## 10. Bottom line

The ecosystem survey's conclusion — "no WASM story, and no one is building one" — is
correct about the *state of the world* and misleading about the *difficulty*. Textual's
architecture is unusually well-suited to this: an abstract driver, an env-var driver hook
that was clearly built for out-of-tree drivers, syscalls confined to `drivers/`, a fully
awaitable entry point, a pure-sync input parser, and a dependency closure with zero native
code.

The reason it doesn't exist is that Textualize chose a server-side business model, not that
the code resists it. **Nothing here needs a fork.** The genuinely hard problems are font
metrics and thread workers, and both are containable.

Confidence: **high** that a working demo is a week of work. **Medium** that it stays
low-maintenance without CI against upstream releases — build that CI early.
