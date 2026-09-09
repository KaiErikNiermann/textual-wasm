# Porting an existing app

In the order you will actually hit the problems, with the reason each one is a problem.

The short version: **a Textual app that avoids threads, subprocesses and raw sockets usually
runs unchanged.** What follows is how to find out whether yours is one, and what to do when it
is not.

:::{seealso}
{doc}`quickstart` if you are starting a new app rather than moving one. {doc}`limitations` for
the same material organised by *whose* constraint each one is.
:::

## 1. Ask before you run

```console
$ textual-wasm doctor myapp.main:App -r httpx -r pydantic
```

The doctor reads your source and reports three classes of problem with a `file:line` for
each:

- **imports** of modules that are absent or behave differently,
- **call sites** for the failures that raise nothing at all - `os.system()`, `time.sleep()`,
  `loop.run_in_executor()`. Import scanning cannot see these, because the module is fine and
  the call is not,
- **dependencies**, classified as pure Python (any version), a `pyemscripten` wasm wheel on
  PyPI, a Pyodide-bundled native wheel (which **pins you to Pyodide's version** of that
  package), or unavailable.

A finding you have considered and accepted can be marked in place:

```python
time.sleep(0.5)  # textual-wasm: allow time.sleep - CLI-only path, never reached in the browser
```

The reason is required. A pragma without one is how a suppression outlives the thing it was
suppressing.

## 2. The five that fail silently

These are the ones worth reading even if the doctor is clean, because they are the ones
whose absence you cannot feel in testing:

| What you wrote | What happens |
|---|---|
| `loop.run_in_executor(...)` | Runs inline on the only thread. Code written to keep the UI responsive freezes the page. |
| `time.sleep(n)` | Blocks everything for `n` seconds - rendering, input, timers. |
| `os.system(...)` | Works in Node. Returns 0 and does nothing in a browser. |
| `socket.connect(...)` | Succeeds. The first `recv` then hangs until the timeout, or forever. |
| `os.kill(pid, SIGKILL)` | Tears down the interpreter. Not catchable, and nothing runs after it. |

`textual_wasm.diagnostics.install()` turns each of these into a loud, specific error or
warning that names the substitute. The build output calls it for you; call it yourself if
you are hosting Pyodide some other way.

The full list, with what was measured for each, is the {doc}`matrix`.

## 3. Threads are not available, in any configuration

`@work(thread=True)` cannot work. Pyodide is not built with `-pthread`, and its ABI forbids
`-pthread` in any library linked against it, so this is not a flag anyone can turn on:
`sys._emscripten_info.pthreads` is `False` and `SharedArrayBuffer` does not change it. SAB
buys the interrupt buffer and urllib3's streaming worker, not `threading`.

Use `@work` without `thread=True`. If the work is genuinely CPU-bound, it has to be broken
into chunks that `await asyncio.sleep(0)` between them, because there is one thread and the
UI is on it.

## 4. Blocking HTTP is mostly fine

Contrary to the usual advice, `requests` and `httpx` work in a browser. Bundled `urllib3`
ships an Emscripten backend that routes through JSPI, a worker, or XHR, and Pyodide patches
httpx to use a fetch-backed transport when `sys.platform == "emscripten"`.

What does not carry over: CORS applies to every request, timeouts and certificate and proxy
configuration are not controllable, and streaming responses need both a Web Worker and
cross-origin isolation. For new code `pyodide.http.pyfetch` is the direct route.

## 5. The terminal has to be told it is a terminal

A TUI decides how to draw from things a browser does not have. The build output handles all
of this; it is listed because anyone hosting Pyodide themselves has to:

- `os.get_terminal_size()` raises, and `shutil.get_terminal_size()` falls back to 80x24, so
  `COLUMNS` and `LINES` must be passed to `loadPyodide({env})`.
- `isatty()` is `False` by default, and an app that believes it has no terminal disables
  colour before it draws. `pyodide.setStdin({isatty: true})`.
- `SIGWINCH` never fires. Resizes come from a `ResizeObserver` on the container.
- Rich's colour auto-detection reads `COLORTERM`/`TERM`, which nothing sets here, so it
  degrades to 8-bit. `TEXTUAL_COLOR_SYSTEM=truecolor` - xterm.js renders truecolor.

`textual_wasm.bootstrap.REQUIRED_ENVIRONMENT` holds the Python half, and applies it as a
package import side effect. It has to happen before the first `import textual` anywhere in
the process: `textual.constants` reads every `TEXTUAL_*` variable into module-level
constants at import time, so a value set afterwards is ignored, silently.

### The page around your app

The default page is bare, and `--title` and `--template` are how you change it. That is a
subject of its own: see {doc}`embedding`.

## 6. Crashes go where nobody is looking

Textual prints tracebacks through a `Console(stderr=True)`. Under Pyodide stderr is the
browser console - so an app that crashes in the browser reports it somewhere the user cannot
see and the developer is not watching.

`diagnostics.attach(app, driver)` replaces that console with one that writes into the
terminal the user is already looking at. The browser driver does it when it takes the
terminal, so a hosted app gets it without asking.

## 7. Pin the dependency closure, not just your dependencies

```console
$ textual-wasm pins        # writes wasm-requirements.txt from the native environment
```

micropip resolves against Pyodide's own bundled package set *before* PyPI. Asking for bare
`textual` therefore yielded a markedly older `rich` than the native environment had - and
that older `rich` imports `getpass`, which imports `termios`. The failure surfaced as a
purity check about terminal modules, which had nothing to do with the actual cause.

Two runtimes cannot be compared unless they load the same code. Generating the pins from the
native environment is what makes that true.

## 8. Check it rather than believing it

```console
$ textual-wasm check --app myapp.main:App \
    --ready-marker "My App" --keys q --settled-marker bye
```

The markers are what let a machine tell "the app has drawn" from "the runtime has not
started yet". Without a ready marker every leg waits for any non-blank screen, which is
weaker but still honest; without a settled marker the keystroke cannot be checked at all,
because a screen captured right after typing may not have handled it.

What the check compares:

- **native against Pyodide** - eight checks, the runtime facts, and the replayed grid. Any
  disagreement is a real portability difference.
- **a real terminal against the browser** - cell by cell. This is the render claim, and it
  is made against a real pty rather than a replay: three character-width tables are involved
  (rich's `cell_len` laid it out, `pyte` replays it, `xterm.js` draws it) and they do not
  share code.

`--strict` makes a runtime that could not be checked a failure, which is what CI wants.
{doc}`usage` has more on reading the output.

### What the render comparison assumes

That the screen is the same on both sides. It compares cells, and it cannot tell a font-width
bug from an app that drew something different — so an app whose content depends on the
network, on the clock, or on how fast a screen assembles will differ between legs for reasons
that have nothing to do with WASM.

Textual's own demo is the worked example: it fetches GitHub star counts and lazily assembles
its home screen, so its terminal and browser captures disagree on eleven rows while every cell
either side actually drew agrees. If your app is like that, point the check at a screen that
is deterministic - a start screen with fixed content, or a `--ready-marker` that only appears
once the variable parts have settled.
