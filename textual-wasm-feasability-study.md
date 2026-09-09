# Textual → WASM: feasibility study

**Date:** 2026-09-06, revised 2026-09-09 with spike results
**Audited against:** `textual` 8.2.8 (`/usr/lib/python3.14/site-packages/textual`)
**Question:** can one Textual app be shipped *both* as a classic terminal TUI *and* as a
fully client-side web app (no server, no PTY, no WebSocket back to a Python process)?

> **Status: confirmed by a working spike.** §11 records what was actually built and measured.
> The audit below is unchanged except where the spike corrected it; every correction is
> marked **[spike]**.

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

> **[spike] This was the one prediction that was wrong, and it was wrong in the worse
> direction.** `WebLoop` *does* honour `set_task_factory` — and then dies. Its `create_task`
> is a copy of CPython 3.13's `BaseEventLoop.create_task`, whose task-factory branch calls
> `asyncio.tasks._set_task_name`, a private helper **removed in CPython 3.14**. Pyodide
> 314.0.6 ships CPython 3.14. The branch is taken only once a factory is set, and
> `App.run_async` sets one unconditionally, so under Pyodide *every* `loop.create_task`
> after the app starts raises `AttributeError`. It is a Pyodide bug, not a Textual one, and
> a four-line polyfill fixes it — but nothing about it is "a behavioural difference only".

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
| 2 | Blocking sync I/O — `requests`, `urllib`, `socket` | **[spike] partly wrong, see below** | `requests` and `httpx` work. Raw sockets do not. |
| 3 | `subprocess`, `os.fork` | **hard** | No. |
| 4 | `App.suspend()` / `Ctrl+Z` (`app.py:4785`) | trivial | `can_suspend = False` already gates it. |
| 5 | `App.run()` blocking | trivial | Use `run_async`. |
| 6 | `webbrowser.open` | trivial | Override `open_url`. |
| 7 | File delivery to a real path | small | Override `deliver_binary` → Blob download. |
| 8 | Filesystem (`DirectoryTree`, `CSS_PATH`, `App.save_screenshot`) | small | MEMFS works; mount IDBFS or a virtual FS for real content. `DirectoryTree` over MEMFS is genuinely useful. |
| 9 | `platformdirs.user_downloads_path` (`app.py:56`) | small | Called lazily; only in the delivery path you're overriding anyway. |
| 10 | **Font metrics / grapheme width** | **the real one** | See below. |
| 11 | Payload size | medium | See §6. |

> **[spike] Row 2 was too strong: blocking HTTP is not fatal.** "Apps must use pyfetch or
> async httpx" is wrong as guidance. Bundled `urllib3 2.6.3` ships
> `urllib3/contrib/emscripten/`, which routes through JSPI, a worker plus SharedArrayBuffer,
> or XHR; and Pyodide *patches* httpx so that `sys.platform == "emscripten"` swaps in a
> fetch-backed transport. Synchronous `requests` code therefore runs in a browser.
>
> The real constraints are narrower and worth stating instead: CORS applies to every request,
> timeouts and certificate and proxy configuration are unavailable, and streaming responses
> need both a Web Worker and cross-origin isolation. Note the patched httpx is *Pyodide's*,
> not PyPI's. Raw `socket.connect` is the genuinely broken case, and it is worse than "hard"
> — it succeeds and then hangs, which is why it is in the registry's silent class.
>
> **[spike] Row 3, and the dependency story generally, has changed.** This document assumed
> C-extension dependencies work only if Pyodide bundles a build. Since Pyodide 314 a package
> can publish a `...-pyemscripten_2026_0_wasm32.whl` to PyPI and `micropip.install()` works
> with no Pyodide-side build at all. The inverse constraint is the new one, and it is the one
> to design around: a package available only as a Pyodide-*bundled* native wheel pins you to
> Pyodide's version of it — `cryptography` is three majors behind PyPI, `polars` eleven
> minors. `textual-wasm doctor` reports which of the two a dependency is.

### 4.1 The font-width problem (the actual hard bug)

Every reported community attempt hit this, and it is *not* a Textual bug. Textual computes
cell widths with `rich`'s `cell_len` (a Unicode East-Asian-Width table). xterm.js computes
its own widths, and the browser then renders glyphs at whatever the chosen font actually
provides. Three ways to disagree:

