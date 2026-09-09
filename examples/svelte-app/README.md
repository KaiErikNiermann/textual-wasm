# svelte-app

A Textual application running **inside a Svelte component**, with Svelte state and controls
around it.

```bash
poetry install
pnpm install

poetry run palette-app        # in a terminal
pnpm dev                      # in a browser, with Vite's reload
pnpm build && pnpm preview    # the static site
```

`pnpm build` does two things: `textual-wasm build` writes the application into
`public/terminal/`, and Vite builds the Svelte site around it. Vite never bundles the Python
— `public/` is copied through untouched — so the two toolchains do not have to know about
each other.

## How the component works

`src/lib/Terminal.svelte` is the whole integration:

```js
await import(new URL("terminal/main.mjs", document.baseURI).href);
while (globalThis.textualWasm === undefined) {
  await new Promise((resolve) => setTimeout(resolve, 100));
}
```

The import is dynamic and marked `@vite-ignore` because the file is served rather than
bundled. The build's own module resolves its manifest relative to *itself*, which is what
lets it sit at `/terminal/` while the page sits at `/` — a document-relative path would only
work if the build were the whole site.

Then the page drives the app the way a user would:

```js
globalThis.textualWasm.input("2");
```

Each theme button sends a number key. The application has bindings for those keys and repaints
itself; it has no JavaScript API, no message protocol, and no idea a framework is involved.
**The keyboard is the integration surface** — anything a user could do to a terminal app, a
page can do to it too.

## What is Svelte's and what is Python's

| | Owns |
|---|---|
| Svelte | the page, the layout, the buttons, `sent` and `current` state |
| Python | everything inside the terminal frame, including its theme |

The boundary is a single `input()` call in one direction. Nothing is shared, nothing is
serialised, and neither side can corrupt the other's state.

## The one rule

The element the terminal opens into carries **no padding or border of its own** — `FitAddon`
sizes the character grid from that element's parent box, so decoration on the mount is counted
as room for text and the bottom rows get drawn outside the frame. The component decorates
`.frame` and leaves `#terminal` bare.
