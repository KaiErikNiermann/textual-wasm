# page-bridge

Live state shared **both ways** between a Textual application and the page around it.

```bash
poetry install
poetry run mixer-app                           # in a terminal, channel inert

poetry run textual-wasm build mixer_app.app:Mixer mixer_app \
  -o dist/ --title "Mixer" --template page --worker
poetry run textual-wasm dev dist/              # http://127.0.0.1:8000
```

## What it shows

The sliders are HTML `<input type="range">`. The meters are the Textual app. Neither owns the
levels: drag a slider and the meter follows, press the arrow keys in the terminal and the
slider follows.

That is the thing [`embedded-page`](../embedded-page) cannot do. Its integration is
`terminal.input("2")` — a keystroke, which is exactly right for a button meaning "press 2"
and no answer at all for a value. There is no keyboard spelling of "gain is now 63", and no
keystroke the application can send back when it changes a level itself.

**Binding a value is one line per side.** In the app:

```python
self.bridge = Bridge.connect(self)
self.bridge.bind("gain", self, "gain")
```

and on the page:

```js
bridge.on("gain", (value) => { slider.value = value; });
slider.addEventListener("input", () => bridge.send("gain", Number(slider.value)));
```

A value the page just sent is not echoed back to it, so those two do not fight.

**The application talks first.** The `clipping` channel has no control behind it — nothing on
the page can send on it. It is the app saying "gain is over 85", which before the bridge could
only be had by scraping the rendered grid. `bind(initial=True)` publishes each level on mount,
which is *before* a page polling for `globalThis.textualWasm` can have subscribed; the page's
relay holds those until a listener appears, which is why the sliders snap into step on load
rather than sitting at whatever the markup declared.

**Both layers.** The levels and the clipping report travel through the codec (JSON by
default). The `note` field uses `sendText`/`message.text` — the pipe with nothing on top,
because a line of prose is already a string and JSON-encoding it so the other side can decode
it back is ceremony.

**It still runs in a terminal.** `poetry run mixer-app` is the same source with no branch in
it. `Bridge.connect` on a runtime with no page returns a bridge whose `available` is False and
whose sends go nowhere; the app prints "no page: running in a terminal" and works.

**The mode does not matter.** This builds with `--worker`, so the interpreter runs in a Web
Worker and the channel crosses a `postMessage` boundary instead of a direct call. Drop the
flag and nothing in `mixer_app/` or `page/` changes — that parity is asserted in
`tests/test_bridge_browser.py`, which runs one harness against both builds and compares them.

## Styling

`page/styles/mixer.css` puts every rule in the `overrides` layer the shipped stylesheet
declares and leaves empty, takes every value from the tokens the page already ships, and
reads the clipping state off a `data-state` attribute rather than a class toggled from
JavaScript.
