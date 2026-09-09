# Embedding and page customisation

The built page is yours. This chapter covers three levels of taking it over: naming it,
replacing it, and putting the terminal inside an application you already have.

## Level 1 — a title

```console
$ textual-wasm build myapp.main:App myapp -o dist/ --title "My App"
```

Defaults to your application class name. The page has no heading of its own, so this is the
browser tab and nothing else.

## Level 2 — your own page

```console
$ textual-wasm build myapp.main:App myapp -o dist/ --template page/
```

`--template` is a **directory copied over the built page**. Anything in it wins over the
shipped asset of the same name, so replacing `index.html` alone is a one-file directory.

A directory rather than a set of options on purpose: what people want to change is a
*document*, and every option that tries to parameterise a document ends up reinventing a worse
templating language.

### The contract

:::{important}
Three requirements, and the first is not style advice.

1. **An element with `id="terminal"`, carrying no padding or border of its own.** `FitAddon`
   sizes the character grid from that element's *parent* box, so decoration on the mount is
   counted as room for text and the bottom rows — where Textual draws its footer — are
   rendered outside the visible area. Decorate a wrapper.
2. **`<script type="module" src="./main.mjs"></script>`.**
3. Optionally an element with `id="status"`. It receives boot progress and a `data-state` of
   `booting`, `ready` or `failed`. Without one those messages go to the console.
:::

A minimal template:

```html
<body>
  <div class="frame">        <!-- decorate this -->
    <div id="terminal"></div><!-- never this -->
  </div>
  <script type="module" src="./main.mjs"></script>
</body>
```

### Styling without a specificity fight

The shipped stylesheet declares its cascade layers up front and leaves an `overrides` layer
empty:

```css
@layer reset, tokens, base, layout, overrides;
```

A template's stylesheet that puts its rules in `@layer overrides` wins by **position** rather
than by out-specifying anything — no `!important`, no escalating selectors. The design tokens
(`--space-3`, `--color-edge`, `--font-terminal`, …) are already defined, so a custom page can
consume them instead of inventing new values.

```css
@layer overrides {
  .frame {
    border: var(--space-1) solid var(--color-edge);
    border-radius: var(--radius-2);
    padding: var(--space-3);
  }
}
```

## Level 3 — a component of your own application

A build is a directory of static files that can be served from **anywhere on your site**. Its
entry module resolves the manifest relative to itself, so `/terminal/main.mjs` finds
`/terminal/app.json` while your page lives at `/`.

```js
await import("/terminal/main.mjs");   // boots into <div id="terminal">
```

The import resolves as soon as the app is running, not when it exits — you can `await` it.

### Driving the app from the page

```js
globalThis.textualWasm.input("2");
```

That is xterm's own *user input* entry point. The application receives a keystroke and cannot
tell a button from a keyboard, which means **the keyboard is the integration surface**: your
app needs no JavaScript API, no message protocol, and no awareness that a page is involved.
Anything a user could do to a terminal app, a page can do to it.

`globalThis.textualWasm` appears once the app is driving the terminal and carries:

| Member | |
|---|---|
| `input(data)` | Send keystrokes, as if typed. |
| `screen()` | The visible grid: `{ columns, rows, lines }`. |
| `columns`, `rows` | The grid size chosen at boot. |
| `finished` | A promise that resolves when the app exits. |

It appears *seconds* after your page does — Pyodide has to boot a CPython interpreter — so
poll for it rather than assuming it:

```js
while (globalThis.textualWasm === undefined) {
  await new Promise((resolve) => setTimeout(resolve, 100));
}
```

### In a framework

```text
<script>
  import { onMount } from "svelte";

  let terminal = $state();

  onMount(async () => {
    await import(/* @vite-ignore */ new URL("terminal/main.mjs", document.baseURI).href);
    while (globalThis.textualWasm === undefined) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    terminal = globalThis.textualWasm;
  });
</script>

<div class="frame"><div id="terminal"></div></div>
<button onclick={() => terminal?.input("2")}>nord</button>
```

The `@vite-ignore` matters: the file is served from `public/`, not built from source, so there
is no module graph for the bundler to follow. The same shape works in Vue's `onMounted`,
React's `useEffect`, or a plain `DOMContentLoaded` listener — nothing here is Svelte-specific.

The complete project is in {doc}`examples`, including the two build steps that never have to
know about each other:

```console
$ textual-wasm build palette_app.app:Palette palette_app -o public/terminal
$ vite build
```

### Two things a host page should define

```css
:root {
  --font-terminal: "IBM Plex Mono", ui-monospace, monospace;
  --color-terminal-bg: #14171f;
}
```

Both have fallbacks, so omitting them is not an error. But the font is what decides how wide a
character cell is, so it is worth being deliberate about — and it is the one setting that can
make a render subtly wrong rather than obviously broken.

### Sizing

A character grid needs a real block size to be measured against. `height: auto` on the frame
collapses it to nothing:

```css
.frame { block-size: 26rem; }   /* or 1fr in a grid, or 100dvb for full-bleed */
```

The terminal refits itself when the container resizes — a `ResizeObserver`, not a window
listener, because the terminal's size is a fact about its box.
