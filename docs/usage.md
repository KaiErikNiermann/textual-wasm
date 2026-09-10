# Building applications

Everything the build does, and the choices it makes for you.

## What `build` produces

```console
$ textual-wasm build myapp.main:App myapp -o dist/
```

| Argument | |
|---|---|
| `myapp.main:App` | The application, as `module:AppClass` — the same form Textual's own runner accepts. |
| `myapp` | The **package directory** to copy. A single module has no directory to copy. |
| `-o dist/` | Where to write. |

## Applications whose `__init__` takes arguments

Every runtime here builds your app with `App()`. If yours needs arguments — a parsed
command line, a file path — point the entry at a **zero-argument factory** instead of the
class:

```python
# myapp/web.py
from argparse import Namespace

from myapp.main import Viewer


def make_app() -> Viewer:
    return Viewer(cli_args=Namespace(file=None))
```

```console
$ textual-wasm build myapp.web:make_app myapp -o dist/
```

This is common: of ten Textual applications surveyed on GitHub, two took required
constructor arguments. There is no browser command line to parse, so deciding those
defaults is something only you can do.

The output is nine files:

```
dist/
  index.html      the page
  main.mjs        boots Pyodide, creates the terminal, starts the app
  entry.py        resolves module:AppClass inside the runtime
  app.json        the manifest: entry, title, requirements, pinned CDN URLs
  sources.json    your package and textual_wasm, as source
  styles/         the page's stylesheet
```

**Python is shipped as source, not as wheels.** It costs a little size and buys two things
worth more: a dev server can serve straight from the working tree, and the browser
demonstrably runs the same files the other runtimes do — which is what the cross-runtime
comparison depends on.

### Size

A small app is about **240 KiB**, nearly all of it Textual's own source. The interpreter and
the terminal emulator are not in that number: Pyodide (~10 MB, cached by the browser after the
first visit) and xterm.js come from a pinned CDN. Adding your own code adds its source size and
nothing else.

## Dependencies

The build installs a dependency closure with `micropip` at page load, pinned to the versions
in **your** environment:

```console
$ textual-wasm pins            # writes wasm-requirements.txt
```

The closure is walked from installed metadata with **extras followed** — which matters more
than it sounds. `textual` depends on `markdown-it-py[linkify]`, and a list of distribution
names cannot express that extra. Its absence does not fail the install; it surfaces later as
Textual's own `Markdown` widget dying with `Linkify enabled but not installed`, three layers
from the list that was wrong.

Extra distributions your app needs:

```console
$ textual-wasm build myapp.main:App myapp -o dist/ -r httpx -r "pydantic>=2"
```

Whether a given package works at all is a question `doctor` answers:

```console
$ textual-wasm doctor myapp.main:App -r httpx -r cryptography
```

| State | Means |
|---|---|
| pure | Pure Python. Any version, straight from PyPI. |
| wasm wheel | Publishes a `pyemscripten` wasm wheel to PyPI. Any version. |
| bundled native | Pyodide ships a build. Works, but **pins you to Pyodide's version** — `cryptography` is three majors behind PyPI. |
| unavailable | No wasm build exists. `micropip.add_mock_package()` is sometimes the honest answer. |

## The page

The default page is deliberately bare: the terminal fills the viewport and nothing is drawn
around it. A Textual app already renders its own header, footer and title, so page chrome
would be a second frame competing with the one the app draws.

```console
$ textual-wasm build myapp.main:App myapp -o dist/ --title "My App"
```

`--title` names the document, defaulting to your application class. For anything more,
`--template` replaces part or all of the page — see {doc}`embedding`.

## Checking it behaves the same

```console
$ textual-wasm check --app myapp.main:App \
    --ready-marker "My App" --keys q --settled-marker "goodbye"
```

Four runtimes, two comparisons:

```
myapp.main:App at 80x24
┏━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ runtime  ┃ status ┃ detail             ┃
┡━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ native   │ ran    │ 8 checks, 0 failed │
│ wasm     │ ran    │ 0 check(s) failed  │
│ browser  │ ran    │ 24 rows rendered   │
│ terminal │ ran    │ tmux 3.7c          │
└──────────┴────────┴────────────────────┘
identical: terminal and browser render the same
equivalent across 4 runtime(s)
```

### The eight checks

Nothing is asked of your app: the probe schedules its own timer, reads the resize off the
`Screen` your app laid out, and judges input by what appears on the grid.

| Check | Settles |
|---|---|
| `import_purity` | No POSIX terminal module and no Textual platform driver was imported. |
| `driver_hook` | `TEXTUAL_DRIVER` selected the out-of-tree driver — the mechanism the whole project rests on. |
| `run_async` | `App.run_async()` completed on the host's event loop. |
| `resize_delivered` | The synthesised resize reached the widget tree. |
| `ansi_output` | The compositor emitted truecolor SGR, i.e. real terminal output. |
| `widget_rendered` | Your ready marker is on the grid. |
| `key_input` | Bytes through `XTermParser` changed the grid. Skipped when no keys are declared. |
| `timer` | `set_timer` fired, so asyncio timing works on that loop. |

### Reading a disagreement

**A check differs between native and wasm.** A real portability difference. The `detail`
column says what was observed on each side.

**A runtime fact differs.** Expected for `platform`, `python_version`, `event_loop`,
`threads_available`, `runtime`, `jspi`, `shared_memory` and `polyfills_applied` — those are
what the host change *is*. Anything else differing means the two runs were not comparable, and
is reported as unexpected. `textual_version` is the one that matters most.

**Rows differ between the terminal and the browser.** Either a character-width disagreement —
the report names the row and the column where they stop matching — or your app drew something
different. The second is more common than the first: the comparison assumes a **deterministic
screen**, and an app whose content depends on the network or the clock does not have one.
Point `check` at a screen that is stable, or use a ready marker that only appears once the
variable parts have settled.

:::{admonition} `--strict`
:class: tip

By default a runtime that cannot be checked here is reported as skipped and the rest still
produce a verdict — a check that fails for a missing tool teaches people to ignore its result.
`--strict` makes a skip a failure, which is what CI wants: a silently narrower check is the
thing you are trying to prevent.
:::

## Diagnostics at runtime

The built page installs guards before starting your app. They exist because Pyodide's most
dangerous failures raise nothing at all:

```python
os.system("ls")                      # returns 0, does nothing (in a browser)
await loop.run_in_executor(None, f)  # ignores the executor, runs inline on the only thread
time.sleep(2)                        # freezes the page for two seconds
```

Each becomes a loud, specific error or warning naming the substitute. And because Textual
prints tracebacks through a `Console(stderr=True)` — which under Pyodide is a browser console
nobody is watching — crash output is routed into the terminal the user is already looking at.

To do this yourself when hosting Pyodide some other way:

```python
from textual_wasm import diagnostics

diagnostics.install()
diagnostics.attach(app, driver)
```

The full list of what is guarded, translated or left alone is the {doc}`matrix`.
