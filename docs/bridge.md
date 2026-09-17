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

## Typing the channel, on both sides

Everything above types the *payload* in Python and nothing at all on the page:
`bridge.send("gian", value)` is valid JavaScript, valid Python, and a message nobody
receives. Declaring the channels closes that, and generates the page's types from the
declaration rather than asking anyone to keep two files in step.

```python
# myapp/channels.py
from typing import Literal, TypedDict

from textual_wasm.channels import Channel

type LevelName = Literal["gain", "bass", "treble"]


class Clipping(TypedDict):
    threshold: int
    hot: list[LevelName]


GAIN: Channel[int] = Channel("gain")
CLIPPING: Channel[Clipping] = Channel("clipping")
```

```console
$ textual-wasm channels myapp.channels -o page/channels.d.ts
```

```ts
export type LevelName = "gain" | "bass" | "treble";

export interface Clipping {
  threshold: number;
  hot: LevelName[];
}

export interface Channels {
  gain: number;
  clipping: Clipping;
}

export interface Bridge {
  send<K extends ChannelName>(channel: K, value: Channels[K]): void;
  on<K extends ChannelName>(channel: K, callback: (value: Channels[K]) => void): () => void;
  sendText(channel: string, text: string): void;
  onText(channel: string, callback: (text: string) => void): () => void;
  codec: Codec;
}
```

The mapped type is the part worth generating. A channel name that does not exist and a
payload of the wrong shape are both type errors at the call site:

```text
error TS2345: Argument of type '"clippping"' is not assignable to parameter of
type 'keyof Channels'.
```

The generated file also types the rest of `globalThis.textualWasm`, so there is one file to
reference rather than two.

### Using it from a plain page

A `.d.ts` has nothing to load at runtime, so a page imports it as types only:

```js
/**
 * @typedef {import("./channels.js").TextualWasm} TextualWasm
 * @typedef {import("./channels.js").ChannelName} ChannelName
 */
```

and is checked with `tsc --noEmit` over a `tsconfig.json` with `allowJs` and `checkJs`. The
[`page-bridge`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/page-bridge)
example ships one; a bundled TypeScript project imports the same names normally instead.

### The declaration carries only a name

```python
GAIN: Channel[int] = Channel("gain")   # the payload type is in the annotation
```

Not `Channel("gain", int)`, and that is worth being explicit about because the more obvious
form quietly stops working. A `payload: type[T]` field means `type[SomeTypedDict]`, which is
not a valid type — pyright stops solving `T` and **every** `send` passes, including the wrong
ones. The annotation is where the type goes.

A `Channel` assigned without one is an error rather than a channel silently missing from the
generated file.

### What a payload may contain

Whatever survives `json.dumps` and `json.loads` unchanged: `str`, `int`, `float`, `bool`,
`None`, `Literal`, `list`, `tuple`, `dict[str, …]`, unions, `TypedDict`, a `type X = …` alias,
and an `Enum` whose members are strings or numbers. Anything else is refused by name, with a
suggestion:

```text
bytes cannot cross a JSON channel; base64 it into a str, or use the raw pipe and skip
the codec
```

`TypedDict` rather than a dataclass on purpose: a TypedDict **is** the decoded object, so
nothing has to be structured back into a class on arrival and no serialisation library has to
be chosen for you. A payload that needs real validation swaps the codec instead.

:::{note}
`int` and `float` both become `number`. JSON has one numeric type and TypeScript has no
integer type, so a generated `integer` would be a claim neither runtime can enforce.
:::

### Keeping it honest

`--check` exits non-zero when the committed file no longer matches the declarations, which is
the only thing that makes a generated file worth trusting:

```console
$ textual-wasm channels myapp.channels --check -o page/channels.d.ts
page/channels.d.ts is out of date; run `textual-wasm channels myapp.channels -o page/channels.d.ts`
```

Run it in CI beside your other checks. Without it, a page goes on type-checking green against
channels the application stopped sending — which is worse than having no generated file,
because it reads as proof.

### JSON Schema, for everything else

`--schema` emits the same model as JSON Schema 2020-12:

```console
$ textual-wasm channels myapp.channels --schema -o page/channels.schema.json
```

Both outputs come off one walk of the Python types, so they cannot describe two different
things. Use it for runtime validation at the page's edge, or to feed a generator for a
language this does not emit — `datamodel-codegen` and `json-schema-to-typescript` both read
it directly.

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
