# textual-wasm

[![pypi](https://img.shields.io/pypi/v/textual-wasm)](https://pypi.org/project/textual-wasm/)
[![ci](https://github.com/KaiErikNiermann/textual-wasm/actions/workflows/ci.yml/badge.svg)](https://github.com/KaiErikNiermann/textual-wasm/actions/workflows/ci.yml)
[![docs](https://github.com/KaiErikNiermann/textual-wasm/actions/workflows/pages.yml/badge.svg)](https://kaierikniermann.github.io/textual-wasm/)
[![python](https://img.shields.io/badge/python-3.12%2B-blue)](https://kaierikniermann.github.io/textual-wasm/installation.html)
[![license](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

Ship one [Textual](https://github.com/Textualize/textual) application as **both** a terminal
TUI and a fully client-side web page — same source, no server-side Python process, no fork of
Textual.

**[Documentation](https://kaierikniermann.github.io/textual-wasm/)** ·
**[Live demos](https://kaierikniermann.github.io/textual-wasm/examples.html)** ·
**[Porting guide](https://kaierikniermann.github.io/textual-wasm/porting.html)**

```bash
textual-wasm build myapp.main:App myapp -o dist/   # a static directory
textual-wasm dev dist/                             # http://127.0.0.1:8000
```

The output is static files. Pyodide and xterm.js come from a pinned CDN; your application is
copied in as source. There is no build toolchain at the far end and nothing for the person
deploying it to install.

Textual itself is untouched. The extension point is a public one —
`TEXTUAL_DRIVER=module:Symbol` (`textual/app.py:1585`) — so there is no patch to rebase.

## The four commands

| | |
|---|---|
| `textual-wasm doctor <module:App>` | What will break, with a `file:line`. Reads imports, **call sites**, and dependencies. |
| `textual-wasm build <module:App> <package> -o dist/` | A static site. Bare page by default; `--title` and `--template` if you want otherwise. `--storage` for a persistent filesystem. Refuses a closure Pyodide cannot install. |
| `textual-wasm dev dist/` | Serve it locally. Standard library only. |
| `textual-wasm check --app <module:App>` | Run it on every runtime available and compare. |

## What `check` actually checks

Four runtimes, and two comparisons that mean something:

| Leg | Runtime | Settles |
|---|---|---|
| native | CPython | The baseline. |
| wasm | Pyodide under Node | Everything on the Python side, in CI, with no browser. |
| browser | Chromium, Firefox **and** WebKit over a real `build` | Rendering, and whether the engines agree. |
| terminal | a real pty via tmux, on Textual's own driver | What a user would actually see. |

`native` against `wasm` is compared check-by-check, fact-by-fact and grid-by-grid.
`terminal` against `browser` is compared cell-by-cell — that one is the render claim, and it
is made against a real terminal rather than a replay because three different character-width
tables are involved and they do not share code.

A runtime this machine cannot reach is reported as **skipped, with the command that would
enable it**, and the rest still produce a verdict. `--strict` makes a skip a failure, which
is what CI wants.

```
textual_wasm.app:SpikeApp at 80x24
┏━━━━━━━━━━┳━━━━━━━━━┳──────────────────────────────────────┓
┃ runtime  ┃ status  ┃ detail                               ┃
┡━━━━━━━━━━╇━━━━━━━━━╇──────────────────────────────────────┩
│ native   │ ran     │ 8 checks, 0 failed                   │
│ wasm     │ ran     │ 0 check(s) failed                    │
│ browser  │ ran     │ 19 rows rendered                     │
│ terminal │ ran     │ tmux 3.7c                            │
└──────────┴─────────┴──────────────────────────────────────┘
identical: terminal and browser render the same
equivalent across 4 runtime(s)
```

Nothing the probe measures is asked of your app: the timer is scheduled by the probe, the
resize is read back off the `Screen` it laid out, and input is judged by what appears on the
grid. An app that has never heard of this project is measured by exactly the code that
measures the one that ships with it.

## Diagnostics

Pyodide's most dangerous failures are the ones that raise nothing. `os.system()` returns 0
and does nothing; `loop.run_in_executor()` ignores the executor and runs inline on the only
thread, so code written to keep a UI responsive freezes the page instead.

`textual_wasm.diagnostics.install()` manufactures a loud, specific failure for each, naming
the substitute. `diagnostics.attach(app, driver)` moves crash output off stderr — which under
Pyodide is a browser console nobody is watching — and into the terminal the user is looking
at. The build output does both for you.

Every one of those claims is **measured, not transcribed**, and the
[porting matrix](./docs/porting-matrix.md) is generated from the same registry the analyser
and the guards read. A test fails when it drifts; a characterisation suite re-measures the
registry inside a real Pyodide. Pyodide's own documentation lists four modules as removed
that import fine in 314.0.6, which is what a hand-maintained table gets you.

## Documentation

The [documentation site](https://kaierikniermann.github.io/textual-wasm/) is itself the proof:
every demo on it is a real build of a real Textual app, running in your browser, served as
static files by GitHub Pages.

- [Quickstart](https://kaierikniermann.github.io/textual-wasm/quickstart.html) — a new app in a
  browser in five minutes.
- [Porting guide](https://kaierikniermann.github.io/textual-wasm/porting.html) — moving an app
  you already have.
- [Embedding](https://kaierikniermann.github.io/textual-wasm/embedding.html) — custom pages,
  and Textual inside Svelte, Vue or plain HTML.
- [Limitations](https://kaierikniermann.github.io/textual-wasm/limitations.html) — what does
  not work, organised by *whose* constraint each one is.
- [Browser support](https://kaierikniermann.github.io/textual-wasm/browsers.html) — measured
  across three engines, and what that measurement does not cover.
- [Managing persistent storage](https://kaierikniermann.github.io/textual-wasm/storage.html) —
  why `localStorage` is the wrong answer (a Web Worker does not have it) and why you need no
  storage abstraction at all.
- [Library support](https://kaierikniermann.github.io/textual-wasm/library-support.html) — 37
  Textual add-ons installed into a real Pyodide and mounted; 23 can be shipped today.
- [Feasibility study](./textual-wasm-feasability-study.md) — the architecture audit, what the
  spike measured, and the claims it corrected.

### Examples

| | |
|---|---|
| [`simple-app`](./examples/simple-app) | A task list. The smallest complete thing. |
| [`embedded-page`](./examples/embedded-page) | The terminal as one component of an article, driven by HTML buttons. |
| [`svelte-app`](./examples/svelte-app) | Mounted in a Svelte 5 component, with Svelte state around it. |
| [`persistent-notes`](./examples/persistent-notes) | A SQLite database that survives a page reload. One code path, one extra `flush()`. |
| [`addon-gallery`](./examples/addon-gallery) | Four third-party Textual libraries, none of which knows it is in a browser. |

Each is a self-contained project with its own `pyproject.toml`, README and linting — copy one
out and it works.

## How the pieces fit

```
bootstrap.py   TEXTUAL_* env, applied before the first `import textual` (it caches at import)
polyfills.py   runtime bugs, quarantined and reported
driver.py      WasmDriverBase  ->  CaptureDriver (sink: a list)
browser.py     WasmDriverBase  ->  BrowserDriver (sink: xterm.js)
target.py      which app, and how a harness knows it drew
probe.py       the experiment, over any app
check.py       every runtime this machine has, and the comparisons
substitutions  the registry: one source for the analyser, the guards and the docs
```

Nothing in the probe, the driver, the app or the report may branch on `sys.platform` — a
semgrep rule enforces it. Runtime differences are confined to `polyfills.py` and recorded in
the report, so a WASM run can never look accidentally native.

## Development

```bash
poetry install
pnpm install                                 # only for the wasm and browser legs of `check`
poetry run pytest                            # includes a selftest of the semgrep rules
pnpm lint:all                                # eslint (css + js), stylelint, principled-css
poetry run textual-wasm pins                 # regenerate wasm-requirements.txt
poetry run textual-wasm matrix -o docs/porting-matrix.md
git config core.hooksPath .githooks          # lint, types, complexity, policy, tests
./scripts/run-spike.sh                       # the whole matrix, strictly
```
