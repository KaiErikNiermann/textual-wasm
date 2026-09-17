# The data channel

A page can already drive an application by sending it keystrokes, which is the right answer
for a button meaning "press 2" and no answer at all for a value. There is no keyboard spelling
of *gain is now 63*, and no keystroke an application can send **back** when it changes
something itself.

`textual_wasm.bridge` is the channel for everything the keyboard is the wrong shape for.

```python
from textual_wasm.bridge import Bridge

class Mixer(App[None]):
    gain = reactive(40)

    def on_mount(self) -> None:
        self.bridge = Bridge.connect(self)
        self.bridge.bind("gain", self, "gain")
```

```js
const { bridge } = globalThis.textualWasm;

bridge.on("gain", (value) => { slider.value = value; });
slider.addEventListener("input", () => bridge.send("gain", Number(slider.value)));
```

That is the whole of a two-way binding. The slider moves the reactive, the reactive moves the
slider, and neither side is the owner.

## Three layers

Each one is usable without the one above it. Reach for the lowest that answers the question.

| | Python | Page |
|---|---|---|
| **pipe** — text on a named channel | `send_text(channel, text)` / `message.text` | `sendText(channel, text)` / `onText(channel, cb)` |
| **codec** — a value, JSON by default | `send(channel, value)` / `message.data` | `send(channel, value)` / `on(channel, cb)` |
| **bind** — a reactive kept in step | `bind(channel, node, attribute)` | — |

The pipe has no opinion about what the text means, which is the point: a protocol this module
has never heard of is one it cannot get in the way of. If you want msgpack in base64, a line
of CSV, or your own message envelope, send it as text and this layer stays out of it.

## Receiving

Everything the page sends arrives as a `BridgeMessage` through Textual's own message pump —
not a callback, so it works the way receiving from a widget already does:

```python
from textual import on
from textual_wasm.bridge import BridgeMessage

def on_bridge_message(self, message: BridgeMessage) -> None:
    if message.channel == "filter":
        self.apply(message.data)
```

`message.text` is exactly what crossed the wire. `message.data` is that text through the
codec, decoded once and cached. A payload the codec cannot read raises where `data` is read,
not where the message arrived — the pipe does not pretend bad text is an empty value, and
`text` survives either way for a handler that wants to recover.

Binding a channel does not consume it. A bound value is applied *and* posted, so an
application can bind a level and still react to its arrival.

## Structure, without inventing a format

`Codec` is two methods:

```python
class Codec(Protocol):
    def encode(self, value: object) -> str: ...
    def decode(self, text: str) -> object: ...
```

The default is `json`, because both runtimes already have one and neither side needs a
dependency. Swapping it is a three-line class rather than a fork:

```python
class Models:
    def encode(self, value: object) -> str:
        return cast(BaseModel, value).model_dump_json()

    def decode(self, text: str) -> object:
        return Levels.model_validate_json(text)

self.bridge = Bridge.connect(self, codec=Models())
```

`message.data` is typed `object` because a codec's output is only as specific as the codec,
and claiming otherwise would put a `cast` in every handler. For a typed payload, reach past it
and hand `message.text` to something that returns a model:

```python
levels = Levels.model_validate_json(message.text)   # pydantic
levels = converter.loads(message.text, Levels)      # cattrs
```

The page's codec is a property, so a project speaking something else replaces it once:

```js
globalThis.textualWasm.bridge.codec = { encode: pack, decode: unpack };
```

## Timing, and why the first message is not lost

`globalThis.textualWasm` appears only once the app is driving the terminal, so a page
necessarily subscribes *after* the application has started — and `bind(initial=True)` sends
during `on_mount`, which is earlier than that. A page that polls at 100ms intervals would miss
it every time on a fast machine and catch it on a slow one.

Both ends therefore hold messages for a receiver that has not arrived yet: 128 of them, oldest
dropped, with one warning if nothing ever subscribes. That is what makes a slider snap into
step on load rather than sitting at whatever its markup declared.

It is a starting gap, not a durable buffer. A page filling it is talking to something that is
never going to answer.

## In a terminal

An application written against the bridge still runs in a terminal, with no branch in it:

```python
self.bridge = Bridge.connect(self)   # no page: available is False
self.bridge.send("levels", payload)  # encodes, then drops
```

`available` says whether there is a page at the other end. It does not claim anything is
*listening* — that is the page's business, and an app that waited for a listener before
drawing would never draw in a terminal.

Encoding happens whether or not anyone is there. That costs a `json.dumps` on a terminal and
buys the thing worth having: a value the codec cannot render fails in every runtime rather
than only in a browser, where the exception lands in a console nobody has open.

## Main thread and worker

The channel behaves identically in both, and that is asserted rather than asserted-about:
`tests/test_bridge_browser.py` runs one harness against both builds and compares the results
to each other. `--worker` is meant to be a performance flag; the moment it changes what an
application can say to its page, it is an API flag.

Which is why the wire carries **text** rather than arbitrary values. On the main thread Python
could be handed a live `JsProxy`; in a worker the identical call arrives as a structured
clone. Those differ in proxy lifetime, in whether a mutation is visible to the other side, and
in whether a function survives the trip. A string crosses both as itself.

## Writing your own page

The contract is two members, and `boot.mjs` registers one satisfying it in every browser
build — there is no flag, because an application that never sends anything pays nothing for
the object existing.

```js
{ send(channel, text), subscribe(callback) }     // what Python is handed
```

A page using the shipped `main.mjs` gets the other side for free on
`globalThis.textualWasm.bridge`:

| Member | |
|---|---|
| `send(channel, value)` | Encode with the codec and send. |
| `sendText(channel, text)` | Send as-is. |
| `on(channel, callback)` | Receive decoded. Returns an unsubscribe function. |
| `onText(channel, callback)` | Receive raw. Returns an unsubscribe function. |
| `codec` | `{ encode, decode }`, JSON by default. Replaceable. |

## The complete example

[`examples/page-bridge`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/page-bridge)
is a mixer with three HTML sliders and three Textual meters over the same three values, a
clipping report the page has no control for, and a text field on the raw pipe. It is live in
{doc}`examples`.
