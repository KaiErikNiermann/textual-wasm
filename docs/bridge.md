# The data channel

A page can already drive an application by sending it keystrokes. That is the right answer
for a button meaning "press 2" and no answer at all for a value: there is no keyboard spelling
of *gain is now 63*, and no keystroke an application can send **back** when it changes
something itself.

`textual_wasm.bridge` is the channel for values.

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

That is a complete two-way binding. The slider moves the reactive, the reactive moves the
slider, and neither side owns the value.

## Three layers

Each layer works without the one above it. Use the lowest that answers the question.

| | Python | Page |
|---|---|---|
| **pipe** — text on a named channel | `send_text(channel, text)` / `message.text` | `sendText(channel, text)` / `onText(channel, cb)` |
| **codec** — a value, JSON by default | `send(channel, value)` / `message.data` | `send(channel, value)` / `on(channel, cb)` |
| **bind** — a reactive kept in step | `bind(channel, node, attribute)` | — |

The pipe attaches no meaning to the text it carries. That is deliberate: a protocol this
module has never heard of is one it cannot obstruct. Msgpack in base64, a line of CSV, another
project's message envelope — send any of them as text and this layer stays out of the way.

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
codec, decoded once and cached. A payload the codec cannot read raises at the point `data` is
read, not at the point the message arrived. Bad text never becomes an empty value, and `text`
survives either way for a handler that wants to recover.

Binding a channel does not consume it. A bound value is applied *and* posted, so an
application can bind a level and still react to its arrival.

## Structure, without inventing a format

`Codec` is two methods:

```python
class Codec(Protocol):
    def encode(self, value: object) -> str: ...
    def decode(self, text: str) -> object: ...
```

The default is `json`, because both runtimes already have one and neither side needs a new
dependency. Replacing it takes a three-line class:

```python
class Models:
    def encode(self, value: object) -> str:
        return cast(BaseModel, value).model_dump_json()

    def decode(self, text: str) -> object:
        return Levels.model_validate_json(text)

self.bridge = Bridge.connect(self, codec=Models())
```

`message.data` is typed `object`, because a codec's output is only as specific as the codec
and claiming more would put a `cast` in every handler. For a typed payload, skip `data` and
hand `message.text` to something that returns a model:

```python
levels = Levels.model_validate_json(message.text)   # pydantic
levels = converter.loads(message.text, Levels)      # cattrs
```

The page's codec is a property, so a project speaking something else replaces it once:

```js
globalThis.textualWasm.bridge.codec = { encode: pack, decode: unpack };
```

## Timing, and why the first message is not lost

`globalThis.textualWasm` appears only once the app is driving the terminal, so a page always
subscribes *after* the application has started. But `bind(initial=True)` sends during
`on_mount`, which is earlier. A page polling at 100 ms intervals would miss that first value
on a fast machine and catch it on a slow one.

Both ends therefore hold messages for a receiver that has not arrived yet: 128 of them, oldest
dropped, with one warning if nothing ever subscribes. That is what makes a slider snap into
step on load instead of sitting at whatever its markup declared.

The queue covers the gap at startup and nothing more. A page that fills it is talking to
something that will never answer.

## In a terminal

An application written against the bridge still runs in a terminal, with no branch in it:

```python
self.bridge = Bridge.connect(self)   # no page: available is False
self.bridge.send("levels", payload)  # encodes, then drops
```

`available` says whether there is a page at the other end. It does not claim anything is
*listening*; that is the page's business, and an app that waited for a listener before drawing
would never draw in a terminal.

Encoding happens whether or not anyone is there. The cost is one `json.dumps` per send on a
terminal. The benefit is that a value the codec cannot render fails in every runtime, instead
of failing only in a browser where the exception lands in an unwatched console.

(typing-the-channel)=
## Typing the channel, on both sides

Everything above types the *payload* in Python and nothing at all on the page.
`bridge.send("gian", value)` is valid JavaScript, valid Python, and a message that reaches
no one. Declaring the channels closes that gap, and generates the page's types from the same
declaration, so there are never two files to keep in step.

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
textual-wasm channels myapp.channels -o page/channels.d.ts
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

The mapped type is the part worth generating. An unknown channel name and a payload of the
wrong shape are both type errors at the call site:

```text
error TS2345: Argument of type '"clippping"' is not assignable to parameter of
type 'keyof Channels'.
```

The generated file also types the rest of `globalThis.textualWasm`, so a page references
one file and not two.

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
example ships one. A bundled TypeScript project imports the same names directly.

### The declaration carries only a name

```python
GAIN: Channel[int] = Channel("gain")   # the payload type is in the annotation
```

Not `Channel("gain", int)`. The more obvious form silently stops working: a
`payload: type[T]` field means `type[SomeTypedDict]`, and that is not a valid type, so pyright
gives up on solving `T` and **every** `send` passes, wrong ones included. The type goes in the
annotation.

A `Channel` assigned without an annotation raises. The alternative is a channel that works at
runtime and is silently missing from the generated file.

