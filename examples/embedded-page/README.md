# embedded-page

A Textual application as **one component of a page**, with HTML controls driving it.

```bash
poetry install
poetry run dashboard-app                       # in a terminal

poetry run textual-wasm build dashboard_app.app:Dashboard dashboard_app \
  -o dist/ --title "A terminal in a page" --template page
poetry run textual-wasm dev dist/              # http://127.0.0.1:8000
```

## What it shows

**Embedding.** `page/index.html` is an article with headings, prose and a code block; the
terminal sits inside it in a sized box rather than filling the viewport. A character grid
needs a real block size to be measured against, so the frame is given one (`24rem`) —
`height: auto` would collapse it to nothing.

**Control from outside.** The buttons next to the terminal are ordinary HTML:

```js
globalThis.textualWasm.input("2");
```

That is xterm's own user-input entry point, so the application receives a keystroke and
cannot tell a button from a keyboard. The app exposes no JavaScript API and knows nothing
about the page — the seam is the keyboard, which every terminal app already has.

`globalThis.textualWasm` appears once the app is running and carries `input()`, `screen()`,
`columns`, `rows` and a `finished` promise. `page/controls.mjs` waits for it rather than
assuming it, because it arrives seconds after the page does.

**Styling without a fight.** `page/styles/embed.css` puts every rule in the `overrides`
layer that the shipped stylesheet declares and leaves empty, and takes every value from the
tokens the page already ships. Nothing is out-specified and no `!important` appears.

## The one rule a custom page must follow

The element the terminal opens into — `id="terminal"` — carries **no padding or border of its
own**. `FitAddon` sizes the grid from that element's parent box, so decoration on the mount
is counted as room for text and the bottom rows are drawn outside the visible area. Decorate
a wrapper, as `page/` does with `.terminal-frame`.
