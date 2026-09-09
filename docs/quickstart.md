# Quickstart

A Textual app in a browser, from nothing, in about five minutes. If you already have an app,
read {doc}`porting` instead — this page assumes you are starting fresh.

## 1. A project

`build` copies a **package directory**, so the app has to live in one. A single `.py` file is
not enough to reconstruct the import path.

```console
$ mkdir -p hello/hello_app && cd hello
$ python -m venv .venv && source .venv/bin/activate
$ pip install textual textual-wasm
```

```python
# hello_app/app.py
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label


class Hello(App[None]):
    TITLE = "Hello"
    BINDINGS = [Binding("space", "cheer", "Cheer")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Press space.", id="message")
        yield Footer()

    def action_cheer(self) -> None:
        self.query_one("#message", Label).update("Hello from WebAssembly.")
```

```python
# hello_app/__init__.py
from hello_app.app import Hello

__all__ = ["Hello"]
```

Run it the ordinary way first, so you know the app itself works:

```console
$ python -c "from hello_app.app import Hello; Hello().run()"
```

## 2. Ask what will break

```console
$ textual-wasm doctor hello_app.app:Hello
no source findings
no blocking issues
```

Worth doing before the build rather than after, because the failures this catches are the ones
that do **not** raise — `os.system()` returning 0 and doing nothing, `run_in_executor` quietly
running inline on the only thread. See {doc}`limitations`.

## 3. Build and serve

```console
$ textual-wasm build hello_app.app:Hello hello_app -o dist/
built dist - 9 files, 240 KiB, 11 requirement(s)
packages: textual_wasm, hello_app
pyodide 314.0.6 from CDN
serve it with: textual-wasm dev dist

$ textual-wasm dev dist/
serving dist on http://127.0.0.1:8000
```

Open it. Pyodide takes a few seconds on the first load — it is fetching a CPython interpreter —
and the page says so while it does. After that the app is running in the tab.

:::{tip}
`dev` is the standard library's own HTTP server. Requiring Node to look at static files would
undo the point of a Python tool that builds a static site.
:::

## 4. Deploy it

`dist/` is finished. There is no further build step.

```console
$ ls dist/
app.json  entry.py  index.html  main.mjs  sources.json  styles/
```

Copy it to GitHub Pages, S3, Netlify, or a directory on any web server. Two things to know:

- **Serve `.wasm` as `application/wasm`.** Most hosts do; a few old configurations do not, and
  the failure is a message about the MIME type rather than a 404.
- **No COOP/COEP headers are needed.** The default build is main-thread only precisely so the
  simplest deployment works. See {doc}`limitations` for what that costs.

## 5. Check that it really behaves the same

```console
$ textual-wasm check --app hello_app.app:Hello \
    --ready-marker "Press space." --keys space --settled-marker "Hello from WebAssembly."
```

The three markers are how a machine knows what it is looking at: text that means the app has
drawn, keystrokes to send, and text that means those keystrokes were handled. Without the last
one a capture races the app and sometimes reads the screen from before the keypress.

What comes back is a runtime-by-runtime table and two comparisons — the Python runtimes check
by check, and a real terminal against the browser cell by cell. {doc}`usage` explains what to
do when a row disagrees.

## Where to go next

- {doc}`usage` — the build in depth: titles, custom pages, dependencies, sizes.
- {doc}`embedding` — putting the terminal inside a page you already have.
- {doc}`examples` — three complete projects, running live on this site.