### What a payload may contain

Whatever survives `json.dumps` and `json.loads` unchanged: `str`, `int`, `float`, `bool`,
`None`, `Literal`, `list`, `tuple`, `dict[str, …]`, unions, `TypedDict`, a `type X = …` alias,
and an `Enum` whose members are strings or numbers. Anything else is refused by name, with a
suggestion:

```text
bytes cannot cross a JSON channel; base64 it into a str, or use the raw pipe and skip
the codec
```

`TypedDict` and not a dataclass, deliberately. A TypedDict **is** the decoded object, so
nothing has to be rebuilt into a class on arrival and this project picks no serialisation
library on your behalf. A payload that needs real validation replaces the codec instead.

:::{note}
`int` and `float` both become `number`. JSON has one numeric type and TypeScript has no
integer type, so a generated `integer` would be a claim neither runtime can enforce.
:::

### Keeping it honest

`--check` exits non-zero when the committed file no longer matches the declarations. That
check is what makes a generated file worth trusting:

```console
$ textual-wasm channels myapp.channels --check -o page/channels.d.ts
page/channels.d.ts is out of date; run `textual-wasm channels myapp.channels -o page/channels.d.ts`
```

Run it in CI beside the other checks. Without it, a page keeps type-checking green against
channels the application no longer sends. That is worse than having no generated file at all,
because it looks like proof.

### JSON Schema, for everything else

`--schema` emits the same model as JSON Schema 2020-12:

```console
textual-wasm channels myapp.channels --schema -o page/channels.schema.json
```

Both outputs come from one walk of the Python types, so they cannot describe two different
things. Use the schema for runtime validation at the page's edge, or to feed a generator for a
language this tool does not emit; `datamodel-codegen` and `json-schema-to-typescript` both
read it directly.

## When something goes wrong

The design rule is one sentence: **a bad value fails where it was written, not on the far
side.** A failure that crosses the boundary unnoticed lands in an unwatched browser console
and says nothing about what sent it.

Every case below is asserted end to end, in Chromium and Firefox, by
`tests/test_bridge_errors.py`.

### The application never dies

Nothing a page can send stops the app. A malformed payload on a bound channel is dropped and
logged with the channel name; the attribute keeps its old value and the next good message
applies normally. The `BridgeMessage` is posted either way, so a handler that wants the raw
text still gets it.

### Errors name their channel

```text
BridgePayloadError: could not decode the payload on channel 'levels':
Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
```

`BridgePayloadError` is raised in both directions: by `message.data` for text the codec
cannot read, and by `send` for a value it cannot render. It subclasses `ValueError` and keeps
the original error as `__cause__`.

### What cannot be sent

| From | Refused | Because |
|---|---|---|
| Python | `float("nan")`, `float("inf")` | `json.dumps` writes the bare token `NaN`, and `JSON.parse("NaN")` throws. The codec passes `allow_nan=False`. This is the one place it is stricter than the standard library. |
| Python | anything `json` cannot render | `BridgePayloadError`, naming the channel |
| Page | `send(channel, undefined)` | `JSON.stringify(undefined)` is `undefined`, not a string |
| Page | `sendText(channel, <not a string>)` | coercion would turn `String(undefined)` into data that looks real |

The page-side refusals throw a `TypeError` at the call site, so the stack still points at the
caller.

### A page can change what type a reactive holds

This one is easy to miss:

```python
gain: reactive[int] = reactive(0)
self.bridge.bind("gain", self, "gain")     # no validator
```

```js
bridge.send("gain", "loud");               // gain is now the string "loud"
```

Textual's reactives are not checked at runtime. The annotation is documentation, and the
page decides the type. The failure then surfaces wherever the application next does arithmetic
on the value, a long way from the channel that caused it.

Without a validator, `bind` warns once per binding when the type changes, so the corruption is
at least visible. The fix is one argument:

```python
self.bridge.bind("gain", self, "gain", validate=int)
```

Anything callable works — a converter, a range clamp, a model validator:

```python
self.bridge.bind("gain", self, "gain", validate=lambda v: max(0, min(100, int(v))))
self.bridge.bind("levels", self, "levels", validate=TypeAdapter(Levels).validate_python)
```

A rejected value is logged and the attribute is left alone. **Pass a validator for any
channel a page can reach.** Declaring channels with {ref}`Channel <typing-the-channel>` types
the page and stops honest mistakes. It does not stop a page that lies.

### What is not checked

The raw pipe carries what it is given. An escape sequence, a null byte, a right-to-left
override and an astral-plane emoji all survive a round trip unchanged, and the test suite
asserts it. Channel names are not validated either: any string is a channel, including the
empty one.

That is the pipe doing its job. A page handling untrusted input should put a validating codec
in front of the channel; this layer will not do it for them.

## What it costs, and where it stops

Measured on a desktop machine through Playwright's Chromium 153 and Firefox 155, against a
build with the interpreter in a Web Worker. Absolute numbers vary by machine. The ratios
below do not.

