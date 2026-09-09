# simple-app

A Textual task list that runs in a terminal **and** in a browser, from one source tree.

```
simple_app/
  app.py      the whole application - ordinary Textual, no WASM awareness
  app.tcss    its stylesheet, shipped to the browser alongside the Python
```

Copy this directory somewhere and it works on its own. It is a normal Poetry project whose
only runtime dependency is `textual`; `textual-wasm` is a **development** dependency, because
it is a build tool rather than something the app imports.

## Run it in a terminal

```bash
poetry install
poetry run simple-app        # or: poetry run python -m simple_app
```

`a` adds a task, `d` removes the last one, `q` quits.

## Run it in a browser

```bash
poetry run textual-wasm build simple_app.app:TaskList simple_app -o dist/
poetry run textual-wasm dev dist/            # http://127.0.0.1:8000
```

`dist/` is static files. Copy it to any static host — GitHub Pages, S3, a directory on a web
server — and it works with no Python on the far side. Pyodide and xterm.js are fetched from a
pinned CDN, and this app's `.py` and `.tcss` are written into the page's own filesystem.

Nothing in `simple_app/` changed between those two commands, and nothing in it imports
`textual_wasm`. That is the whole point of the example.

The page is bare - the terminal fills the viewport and nothing is drawn around it, because
this app already draws its own header and footer. Two levers if you want otherwise:

```bash
poetry run textual-wasm build simple_app.app:TaskList simple_app -o dist-framed/ \
  --title "Tasks" --template page
```

`--title` names the browser tab (it defaults to the class name, `TaskList`). `--template` is
a directory copied over the built page: `page/` here holds an `index.html` with a heading and
a framed terminal, and a stylesheet that lands in the empty `overrides` layer the shipped CSS
declares - so it changes the design without out-specifying it.

The contract a replacement page has to satisfy is small: an element with `id="terminal"` for
the terminal to open into, **with no padding or border of its own** (`FitAddon` sizes the
grid from that element's parent, so decoration on the mount is counted as room for text and
the bottom rows get clipped - decorate a wrapper, as `page/` does), and a module script
loading `./main.mjs`. An `id="status"` element is optional and receives boot progress.

## Check that both really behave the same

```bash
poetry run textual-wasm check \
  --app simple_app.app:TaskList \
  --ready-marker Tasks --keys aa --settled-marker "Task 2"
```

That boots the app on every runtime the machine has — CPython, Pyodide under Node, a real
Chrome, and a real terminal through tmux — and compares them: the Python runtimes check by
check, and the terminal against the browser cell by cell. Runtimes it cannot reach are
reported as skipped with the command that would enable them, so this is useful output on a
machine with none of the optional tools installed.

The three markers are how a harness knows what it is looking at: `--ready-marker` is text
that means the app has drawn, `--keys` are literal keystrokes, and `--settled-marker` is text
that means those keystrokes were handled. Without the last one a capture races the app and
sometimes reads the screen from before the keypress.

## Before you port a bigger app

```bash
poetry run textual-wasm doctor simple_app.app:TaskList
```

The doctor reads the source and reports what will behave differently under Pyodide, with a
`file:line` for each — including the failures that raise nothing at all, like `time.sleep()`
blocking the whole page or `run_in_executor` silently running inline. This app is clean, which
is the other reason it is worth reading: it shows what "portable" looks like.

## Why this app is shaped the way it is

Two constraints, both so the check above is meaningful:

- **The screen is deterministic.** No clock, no network, no animation. The check diffs the
  rendered grid, and it cannot tell a font-width bug from an app that drew something else.
- **Every change is keyboard-driven**, so a harness can put the app in a known state and know
  when it got there.

Real apps are not always like this. When yours is not, point `check` at a screen that is —
a start screen with fixed content, or a ready marker that only appears once the variable
parts have settled.

## Linting

```bash
poetry run ruff check . && poetry run ruff format --check .
poetry run pyright
```

`pyproject.toml` carries a small ruff selection and pyright in strict mode. It is a starting
point rather than a house style — the rules there are the ones that catch real mistakes in a
Textual app.
