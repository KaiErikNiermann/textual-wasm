# Command reference

Every command takes `--help`. This page is the map.

## `textual-wasm doctor`

```console
$ textual-wasm doctor <module:App | path> [-r DISTRIBUTION]...
```

Reports what will behave differently under Pyodide, before you run it there: imports, **call
sites** for the failures that raise nothing, and dependency classification. Exits non-zero on
anything blocking — a silent failure, a fatal call, an absent module, or a dependency with no
wasm build. Things that raise honestly are reported but do not fail the run; the app will tell
you about those itself.

A finding you have considered can be marked in place, and the reason is required:

```python
time.sleep(0.5)  # textual-wasm: allow time.sleep - CLI-only path, never reached in a browser
```

## `textual-wasm build`

```console
$ textual-wasm build <module:App> <package> [-o dist/] [--title T] [--template DIR] [--worker] [-r DIST]...
```

Writes a self-contained static site. See {doc}`usage` and {doc}`embedding`.

`--worker` runs the interpreter in a Web Worker so a slow call does not freeze the page. It
needs no special headers and deploys to the same static hosts. See {doc}`workers`.

## `textual-wasm dev`

```console
$ textual-wasm dev [dist/] [-p PORT]
```

Serves a build on loopback with caching off. The standard library's own server — a development
server is not a deployment target.

## `textual-wasm check`

```console
$ textual-wasm check [--app module:App] [--ready-marker T] [--keys K] [--settled-marker T]
                     [--width N] [--height N] [--browser ENGINE] [--worker] [--strict]
```

Runs the app on every runtime available and compares them. See {doc}`usage`.

`--worker` builds the browser leg to run Python in a Web Worker. The render must come out
identical, so this is the same comparison rather than a weaker one — see {doc}`workers`.

## `textual-wasm pins`

```console
$ textual-wasm pins [--output wasm-requirements.txt]
```

Regenerates the WASM dependency closure from the installed native environment, walking
extras. Generated rather than hand-written because two runtimes are only comparable when they
load the same code.

## `textual-wasm matrix`

```console
$ textual-wasm matrix [-o docs/porting-matrix.md] [--check]
```

Renders the {doc}`matrix` from the substitution registry. `--check` exits non-zero when the
file on disk is out of date, which is the CI form.

## The individual legs

`check` runs these for you; they exist separately for when you want one.

| | |
|---|---|
| `probe` | Run the eight checks natively and print a report (`--json` for the machine-readable form). |
| `compare` | Diff two probe reports. |
| `capture-terminal` | Render the app in a real terminal via tmux and emit the grid as JSON. |
| `compare-screens` | Diff two grids, reporting the row and the column at which they stop matching. |
| `schema` | Print the check ids a report can contain. |