- **Wide/ambiguous CJK** — Python says 2 cells, font renders 1.9 → drift across a row.
- **Emoji / ZWJ sequences** — Python's table vs the browser's font fallback.
- **Powerline / Nerd Font glyphs** — only agree if the *exact* patched font is loaded.

> **[spike] Measured, and not observed.** §12 diffs the browser against a real terminal —
> `tmux` running the app on a pty through Textual's own driver. Box drawing, arrows, braille,
> **CJK**, astral-plane characters, variation selectors and **ZWJ sequences** all land in
> identical cells. Every specific failure predicted in this section — CJK drift, emoji
> divergence — did not occur. Only Nerd Font glyphs remain unmeasured, and those are
> private-use codepoints whose width is a property of the font file, not of the emulator.

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
| Threads | **no, in any configuration** | no | no |
| Package install | `micropip` (pure-Python wheels) | bundle-time | bundle-time |
| Fit for this | **yes** | workable, awkward | **no** — no DOM |

> **[spike] Pyodide's versioning changed.** Releases are now aligned to the CPython version
> they ship: `314.0.6` is CPython 3.14, and the old `0.2x` line ended at `0.29.4`. Anything
> written against "Pyodide 0.29" is a major version behind. Pinning matters more than usual
> here — see the micropip finding in §11.

**Pyodide is the only sensible target.** The wasmtime/WASI attempt reported in #2764 hitting
"platform driver import failures with socket permission errors" is exactly what you'd
expect: WASI has no DOM, so you'd be reinventing xterm.js inside WASM for no reason. Kill
that branch.

Optional later refinement: run Python in a **Web Worker** with the xterm.js instance on the
main thread, `postMessage`-bridged. Keeps a heavy `on_mount` from freezing the page. Non-goal
for v1.

> **[spike] `SharedArrayBuffer` does not unlock threads.** This section originally said that
> SAB plus a worker gives you real threads and therefore `@work(thread=True)`. That is wrong,
> and it was the most load-bearing wrong claim in this document, because it made an
> unavailable feature look like a deployment-header problem.
>
> Pyodide is not built with `-pthread`, and its ABI documentation forbids `-pthread` in any
> library linked against it. Measured, not inferred: `grep -c SharedArrayBuffer
> pyodide.asm.mjs` is `0`, and `sys._emscripten_info.pthreads` is `False` in the running
> interpreter — the probe reports it as `threads_available` on every run. SAB buys the
> interrupt buffer and `urllib3`'s streaming worker; it does not buy `threading`.
>
> `@work(thread=True)` is therefore unavailable short of a forked Pyodide build, and the
> correct treatment is a loud, specific failure at the call site rather than a note about
> COOP/COEP headers. That is what `textual_wasm.diagnostics` now does.
>
> **JSPI is the real escape hatch for synchronous code.** `pyodide.ffi.run_sync()` lets
> synchronous Python await a JS promise by stack switching, and `can_run_sync()` feature-detects
> it — measured `True` under `runPythonAsync`, `False` under plain `runPython`. Chrome has
> shipped it unflagged since 137. Its own docstring still says "experimental / not yet
> stable", so the probe *reports* it (`RuntimeFacts.jspi`) rather than depending on it.

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

**[spike] Measured**, against the pinned `pyodide@314.0.6`:

```
pyodide.asm.wasm    9.2 MB raw   3.1 MB brotli
python_stdlib.zip   2.4 MB raw   2.4 MB brotli   (already deflated)
```

So first load is **~12 MB raw, ~5.5 MB over the wire**, plus the Python packages above. The
earlier estimate held. Measured timings under Node, warm cache:

```
pyodide boot          ~0.9 s
dependency install    ~0.7 s
probe (app run)       ~3.8 s   <- dominated by the probe's own deliberate waits
```

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

**[spike] Revised.** The top row was wrong; see §12.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ~~Font/cell-width drift looks broken~~ **[spike]** not observed at all: BMP, CJK, astral, variation selectors and ZWJ all render identically in a real terminal and in the browser. Only private-use (Nerd Font) glyphs remain unmeasured | ~~high~~ **low** | medium | pinned font stack; the tmux reference in §12.3 |
| `_xterm_parser` private-API break | medium | medium | pin range, CI on Textual releases |
| Payload too heavy for target users | medium | medium | drop pygments, brotli, precompiled bundle |
| App uses `@work(thread=True)` | medium | **high** for that app | fail loudly + document; Worker+SAB later |
| Pyodide `WebLoop` misses `set_task_factory` | low | low | already `hasattr`-guarded upstream |
| Textualize refuses even the small PRs | medium | low | v1 needs none of them |
| Deep-in-Textual assumption discovered late | low | high | de-risk with the day-1 spike below |

