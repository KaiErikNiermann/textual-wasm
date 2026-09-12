# Examples

Five complete projects, each self-contained enough to copy out of the repository and use.
The demos below are **live**: every one is a real build of the app beside it, running in your
browser on this static site.

:::{note}
The first load of each demo fetches a CPython interpreter (~10 MB, then cached by your
browser), so give it a few seconds. That cost is Pyodide's, paid once per visitor.
:::

---

## A terminal app on the web

[`examples/simple-app`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/simple-app)
— a task list. The smallest complete thing: an ordinary Textual app, a `.tcss` stylesheet, and
nothing else.

```{raw} html
<iframe class="demo-frame" src="demos/simple/" title="A Textual task list running in the browser" loading="lazy"></iframe>
```

**What it shows.** The default page: the terminal fills its box and nothing is drawn around
it. The app imports nothing from `textual_wasm` and does not branch on the platform — shipping
it to a browser is a build step, not a port.

Its stylesheet is a real `.tcss` file rather than a `CSS` string on purpose: a stylesheet left
behind by the build fails at *mount time* in the browser and nowhere earlier, so the example is
what proves it ships.

```console
$ poetry run simple-app                                             # a terminal
$ textual-wasm build simple_app.app:TaskList simple_app -o dist/    # a web page
```

---

## A terminal inside a page

[`examples/embedded-page`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/embedded-page)
— the same idea, but the terminal is one component of an article with headings, prose and
controls of its own.

```{raw} html
<iframe class="demo-frame" src="demos/embedded/" title="A Textual app embedded in an HTML article" loading="lazy"></iframe>
```

**What it shows.** `--template` replacing the whole page, and HTML buttons driving the
application:

```js
globalThis.textualWasm.input("2");
```

That is xterm's own user-input entry point, so the app receives a keystroke and cannot tell a
button from a keyboard. It exposes no JavaScript API and knows nothing about the page. See
{doc}`embedding`.

Its stylesheet lands in the `overrides` cascade layer the shipped CSS declares and leaves
empty, so it restyles the page without out-specifying anything.

---

## A terminal inside a Svelte component

[`examples/svelte-app`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/svelte-app)
— Svelte 5 and Vite, with the Textual app mounted in a component and Svelte state around it.

```{raw} html
<iframe class="demo-frame" src="demos/svelte/" title="A Textual app inside a Svelte component" loading="lazy"></iframe>
```

**What it shows.** Two toolchains that never have to know about each other:

```console
$ textual-wasm build palette_app.app:Palette palette_app -o public/terminal
$ vite build
```

Vite copies `public/` through untouched — it never sees the Python — and the build's entry
module resolves its manifest relative to itself, which is what lets it live at `/terminal/`
while the Svelte page lives at `/`.

The buttons send number keys, and the Textual app switches its own **theme** in response:
every widget in the frame repaints, and none of that is the page's doing. The boundary is a
single `input()` call in one direction.

| | Owns |
|---|---|
| Svelte | the page, the layout, the buttons, its own reactive state |
| Python | everything inside the terminal, including its theme |

The same shape works in Vue's `onMounted` or React's `useEffect`; nothing about it is
Svelte-specific.

---

## Storage that survives a reload

[`examples/persistent-notes`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/persistent-notes)
— a notebook backed by a real **SQLite** database, with a real schema and real queries,
persisting across page reloads.

**What it shows.** That a browser needs no storage abstraction. Pyodide can mount IndexedDB
*as a filesystem*, so `sqlite3.connect(...)` works in a page and persists — and a `Store`
protocol with two backends would be a worse reimplementation of that, without SQL.

What genuinely differs is *when* a write becomes durable, so the app calls one extra method:

```python
store = Store.open("persistent-notes")
connection = sqlite3.connect(store.path("notes.db"))   # the one line that differs
...
await store.flush()                                     # no-op natively
```

```console
$ textual-wasm build notes_app.app:Notes notes_app -o dist/ --storage --worker
```

Build it *without* `--storage` and the app says so in its own banner rather than silently
forgetting. Measured across Chromium and Firefox, main thread and Web Worker: a note written,
the page reloaded, the note still there — in all four combinations. {doc}`storage` is the
full account, including why `localStorage` is the wrong answer (a Web Worker does not have
it).

---

## Four third-party libraries in one page

[`examples/addon-gallery`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/addon-gallery)
— a signal explorer built from `textual-autocomplete`, `textual-plotext`, `textual-plot` and
`textual-slider`.

**What it shows.** That the add-on ecosystem works, and that **none of these libraries knows
it is in a browser** — no shim, no conditional import, no vendored fork. Four packages off
PyPI, installed by `micropip` at boot.

The part that makes it work is not in the application at all:

```console
$ textual-wasm build gallery_app.app:Gallery gallery_app -o dist/ --worker \
    -r textual-autocomplete -r textual-plotext -r textual-plot -r textual-slider
```

A missing `-r` produces a page that fetches a 10 MB interpreter, boots it, and *then* fails on
the first import — so `textual-wasm doctor -r <dist>` belongs before the build, not after the
deploy.

Two plotting libraries side by side on identical data, because they are the two options in
the ecosystem. {doc}`library-support` is the survey these four were picked from: 37 libraries
installed into a real Pyodide and mounted, of which 23 can be shipped today.

---

## Textual's own demo

Not shipped as an example, but worth knowing: `python -m textual` — lazily-loaded screens, a
Markdown widget, a command palette, network calls — runs unmodified.

```console
$ textual-wasm check --app textual.demo.demo_app:DemoApp \
    --ready-marker "What is Textual?" --width 100 --height 30
```

All eight checks pass on both Python runtimes. Pointing the tool at it found two real bugs in
*this* project, which is what an acceptance case is for; {doc}`study` §14 has the account.
