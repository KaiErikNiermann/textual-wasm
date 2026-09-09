# Web Workers

By default your application shares a thread with the page. `textual-wasm build --worker` moves
it to a Web Worker instead.

```console
$ textual-wasm build myapp.main:App myapp -o dist/ --worker
built dist - 10 files, 248 KiB, 11 requirement(s)
python runs in a Web Worker; no COOP/COEP headers required
```

Nothing about your application changes. The driver talks to the same four-member host
contract either way; in worker mode that contract is satisfied over `postMessage` instead of
by direct call.

## What it fixes

Pyodide has no threads. A Python call that takes a second is a second in which nothing else
on that thread runs — and when that thread is the page's, the whole tab is frozen: no
scrolling, no animation, no other component doing anything.

Measured against [`tests/blocking_app.py`](https://github.com/KaiErikNiermann/textual-wasm/blob/main/tests/blocking_app.py),
which spends about a second in a synchronous loop, sampling `requestAnimationFrame` on the
main thread throughout:

| Build | Longest gap between frames |
|---|---|
| default (main thread) | **1333 ms** |
| `--worker` | **16.8 ms** |

16.8 ms is one frame at 60 Hz — the page never stopped painting. The measurement is the
longest gap rather than a frame count on purpose: over a window longer than the blocking call,
a frame count dilutes a real stall into a healthy-looking average. The first version of this
measurement reported "340 frames rendered" for a build that had frozen for a third of a second.

`textual-wasm check --worker` runs the full four-runtime comparison against a worker build, so
"renders identically" is checked rather than assumed, on all three engines, on every commit.

## What it does not fix

**It does not make Python faster.** The work takes just as long. The freeze moves off the
thread the user can see, which is the entire benefit and the whole of it.

**It does not give you threads.** `sys._emscripten_info.pthreads` is `False` inside a worker
exactly as it is on the main thread — Pyodide is not built with `-pthread`, and its ABI
forbids it in linked libraries. `@work(thread=True)` is unavailable in either mode. Use
`@work` without `thread=True`, which is cooperative and works normally.

**It does not need — or benefit from — cross-origin isolation.** No COOP/COEP headers, so a
worker build deploys to GitHub Pages and every other header-less static host, exactly like the
default. `SharedArrayBuffer` would only be needed to *block* the worker waiting on main-thread
input, and Textual never does: its input path is a queue an async loop drains, so a message
arriving whenever it arrives is already the right shape.

## Which to choose

Use the default when your app is mostly waiting on the user. It is one fewer moving part, and
the boot path is shorter.

Use `--worker` when any of these is true:

- Something in your app blocks for longer than a frame — parsing a large file, a tight loop,
  a big `on_mount`.
- The page has other content around the terminal. A frozen tab is much more obvious when
  there is a sidebar or a form next to it that stops responding too. See
  [embedding](embedding.md).
- You are mounting the terminal inside a framework component whose own reactivity shares the
  main thread — the [Svelte example](examples.md) is the case in point.

## Writing a custom page for worker mode

The [template contract](embedding.md) is unchanged: an element with `id="terminal"` and a
module script loading `./main.mjs`. `main.mjs` reads the `worker` flag out of `app.json` and
starts the worker itself, so a template written for the default build works in worker mode
with no edit.

Two host capabilities are forwarded back to the page, because a worker has neither `window`
nor `document`:

- `App.open_url()` — becomes `window.open` on the page's thread.
- Textual's file delivery — becomes a download-triggering anchor on the page's thread.

If you register your **own** host object rather than using the shipped page, those two are
optional members of the contract:

```js
{
  write(text), onData(callback), onResize(callback), cols, rows,   // required
  openUrl(url, newTab), deliverFile(href, filename),               // optional
}
```

Omitting them is fine on the main thread, where the driver falls back to the page's own
globals. In a worker there is nothing to fall back to, so a host that omits them will raise
when the application tries to open a link.
