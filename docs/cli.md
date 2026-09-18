# Command reference

Every command takes `--help`. This page is the map.

## `textual-wasm doctor`

```console
textual-wasm doctor <module:App | path> [-r DISTRIBUTION]...
```

Reports what will behave differently under Pyodide, before you run it there: imports, **call
sites** for the failures that raise nothing, dependency classification, and whether the
requirements can coexist *with each other*. That last one catches the quietest failure in the
add-on ecosystem: a library that caps Textual below your version installs perfectly well,
because micropip resolves Textual *down* to suit it. Exits non-zero on
anything blocking — a silent failure, a fatal call, an absent module, or a dependency with no
wasm build. Things that raise a clear error are reported but do not fail the run; the
app will report those itself.

A finding you have considered can be marked in place, and the reason is required:

```python
time.sleep(0.5)  # textual-wasm: allow time.sleep - CLI-only path, never reached in a browser
```

## `textual-wasm build`

```console
textual-wasm build <module:App> <package> [-o dist/] [--title T] [--template DIR]
                   [--worker] [--storage] [--no-check-dependencies] [-r DIST]...
```

Writes a self-contained static site. See {doc}`usage` and {doc}`embedding`.

`--worker` runs the interpreter in a Web Worker so a slow call does not freeze the page. It
needs no special headers and deploys to the same static hosts. See {doc}`workers`.

`--storage` mounts a persistent filesystem (IndexedDB, via IDBFS) at `/persist`, which is
what `textual_wasm.storage` writes into. Off by default: it adds a round trip to boot, and an
app that writes nothing should not ask a user's browser for storage. See {doc}`storage`.

The build **checks its resolved closure and refuses** to write a site that would die during
`micropip.install` in someone else's browser. Two different failures:

- a native dependency pinned to a version Pyodide does not have — `pandas<=2.2.3` against its
  bundled 3.0.2. This half reads Pyodide's package set, so it needs the vendored runtime.
- a requirement that contradicts another in the closure — an add-on capping `textual<6.0.0`
  against a build pinning 8.2.8. This half needs no lock file and always runs. It is the more
  important of the two, because micropip would otherwise *succeed* by downgrading Textual.

`--no-check-dependencies` skips the first. Where no local Pyodide exists to read a package set
from, the build reports that it did not check.

## `textual-wasm dev`

```console
textual-wasm dev [dist/] [-p PORT]
```

Serves a build on loopback with caching off. The standard library's own server — a development
server is not a deployment target.

## `textual-wasm check`

```console
textual-wasm check [--app module:App] [--ready-marker T] [--keys K] [--settled-marker T]
                   [--width N] [--height N] [--browser ENGINE] [--worker]
                   [-r DISTRIBUTION]... [--strict]
```

Runs the app on every runtime available and compares them. See {doc}`usage`.

`-r` names a distribution your app needs, installed by `micropip` in the runtimes that
install anything. Without it an app that depends on more than Textual fails to import under
Pyodide, which is most applications.

`--worker` builds the browser leg to run Python in a Web Worker. The render must come out
identical, so this is the same comparison, not a weaker one — see {doc}`workers`.

## `textual-wasm pins`

```console
textual-wasm pins [--output wasm-requirements.txt]
```

Regenerates the WASM dependency closure from the installed native environment, walking
extras. It is generated because two runtimes are only comparable when they load the same
code.

## `textual-wasm matrix`

```console
textual-wasm matrix [-o docs/porting-matrix.md] [--check]
```

Renders the {doc}`matrix` from the substitution registry. `--check` exits non-zero when the
file on disk is out of date, which is the CI form.

## `textual-wasm libraries`

```console
textual-wasm libraries [-o docs/library-table.md] [--check]
```

Renders {doc}`library-support` from the ecosystem registry — which third-party Textual
add-ons work in a browser, measured by installing each into a real Pyodide and mounting its
widgets. `--check` is the CI form, same as `matrix`.

## `textual-wasm channels`

```console
textual-wasm channels MODULE [-o page/channels.d.ts] [--path DIR] [--schema] [--check]
```

Renders TypeScript declarations for every channel an application declares, so the page can
be type-checked against the same source the application sends from. See
{doc}`bridge` for the declaration side.

`--path` names a directory to import from, for an application package that is not installed —
the same package `build` reads straight off disk. `--schema` emits JSON Schema instead, from
the same walk of the types, for runtime validation or a different generator. `--check` is the
CI form, same as `matrix`.

## The individual legs

`check` runs these for you; they exist separately for when you want one.

| | |
|---|---|
| `probe` | Run the checks natively and print a report (`--json` for the machine-readable form). |
| `compare` | Diff two probe reports. |
| `capture-terminal` | Render the app in a real terminal via tmux and emit the grid as JSON. |
| `compare-screens` | Diff two grids, reporting the row and the column at which they stop matching. |
| `schema` | Print the check ids a report can contain. |