---

## 9. Recommended path

**Spike (½–1 day).** ~~`HeadlessDriver` subclass under Pyodide…~~ **Done — see §11.** It
went further than planned: the driver, the Node probe *and* an xterm.js page all landed, so
v0 below is mostly hardening rather than new construction.

**v0 (~1 week).** Harden the browser driver: mouse, bracketed paste, clipboard, focus/blur,
the ESC-timeout pump under real load. Target: `code_browser.py` and the Textual demo
running interactively.

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

Confidence: ~~**high** that a working demo is a week of work~~ — **[spike] it was a day**,
including the browser half; see §11. **Medium** that it stays low-maintenance without CI
against upstream releases — build that CI early.

---

## 11. Spike results (2026-09-09)

Everything in §0–§10 above was a reading of the source. This section is measurement.

### 11.1 What was built

An out-of-tree package (`textual_wasm`) against **unpatched Textual 8.2.8 from PyPI**:

| Piece | What it is |
|---|---|
| `driver.py` | `WasmDriverBase` — app-mode sequences, `XTermParser` pump, resize, capability overrides. ~190 lines. |
| `driver.py` | `CaptureDriver` — sink is a list. Used by the probe and the tests. |
| `browser.py` | `BrowserDriver` — sink is `xterm.js`. ~110 lines. |
| `probe.py` | One driver-agnostic coroutine that boots a real `App` and returns a structured verdict. |
| `harness/pyodide-probe.mjs` | Runs that same coroutine under Pyodide in Node. |
| `assets/` + `bundler.py` | The same app in a browser against a real terminal emulator. |

*(Paths as of the module build-out; the spike's `scripts/run-pyodide-node.mjs`, `web/` and
`scripts/serve.mjs` moved into the package so a user needs no checkout of this repository.)*

**No patch to Textual, and no fork.** `TEXTUAL_DRIVER=textual_wasm.driver:CaptureDriver` was
sufficient, exactly as §2.1 predicted.

### 11.2 The result

Eight mechanically-checkable claims, run natively and under Pyodide, compared by
`textual-wasm check`:

| check | native | wasm |
|---|---|---|
| `import_purity` — no tty module, no Textual platform driver imported | pass | pass |
| `driver_hook` — `TEXTUAL_DRIVER` selected the out-of-tree class | pass | pass |
| `run_async` — completed on the host loop, returned the sentinel | pass | pass |
| `resize_delivered` — driver-synthesised `Resize` reached the app | pass | pass |
| `ansi_output` — compositor emitted truecolor SGR | pass | pass |
| `widget_rendered` — the app's own text present on the replayed grid | pass | pass |
| `key_input` — bytes through `XTermParser` drove an app binding | pass | pass |
| `timer` — `set_timer` fired | pass | pass |

Runtime differences, all expected: `linux`/`emscripten`, `_UnixSelectorEventLoop`/`WebLoop`,
threads `True`/`False`, one polyfill. `textual_version` identical, which is what makes the
comparison mean anything.

**The compositor emitted a byte-identical 7311 characters on both runtimes.**

In the browser: renders correctly at 119×32 in `xterm.js`, truecolor, borders and box-drawing
intact; three real Chrome keystrokes produced three increments and three live re-renders.

### 11.3 Findings the source audit could not have produced

Ranked by how much time they would cost someone starting from the audit alone.

**1. `App.run_async` breaks every `create_task` under Pyodide.** See the box in §2.4. Four-line
polyfill, but the symptom is an `AttributeError` from deep inside `WebLoop` that names nothing
recognisable.

**2. Python callbacks handed to JavaScript need `pyodide.ffi.create_proxy`.** The automatic
proxy is *borrowed* and destroyed when the call it was passed into returns, so
`terminal.onData(self.feed_input)` registers cleanly and then throws
`This borrowed proxy was automatically destroyed` on every keystroke — into the browser
console, where a Textual app will never see it. Cost: 114 silent errors and a key that did
nothing. **Any browser driver must own its proxies and destroy them on teardown.**

