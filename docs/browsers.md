# Browser support

Measured, on the same day, against the same build: the
[`simple-app` demo](examples.md), forced to an 80×24 grid, diffed **cell by cell** against the
same application running in a real terminal.

| Engine | Version | Renders identically to a terminal | JSPI | Notes |
|---|---|---|---|---|
| Chromium | 153 | yes | yes | Chrome, Edge, Brave, Opera, Arc — one engine |
| Firefox | 155 | yes | yes | |
| WebKit | 26.6 | yes | yes | Playwright's build; see the Safari caveat below |
| Safari | — | not yet reported | — | Checked weekly on macOS; see below |

No page errors, no failed requests, and no divergent rows in any of them. `SharedArrayBuffer`
is unavailable in all three, which is expected and fine: the default build is main-thread only
precisely so that no COOP/COEP headers are needed.

## What is checked, and how

Every push runs `textual-wasm check --strict --browser <engine>` for all three engines. Each
one builds the app, serves it, boots Pyodide in that browser, sends a keystroke, reads the
grid back, and diffs it against a capture from a real pty running the same app through
Textual's own driver.

```console
$ textual-wasm check --browser firefox
│ browser  │ ran    │ firefox 155.0, 19 rows rendered │
│ terminal │ ran    │ tmux 3.5a                       │
identical: terminal and browser render the same
```

You can point it at the browser you actually ship to:

| `--browser` | Drives |
|---|---|
| `chromium`, `firefox`, `webkit` | Playwright's own builds. Reproducible; what CI runs. |
| `chrome`, `msedge` | The browser **installed on your machine**, through Playwright's channels. |
| `safari` | Real Safari through `safaridriver`. macOS only, and needs `sudo safaridriver --enable` once. |

:::{important}
## What this does *not* cover

The comparison reads **xterm.js's buffer**, not pixels — and xterm.js's character-width logic
is the same JavaScript in every browser. So cell *assignment* is engine-independent by
construction, and a green row here does not mean the glyphs were drawn identically.

What multi-engine testing genuinely catches is everything around that: whether Pyodide boots,
whether the page's JavaScript works, which capabilities each engine reports, and how fast each
one gets there. What it cannot catch is a font rendering wider than the cell it was assigned.
That is a property of the font and the platform's text stack, not of the engine, and covering
it would need pixel comparison — which is flaky enough across engines to be worth less than it
costs.
:::

## Why Edge is not in the matrix

It is Chromium, running the same `xterm.js`. Testing it would measure the same renderer twice
and report the result as though it were independent evidence. The same goes for Brave, Opera,
Arc and Vivaldi.

`--browser msedge` exists if you want to run it against your installed copy — for a policy or
enterprise-configuration question, where the browser really is different — but it is not part
of the matrix, and the reason is stated here rather than left as a silent omission.

## Safari, and why it is a weekly job

**Playwright's WebKit is not Safari.** It is a different port of the same engine, built
against GTK on Linux, with a different font stack and none of Apple's platform limits. It
answers "does this engine run the page", which is most of what matters — and it cannot answer
the two questions that are specifically Safari's:

- **The font fallback**, which decides how a glyph is drawn when the pinned stack is absent.
- **The WebAssembly memory ceiling**, which on iOS in particular is real and which a ~10 MB
  interpreter has to fit inside.

So real Safari runs on a macOS runner **once a week** rather than on every pull request.
`safaridriver` is the flakiest link in this whole matrix and macOS runners are slow; a gate
people learn to re-run is worse than no gate. A failure there is a signal to investigate, not
a blocked merge.

That leg is new and has not yet reported. This page will carry its result rather than an
assumption — if you are relying on Safari today, run it yourself:

```console
$ sudo safaridriver --enable
$ textual-wasm check --browser safari --app myapp.main:App
```

## Mobile

Untested, and worth saying plainly rather than implying by omission. A Textual app in a
mobile browser has two problems that are not about this project: there is no physical
keyboard, and iOS applies a tighter WebAssembly memory ceiling than desktop Safari. The
terminal renders; whether an app is *usable* that way is a question about the app.

## Requirements

Whatever the engine, a host has to serve `.wasm` as `application/wasm` and support
WebAssembly with BigInt integration — which every browser in the table above has done for
years. No cross-origin isolation, no special headers, no service worker.
