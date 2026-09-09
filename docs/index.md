# textual-wasm

Ship one [Textual](https://github.com/Textualize/textual) application as **both** a terminal
TUI and a client-side web page — same source, no server-side Python process, and no fork of
Textual.

```console
$ textual-wasm build myapp.main:App myapp -o dist/
built dist - 9 files, 240 KiB, 11 requirement(s)
$ textual-wasm dev dist/
serving dist on http://127.0.0.1:8000
```

The output is static files. Copy `dist/` to any static host and it works: there is no server,
no build toolchain at the far end, and nothing for the person deploying it to install. Pyodide
and xterm.js are fetched from a pinned CDN; your application is written into the page as
source.

:::{admonition} This documentation site is the proof
:class: tip

Every demo in the [examples gallery](examples.md) is a real build of a real Textual app,
running in your browser on this GitHub Pages site. GitHub Pages serves static files and
nothing else — which is exactly the claim.
:::

## Why this is possible at all

Textual's driver is an abstraction with an environment-variable hook —
`TEXTUAL_DRIVER=module:Symbol` — that was clearly built for out-of-tree drivers. Every
syscall lives in `textual/drivers/`, the entry point is fully awaitable, and the input parser
is pure synchronous Python. So a driver whose sink is an `xterm.js` terminal instead of a file
descriptor is the whole of it.

**Nothing here patches Textual.** The [feasibility study](study.md) is the audit that
established that, and §11–§14 are what the implementation measured against it.

## Start here

::::{grid} 1 1 2 2
:gutter: 2

:::{grid-item-card} {octicon}`rocket` Quickstart
:link: quickstart
:link-type: doc

A working web build of a new app in about five minutes.
:::

:::{grid-item-card} {octicon}`arrow-switch` Porting an existing app
:link: porting
:link-type: doc

What to change, in the order you will actually hit it.
:::

:::{grid-item-card} {octicon}`browser` Embedding
:link: embedding
:link-type: doc

Custom pages, and Textual inside Svelte, Vue or plain HTML.
:::

:::{grid-item-card} {octicon}`alert` Limitations
:link: limitations
:link-type: doc

What does not work, and whose constraint each one is.
:::
::::

## What the tool actually does

| Command | |
|---|---|
| `textual-wasm doctor <module:App>` | What will break, with a `file:line`. Reads imports, **call sites** and dependencies. |
| `textual-wasm build <module:App> <package> -o dist/` | A static site. |
| `textual-wasm dev dist/` | Serve it locally. Standard library only — no Node. |
| `textual-wasm check --app <module:App>` | Run the app on every runtime available and compare them. |

`check` is the unusual one. It runs your application natively on CPython, under Pyodide in
Node, in a real Chrome, and on a real pty through tmux — then compares the Python runtimes
check by check and the real terminal against the browser **cell by cell**. A runtime this
machine cannot reach is reported as skipped with the command that would enable it.

```{toctree}
:hidden:
:caption: Getting started

installation
quickstart
usage
```

```{toctree}
:hidden:
:caption: Going further

porting
embedding
examples
```

```{toctree}
:hidden:
:caption: Reference

limitations
matrix
cli
study
```