**3. `textual.constants` caches every `TEXTUAL_*` variable at import time** (`constants.py:113`).
Setting `os.environ["TEXTUAL_DRIVER"]` after anything has imported `textual` has no effect
whatsoever, silently, and the app falls back to the platform driver and dies on `termios`. The
ordering has to be structural, not remembered.

**4. micropip resolves Pyodide's bundled package set before PyPI.** `micropip.install("textual")`
pulled `rich 14.3.3` (bundled) rather than 15.0.0 — and that older `rich` imports `getpass`,
which imports `termios`, which failed the import-purity check for a reason that had nothing to
do with Textual or with WASM. Pyodide 314.0.6 bundles `rich`, `pygments`, `platformdirs` and
`typing_extensions`. **Pin the whole closure, generated from the native environment**, or the
two runtimes are not running the same code and no comparison between them is valid.

**5. Three browser-only failures, all silent.** A 404 stylesheet (xterm's hidden
character-measurement element renders on top of the app); a container class of `terminal`,
which is also what `xterm.js` names its own root element (every rule applies twice); and
`FitAddon.fit()` before `document.fonts.ready` (divides the container by an unmeasurable cell
and yields a 1-row grid — the app renders, just one line of it). None raise.

**6. `fcntl` is not a Textual import.** `import asyncio` pulls it via `subprocess` on POSIX,
along with `selectors` and `signal`. An import-purity check that watches them tests an import
graph Textual does not control. The meaningful watch list is `termios`, `tty`, `pty`, `curses`
plus `textual.drivers.*_driver`.

### 11.4 What the spike did *not* settle

- ~~**Font metrics.**~~ **Settled for everything but emoji — see §12.**
- ~~**Frame-for-frame equality.**~~ **Done — see §12.**
- **Mouse, paste, clipboard, focus/blur** are written but untested.
- ~~**`@work(thread=True)`** is confirmed unavailable (`threads_available: false`) but still
  fails obscurely rather than loudly.~~ **Addressed.** `textual_wasm.diagnostics` now
  intercepts `run_in_executor` — the call `worker.py:326` makes — and raises with the
  constraint and the substitute named. §5's correction explains why no configuration can
  make threads available.

---

## 12. Render equivalence (2026-09-09)

§11 established that the two Python runtimes emit the same bytes. A byte stream is a
rendering *instruction*, so that left the study's top risk — font and cell metrics — open.
This section closes most of it.

### 12.1 Method

A third runtime was added: **headless Chrome driving the real page**, and a way to compare
what it draws against what a terminal would.

```
                    ┌── WasmDriver ──▶ ANSI stream ──┬──▶ pyte replay (wcwidth)
Textual             │                                │            │
(rich cell_len) ────┤                                └──▶ xterm.js render (own table)
                    │                                             │
                    └── LinuxDriver ─▶ real pty ──▶ tmux 3.7c ────┤
                                                                  ▼
                                                                diff
```

Three character-width tables, none sharing code, and — after §12.3 — two references rather
than one. The upper path is this project's driver; the lower is Textual's own on a real pty,
with nothing from the WASM work in it. That lower path is the reference that matters: a
browser render matching it is a browser render matching what a user would see. `pyte` is a terminal emulator in pure
Python, so it installs under Pyodide and both Python runtimes now carry a **rendered grid**
in their report, not just a byte count. `scripts/run-browser-check.mjs` boots the page in
Chrome at a forced grid (`?cols=80&rows=24` — a browser window's size is not a number anyone
chose), drives the app through `xterm.js`'s own user-input entry point, and reads the buffer
back. `textual-wasm compare-screens` diffs the two.

Both sides are normalised first: trailing blanks dropped, and text composed to NFC. `pyte`
merges a combining mark into the cell it modifies and yields the composed character;
`xterm.js` returns the codepoints it was sent. One column, one glyph, two spellings — that is
a representation difference, not a rendering one.

### 12.2 Result

**Identical, cell for cell**, at 80×24 — across the pyte replay, the browser, *and* a real
terminal:

```
ascii     abcdef|
box       ─│┌┐└┘├┤|
arrows    ←↑→↓|
braille   ⠁⠂⠃⠄⠅|
cjk       世界日本語|
combining éà|
astral    🚀💻|
vs16      ✅⚠️|
zwj       👩‍💻|
```

Each sample carries a terminator, so a width disagreement would move that character and the
diff would name the row and the column rather than merely failing. Nothing moved. **The
wide/ambiguous CJK drift §4.1 predicted did not occur.**

### 12.3 The one divergence, and which side was wrong