| | Chromium | Firefox |
|---|---|---|
| Round trip, page → app → page | 0.1 ms median, 0.2 ms p95 | under 1 ms |
| 10,000 small messages, app drains | 148 ms | 193 ms |
| 1 MB payload, round trip | 4 ms | similar |
| 8 MB payload, round trip | 32 ms | similar |
| 200,000 messages, all received | yes | yes |

A single value crossing costs about a tenth of a millisecond. A slider dragged at 60 Hz uses
roughly a thousandth of the channel's capacity. **For a control a person operates, the cost is
negligible.** The rest of this section is about the cases where it is not.

### There is no backpressure

`send` returns as soon as the value is queued. The queue lives in the receiving runtime, and
nothing anywhere tells a fast sender to slow down.

The gap between the two sides is large. Measured: a page pushes **200,000 messages in
162 ms**, and the application takes **2.7 seconds** to consume them. Sending is seventeen
times faster than receiving, so the cost of a burst is not the time spent sending it. The cost
is the backlog afterwards, during which the application drains the queue and its own work
waits.

```text
page:  |==| 162ms of sending
app:   |==============================| 2.7s of draining
```

The ceiling is about **75,000 messages a second** into the application. That ceiling belongs
to Python, not to the channel: the same burst takes the same time on a terminal. `--worker`
does not raise it, because moving the work to another thread does not reduce how much there
is.

Three cases, in order of concern:

- **A control a person operates** — a slider, a colour picker, a text field. Negligible.
- **An animation loop or a sensor at 60 Hz** — about 0.1% of capacity. Negligible.
- **Ticks, samples or events at kHz rates** — a backlog builds. Batch them into one message
  per frame, or use `sendLatest`.

### `sendLatest`, for state that arrives faster than it is used

```js
bridge.sendLatest("gain", Number(slider.value));
```

At most one value per channel per frame, keeping the newest and dropping the rest. Measured:
20,000 calls in a synchronous loop arrive as **one** message.

Dropping is wrong for an event stream and right for a value that is only ever rendered, since
the application would have drawn the last one and discarded the rest. The two are separate
methods for that reason: `send` never drops anything.

There is no Python-side equivalent, deliberately. An application sending faster than a page
can paint is not a problem that occurs, because the page's listener is a function call rather
than a queue.

### Large payloads are fine, and are copied

About 3.5 ms per megabyte, round trip, in both engines. Every payload is copied at each
boundary — `JSON.stringify`, the structured clone into the worker, `json.loads` — so an 8 MB
message costs several 8 MB allocations before it is a Python object. One per frame is far too
many. One when a file is dropped costs nothing worth measuring.

### Nothing accumulates

Checked with forced collection between rounds, in both modes: after 25,000 messages the
page's heap is where it started — 27,000 KB to 27,004 KB on the main thread, 3,045 KB to
3,047 KB in a worker. Neither side retains anything per message. The startup queue described
above holds at most 128 messages, and only until something subscribes.

### The main thread still stalls

With the interpreter on the main thread, a burst of 5,000 messages blocks it for **33 ms in
Chromium and 66 ms in Firefox** — two to four dropped frames. In a worker the longest gap is
one frame, on both engines. {doc}`workers` describes this trade for slow Python in general;
the channel does not change it. Heavy channel traffic is one more reason to use `--worker`.

## Main thread and worker

The channel behaves identically in both modes, and the test suite proves it:
`tests/test_bridge_browser.py` runs one harness against both builds and compares the two sets
of results. `--worker` is a performance flag. The moment it changes what an application can
say to its page, it becomes an API flag.

That is why the wire carries **text** and not arbitrary values. On the main thread Python
could be handed a live `JsProxy`; in a worker the identical call arrives as a structured
clone. The two differ in proxy lifetime, in whether a mutation is visible across the boundary,
and in whether a function survives the trip. A string crosses both as itself.

## Writing your own page

The contract is two members, and `boot.mjs` registers an object satisfying it in every
browser build. There is no flag to enable, because an application that never sends anything
pays nothing for the object existing.

```js
{ send(channel, text), subscribe(callback) }     // what Python is handed
```

A page using the shipped `main.mjs` gets the other side on
`globalThis.textualWasm.bridge`:

| Member | |
|---|---|
| `send(channel, value)` | Encode with the codec and send. Never drops. |
| `sendLatest(channel, value)` | At most one per channel per frame, keeping the newest. |
| `sendText(channel, text)` | Send as-is. |
| `on(channel, callback)` | Receive decoded. Returns an unsubscribe function. |
| `onText(channel, callback)` | Receive raw. Returns an unsubscribe function. |
| `codec` | `{ encode, decode }`, JSON by default. Replaceable. |

## The complete example

[`examples/page-bridge`](https://github.com/KaiErikNiermann/textual-wasm/tree/main/examples/page-bridge)
is a mixer. Three HTML sliders and three Textual meters share the same three values, a
clipping report travels one way from the application, and a text field uses the raw pipe. It
runs live in {doc}`examples`.
