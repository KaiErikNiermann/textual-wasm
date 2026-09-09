# Installation

```console
$ pip install textual-wasm
```

That is enough for `doctor`, `build` and `dev` — the three commands most people need. It
brings Textual, Rich and a small pure-Python closure with it, and nothing that has to be
compiled.

:::{note}
Until the first PyPI release, install from the repository:

```console
$ pip install git+https://github.com/KaiErikNiermann/textual-wasm
```
:::

## Python version

**3.12 or newer** on your development machine. Note this is separate from the interpreter your
app runs on in a browser, which is whatever CPython the pinned Pyodide ships — 3.14 at
present. `textual-wasm check` reports both, and a difference between them is expected rather
than a problem:

```
platform          linux        emscripten
python_version    3.14.7       3.14.2
event_loop        _UnixSelector…  WebLoop
```

## Optional tools, and what each one buys

Nothing below is needed to build or serve a site. Each unlocks one leg of
`textual-wasm check`, and a leg that cannot run is reported as skipped with the command that
would enable it — never as a failure.

| Tool | Unlocks | Install |
|---|---|---|
| `tmux` | The **real-terminal reference**: your app on a real pty through Textual's own driver, which is what the browser render is judged against. | `apt install tmux` / `pacman -S tmux` / `brew install tmux` |
| Node + `pyodide` | The **WASM leg**: the same probe under Pyodide, headless and CI-able. | `pnpm add -D pyodide` |
| Node + `playwright` | The **browser leg**: a real build, served by a real dev server, rendered by a real browser engine. | `pnpm add -D playwright` then `pnpm exec playwright install chromium firefox webkit` |

The npm packages are resolved by walking up from your working directory the way Node itself
would, so a single `node_modules` at the root of a monorepo serves every project in it.

Playwright's engines are downloaded separately from the package, which is why there are two
commands. `--browser chrome` and `--browser msedge` drive the browsers already installed on
your machine instead, and need no download at all — see {doc}`browsers`.

:::{admonition} Why tmux, specifically
:class: dropdown

It is the only terminal emulator that will hand its screen back as text. `capture-pane` is
what makes "does the browser render this the same way a terminal does" a mechanical question
rather than an opinion — and the answer has already been surprising once, when the *reference*
implementation turned out to be the wrong one. See {doc}`study` §12.3.
:::

## For working on textual-wasm itself

```console
$ git clone https://github.com/KaiErikNiermann/textual-wasm
$ cd textual-wasm
$ poetry install
$ pnpm install                       # only for the wasm and browser legs
$ git config core.hooksPath .githooks
$ poetry run pytest
```

The pre-push hook runs ruff, pyright in strict mode, radon, semgrep and the test suite. CI
runs the same gates on the floor and ceiling of the supported Python range, plus the full
four-runtime check with `--strict`.