The first run of this comparison was *not* green. Three rows differed — `combining`, `emoji`
and `zwj` — and in every case **the browser was the faithful one**.

`pyte` 0.8.2 silently discards the remainder of a line after a zero-width joiner (U+200D) or
a variation selector (U+FE0F). Reduced to a one-liner:

| fed | pyte renders | xterm.js renders |
|---|---|---|
| `世界\|` | `世界\|` | `世界\|` |
| `🚀\|` | `🚀\|` | `🚀\|` |
| `⚠️\|` | `⚠` | `⚠️\|` |
| `👩‍💻\|` | `👩` | `👩‍💻\|` |

CJK and astral-plane characters are fine; a joiner or a variation selector eats the rest of
the row. So on emoji sequences the oracle was wrong and the browser was right, which meant
`pyte` **could not adjudicate emoji at all** — including them measured the measuring
instrument.

This is the shape of finding a spike exists to produce. The study assumed the browser would be
the unreliable side. Where a disagreement was actually found, it was the reference
implementation that was wrong.

**The fix was a better reference, not a smaller question.** `textual_wasm.terminal` runs the
app under `tmux` on a real pty through **Textual's own `LinuxDriver`**, and reads the pane
back with `capture-pane`. Reproducibility comes from refusing the ambient environment:
`-f /dev/null` ignores the user's tmux config, `-u` forces UTF-8, and the status bar is
turned off because it would otherwise consume one of the rows being compared. The capture
waits for a *settled* marker rather than a ready one — without that it races the app and
intermittently reads `pressed 0`.

With that reference the emoji samples are answerable, and the answer is agreement: `vs16` and
`zwj` render identically in tmux 3.7c and `xterm.js` 6, terminator and all. They are back in
the sample set.

`pyte` keeps a narrower job — giving the two Python runtimes a comparable grid. They share
its blind spots exactly, so equality between *them* stays meaningful. The characterisation
test now pins that reasoning. tmux is optional throughout: the tests skip and
`run-spike.sh` says so, the same way the semgrep suite skips without semgrep.

### 12.4 What remains open on rendering

- ~~**Emoji and ZWJ sequences.**~~ **Settled — see §12.3.** They render identically in a real
  terminal and in the browser.
- **Nerd Font / Powerline glyphs.** Private-use codepoints whose width depends entirely on the
  loaded font. Not exercised; the page pins a plain monospace stack.
- **Non-default fonts generally.** One font stack was measured (`IBM Plex Mono`, `DejaVu Sans
  Mono`, `ui-monospace`). The result is about that stack.
- **Styling.** The diff is over characters, not colours or attributes. Truecolor SGR is
  asserted present but never compared cell by cell.

---

## 13. The WASM Component Model, assessed and closed (2026-09-09)

The obvious question about anything WASM in 2026 is whether the **Component Model** and
**WIT** help — a typed interface language, with Rust or Go or C filling in what Python cannot
do. The answer is no, and the reason is structural rather than a matter of maturity, so it is
recorded here to close the question rather than leaving it open.

**Two different Pythons that cannot meet.** Pyodide is `wasm32-unknown-emscripten`.
`componentize-py` targets `wasm32-wasip2` and ships *its own* CPython built against wasi-sdk.
These are separate builds with separate memories and separate object graphs; there is no
shared heap for a Python object to cross and no ABI that would let one call the other's
interpreter. Putting both in one page means shipping two interpreters that can exchange
nothing but bytes.

**WASI 0.2 has no browser story.** `jco` can put a component in a browser only by transpiling
it back to core WebAssembly plus JavaScript glue — which is `wasm-bindgen` with extra
ceremony, and arrives at the same place the existing `pyodide.ffi` already occupies.

**Pyodide has no component-model interop**, present or planned. Searched: no issues, no
roadmap entry, no prior art.

So the branch is killed. The practical version of "another language fills a gap" is what
already works: compile that piece to a core wasm module and call it through `pyodide.ffi`, or
publish it as a `pyemscripten` wheel and `micropip install` it. Both are available today and
neither needs a second interpreter.

Two adjacent options were assessed and rejected for their own reasons. **RustPython** is
22.8 MB of wasm — *larger* than Pyodide — with an incomplete standard library.
**MicroPython-wasm** is not CPython, and Rich and Textual need the full standard library. For
payload, `pyodide-pack` plus a custom `stdLibURL` remains the boring, measurable lever.
