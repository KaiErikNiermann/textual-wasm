# textual-wasm

Ship one Textual application as both a terminal TUI and a client-side web page.

The web page is static files. There is no server-side Python process, no build toolchain at
the far end, and nothing for the person deploying it to install. Pyodide and xterm.js come
from a pinned CDN; your application is copied in as source.

Textual itself is unmodified. The whole extension point is a public one -
`TEXTUAL_DRIVER=module:Symbol` - so there is no fork to maintain and no patch to rebase.

## Start here

```bash
pip install textual-wasm

textual-wasm doctor myapp.main:App     # what will break, before you run it anywhere
textual-wasm build myapp.main:App myapp -o dist/
textual-wasm dev dist/                 # http://127.0.0.1:8000
```

And, when you want the claim checked rather than asserted:

```bash
textual-wasm check --app myapp.main:App --ready-marker "My App" --keys q --settled-marker "bye"
```

That runs your app on every runtime this machine can offer - CPython, Pyodide under Node, a
real Chrome, and a real terminal through tmux - and compares them. Runtimes it cannot reach
are reported as skipped, with the command that would enable them.

## The documents

- [`examples/simple-app`](../examples/simple-app) - a complete, self-contained app that runs
  both ways, with its own `pyproject.toml` and linting. The fastest way in.
- [Porting guide](./porting-guide.md) - what to change, in the order you will hit it.
- [Porting matrix](./porting-matrix.md) - every measured behavioural difference, generated
  from the registry the tools themselves read.
- [Feasibility study](../textual-wasm-feasability-study.md) - the architecture audit, and
  what the spike actually measured.

## What this is not

It is not a way to run *any* Python in a browser unchanged. Threads, subprocesses and raw
sockets do not exist there and cannot be emulated; the porting matrix says so per capability,
and `doctor` finds them in your source. What this project does is make that list short,
knowable in advance, and loud at runtime rather than silent.
