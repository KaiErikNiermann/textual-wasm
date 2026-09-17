"""A two-way data channel between a Textual app and the page hosting it.

The terminal stream is already a channel, and for *control* it is the right one: a page
button meaning "press 2" needs no protocol, because the application is already listening for
keystrokes. It is the wrong one for data. A slider emitting sixty values a second has no
keyboard spelling, and a page has no way at all to hear that the application changed
something.

So this module adds one thing and declines to add a second: a named channel carrying text,
in both directions, with no opinion about what the text means. Anything structured is built
on top by a codec, which defaults to JSON because both sides already have one and neither
needs a new serialisation format invented for them.

Three layers, each usable without the one above it:

* the pipe - :meth:`Bridge.send_text` and :attr:`BridgeMessage.text`, strings on named
  channels. Arbitrary by construction: a protocol this module has never heard of is a
  protocol it cannot get in the way of.
* the codec - :meth:`Bridge.send` and :attr:`BridgeMessage.data`, JSON by default and
  swappable for anything with ``encode``/``decode``.
* :meth:`Bridge.bind` - a Textual reactive and a channel kept in step, which is the slider
  case and the only protocol shipped here.

The wire carries text rather than arbitrary values, and that is a decision rather than
something the runtime forced. On the main thread Python could be handed a live ``JsProxy``;
in a worker the identical call arrives as a structured clone. Those two behave differently -
proxy lifetimes, whether a mutation is visible to the other side, whether a function survives
the trip - so a channel whose semantics depend on a build flag is exactly the failure
`TerminalHost` was shaped to avoid. A string crosses both transports as itself.

The page half is registered by `boot.mjs` and is present in every browser build; there is no
flag to enable, because an application that never sends anything pays nothing for it. On a
terminal there is no page at all, :attr:`Bridge.available` is False and sending is a no-op,
so an application written against the bridge still runs unchanged in a terminal.
"""

from __future__ import annotations

import importlib
import json
import logging
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

import rich.repr
from textual.message import Message

if TYPE_CHECKING:
    from collections.abc import Callable

    from pyodide.ffi import JsCallable
    from textual.app import App
    from textual.dom import DOMNode

_log: Final = logging.getLogger(__name__)

BRIDGE_MODULE: Final[str] = "textual_wasm_bridge"
"""Name the page registers its channel object under via `pyodide.registerJsModule`.

Duplicated in `boot.mjs` as `BRIDGE_MODULE`; a test asserts the two agree, because a silent
disagreement would present as an application whose messages vanish.
"""

type Validator = Callable[[Any], object]
"""Converts or rejects one inbound value, for :meth:`Bridge.bind`.

The parameter is `Any` rather than `object`, and that is the difference between the
documented one-liner working and not: `int` does not satisfy `Callable[[object], object]`,
because none of its overloads accepts a bare `object`. So `validate=int` - the fix this
argument exists for - would be a type error, which is the worst possible place to be strict.
"""

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
"""What :class:`JsonCodec` accepts and produces.

Exported because it is the type of everything crossing a default-codec channel, and an
application annotating its own payloads should not have to restate it.
"""


class BridgePayloadError(ValueError):
    """A value could not cross a channel, in either direction.

    One class for both because the question an operator asks is the same - *which channel,
    and what was wrong with it* - and because the original is kept as `__cause__` for
    anyone who needs to tell a `JSONDecodeError` from a `TypeError`.

    Naming the channel is the whole point. In a browser the only diagnostic is a console
    nobody has open, and `Expecting value: line 1 column 1 (char 0)` on its own does not say
    which of an application's channels produced it.
    """


class BridgeHost(Protocol):
    """The contract a page satisfies to give an application a data channel.

    Two members, matching the two directions. `send` is what Python calls to reach the page;
    `subscribe` is how the page learns where to deliver what it sends back. The shipped page
    provides both in either threading mode - directly on the main thread, over `postMessage`
    in a worker - and Python cannot tell which it has.
    """

    def send(self, channel: str, text: str) -> None:
        """Deliver `text` to whatever the page has listening on `channel`."""
        ...

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        """Register the callable the page invokes with `(channel, text)`."""
        ...


class Codec(Protocol):
    """How a value becomes the text the pipe carries, and back.

    Two methods so that swapping the default is a three-line class rather than a fork of
    this module. Pydantic's `model_dump_json`/`model_validate_json`, `cattrs`, or a msgpack
    payload wrapped in base64 all satisfy it, and none of them needs anything added here.
    """

    def encode(self, value: object) -> str:
        """Render `value` as the text to put on the wire."""
        ...

    def decode(self, text: str) -> object:
        """Recover a value from text that came off the wire."""
        ...


class JsonCodec:
    """The default codec: `json` on this side, `JSON` on the page's.

    Chosen because it is the one format both runtimes already have, which means a page
    author writes no encoder and an application adds no dependency. Non-serialisable values
    raise rather than being coerced - a payload the page cannot read should fail where it
    was written.

    `allow_nan=False`, which is not the `json` default and is the one place this codec is
    stricter than the standard library. `json.dumps(float("nan"))` produces the bare token
    `NaN`, which is not JSON: measured, `JSON.parse("NaN")` throws `SyntaxError: "NaN" is
    not valid JSON`. Left at the default, an application that divided by zero somewhere
    would send a payload that fails inside a page listener, in a console nobody is reading,
    with nothing pointing back at the sender. The page has the same gap in reverse -
    `JSON.stringify(NaN)` is `null` - but that direction at least arrives.
    """

    __slots__ = ()

    def encode(self, value: object) -> str:
        return json.dumps(value, allow_nan=False)

    def decode(self, text: str) -> object:
        return cast("object", json.loads(text))


class BridgeMessage(Message):
    """Text that arrived from the page, delivered through Textual's own message pump.

    A `Message` rather than a callback, so that receiving from a page works the way
    receiving from a widget already does: `on_bridge_message` on the app, `@on(BridgeMessage)`
    anywhere, `bubble`, `prevent`, and a test that posts one by hand without a browser in
    sight.

    Both layers are on the object. `text` is what crossed the wire and is always exactly
    what the page sent; `data` is that text through the bridge's codec, decoded once and
    kept, for the common case where nobody wants to see the JSON.
    """

    def __init__(self, channel: str, text: str, codec: Codec) -> None:
        super().__init__()
        self.channel = channel
        """The channel name the page sent on."""
        self.text = text
        """The raw payload, exactly as the page wrote it."""
        self._codec = codec
        self._decoded: object = _UNDECODED

    @property
    def data(self) -> object:
        """The payload through the codec, decoded on first access and then cached.

        Typed as `object` because a codec's output is only as specific as the codec, and a
        lie here would be a cast in every handler. Narrow it with `isinstance`, `match`, or
        by reaching past this to `text` and handing that to a codec that returns a model.

        Raises:
            BridgePayloadError: If the codec cannot read the text. The pipe does not pretend
                a malformed payload is an empty one; `text` survives for a handler that
                wants to recover, and the original error is the `__cause__`.
        """
        if self._decoded is _UNDECODED:
            try:
                self._decoded = self._codec.decode(self.text)
            except Exception as error:
                raise BridgePayloadError(
                    f"could not decode the payload on channel {self.channel!r}: {error}"
                ) from error
        return self._decoded

    def __rich_repr__(self) -> rich.repr.Result:
        yield "channel", self.channel
        yield "text", self.text


_UNDECODED: Final = object()
"""Distinguishes "not decoded yet" from a payload that decoded to `None`."""


class _Binding:
    """One reactive attribute kept in step with one channel.

    Holds the echo guard, which is the only non-obvious part of `bind`: applying an inbound
    value assigns the attribute, that assignment fires the watcher, and the watcher would
    send the value straight back to the page that just sent it. The loop terminates anyway -
    the page sets its control to a value it already has - but the traffic is real and a
    channel that echoes everything is hard to read in a console.

    Also holds the validator, for the reason below.
    """

    __slots__ = ("attribute", "channel", "node", "suppressed", "validate", "warned")

    def __init__(
        self,
        channel: str,
        node: DOMNode,
        attribute: str,
        validate: Validator | None,
    ) -> None:
        self.channel = channel
        self.node = node
        self.attribute = attribute
        self.validate = validate
        self.suppressed = False
        self.warned = False

    def apply(self, value: object) -> None:
        """Assign `value` to the bound attribute without sending it back.

        Raises:
            Whatever the validator raises. Caught by the caller, which logs it and leaves
            the attribute alone, because this runs inside a JavaScript callback.
        """
        current = getattr(self.node, self.attribute)
        if self.validate is None:
            self._warn_on_type_change(current, value)
        else:
            value = self.validate(value)
        if current == value:
            # Textual does not fire a watcher for an unchanged value, so this is not the
            # guard - it is the cheaper path that avoids arming one.
            return
        self.suppressed = True
        try:
            setattr(self.node, self.attribute, value)
        finally:
            self.suppressed = False

    def _warn_on_type_change(self, current: object, value: object) -> None:
        """Say so, once, when the page changes what *type* an attribute holds.

        Textual's reactives do not type-check at runtime, so a `reactive[int]` sent the
        string `"loud"` simply holds `"loud"` afterwards and the failure surfaces wherever
        the application next does arithmetic on it - a long way from the channel that caused
        it. Without a validator this is the only warning anyone gets, and silence here is
        how a page quietly redefines an application's state.

        Once per binding rather than per message: a slider dragged across a type boundary
        would otherwise fill the console with the same line sixty times a second.

        `None` is exempt in both directions because it is how an unset reactive starts and
        how an application spells "no value", not a type the page imposed.
        """
        if self.warned or current is None or value is None:
            return
        if type(current) is type(value):
            return
        self.warned = True
        _log.warning(
            "channel %r: the page changed %s.%s from %s to %s. Reactives are not checked at "
            "runtime, so this sticks. Pass validate= to bind() to convert or reject it.",
            self.channel,
            type(self.node).__name__,
            self.attribute,
            type(current).__name__,
            type(value).__name__,
        )


class Bridge:
    """An application's end of the channel.

    One per app. Constructed with :meth:`connect`, which finds the page's half if there is
    one; a terminal run gets a bridge whose `available` is False and whose sends go nowhere,
    so application code needs no branch.
    """

    __slots__ = ("_app", "_bindings", "_host", "_proxy", "codec")

    def __init__(
        self,
        app: App[Any],
        *,
        codec: Codec | None = None,
        host: BridgeHost | None = None,
    ) -> None:
        """Wire `app` to `host`, subscribing immediately if there is one.

        Args:
            app: The application that receives :class:`BridgeMessage`.
            codec: How values become text. `JsonCodec` when omitted.
            host: The page's half. Deliberately not discovered here - :meth:`connect` does
                that - so a test can pass its own without a runtime to fake.
        """
        self._app = app
        self.codec: Codec = codec if codec is not None else JsonCodec()
        self._host = host
        self._proxy: JsCallable[..., None] | None = None
        self._bindings: dict[str, _Binding] = {}
        if host is not None:
            host.subscribe(self._subscription())

    @classmethod
    def connect(cls, app: App[Any], *, codec: Codec | None = None) -> Bridge:
        """Attach `app` to the page's channel, or to nothing if this is a terminal.

        Args:
            app: The application that receives :class:`BridgeMessage`.
            codec: How values become text. `JsonCodec` when omitted.
        """
        return cls(app, codec=codec, host=_host())

    @property
    def available(self) -> bool:
        """Whether there is a page on the other end.

        True in every browser build. It does not claim that anything on the page is
        *listening* - that is the page's business, and an application that waits for a
        listener before drawing would never draw in a terminal.
        """
        return self._host is not None

    def send_text(self, channel: str, text: str) -> None:
        """Put `text` on `channel` as-is, with no codec in the way.

        The pipe. Anything with its own framing - a protocol buffer in base64, a line of
        CSV, another project's message envelope - travels this way and this module stays out
        of it.
        """
        if self._host is None:
            _log.debug("no page to receive %d characters on %r", len(text), channel)
            return
        self._host.send(channel, text)

    def send(self, channel: str, value: object) -> None:
        """Encode `value` with the codec and put it on `channel`.

        Encoding happens even when there is no page, which costs a `json.dumps` on a
        terminal and buys the thing worth having: a value the codec cannot render fails in
        every runtime rather than only in a browser.

        Raises:
            BridgePayloadError: If the codec cannot render `value`. Raised here rather than
                left to surface on the page, because the page cannot say what sent it.
        """
        try:
            text = self.codec.encode(value)
        except Exception as error:
            raise BridgePayloadError(
                f"could not encode a value for channel {channel!r}: {error}"
            ) from error
        self.send_text(channel, text)

    def bind(
        self,
        channel: str,
        node: DOMNode,
        attribute: str,
        *,
        initial: bool = True,
        validate: Validator | None = None,
    ) -> None:
        """Keep a reactive attribute and a channel in step, in both directions.

        The slider case in one line: the page's control and the application's state are two
        views of one value, and neither side has to know which of them moved it.

        Args:
            channel: The channel carrying the value.
            node: The app or widget owning the attribute. A `DOMNode`, so a widget can own
                its own channel without routing through the app.
            attribute: The name of a reactive attribute on `node`.
            initial: Whether to send the current value immediately, so a page that loads
                against a running app starts in step rather than in whatever state its
                markup happened to declare.
            validate: Called with each inbound value; its return is what gets assigned, and
                raising rejects the update. **Pass one for anything a page can reach**, and
                read the paragraph below before deciding not to.

        Binding a channel does not consume it: a :class:`BridgeMessage` is still posted, so
        an application can bind a value *and* react to its arrival - including one a
        validator rejected, since the raw text is still there.

        Without a validator the page decides the *type* of the attribute, not just its
        value. Textual's reactives do not type-check at runtime, so a `reactive[int]` sent
        the string `"loud"` holds `"loud"` afterwards, and the failure surfaces wherever the
        application next does arithmetic on it - measured, not theorised. `validate=int` is
        the whole fix for the common case:

            self.bridge.bind("gain", self, "gain", validate=int)

        Anything callable works, so `float`, a function that clamps to a range, or
        `TypeAdapter(Levels).validate_python` all fit without this module knowing about
        them. A rejected value is logged with the channel name and the attribute is left
        alone.
        """
        binding = _Binding(channel, node, attribute, validate)
        self._bindings[channel] = binding

        def on_change(value: object) -> None:
            if not binding.suppressed:
                self.send(channel, value)

        self._app.watch(node, attribute, on_change, init=initial)

    def close(self) -> None:
        """Release the callback proxy and forget the bindings.

        The proxy is not garbage collected on either side, so an application that outlives
        its bridge - a page that boots a second app into the same interpreter - has to say
        so. A page that closes with the app does not need this; the whole heap is going.
        """
        if self._proxy is not None:
            self._proxy.destroy()
            self._proxy = None
        self._bindings.clear()

    def _subscription(self) -> Callable[[str, str], None]:
        """The callable handed to the page, proxied when there is a JavaScript side.

        Every Python callable JavaScript stores and invokes later must own an explicitly
        created proxy: the automatic one is borrowed and destroyed when the call it was
        passed into returns, so a bare method appears to subscribe and then throws on the
        first message, into a console no Textual user is reading.

        Outside Pyodide there is no proxy to make and nothing to manage, which is the case a
        test with a fake host is in.
        """
        try:
            from pyodide.ffi import create_proxy  # noqa: PLC0415 - runtime-only import
        except ImportError:
            return self._deliver
        self._proxy = create_proxy(self._deliver)
        return self._proxy

    def _deliver(self, channel: str, text: object) -> None:
        """Hand one inbound message to the application.

        `text` is typed `object` rather than `str` because JavaScript is what calls this,
        and JavaScript will call it with whatever it has. Narrowing here is the boundary
        check; a `str` annotation would be a claim about a caller that cannot be held to it.

        Called by JavaScript, which means an exception raised here lands in the browser
        console rather than anywhere the application can see - so a decode failure in a
        binding is logged and the binding is skipped, while the message itself is posted
        regardless. The raw text survives either way, and an application that wants to know
        can read `text` and decode it itself.
        """
        if not isinstance(text, str):
            # Reachable from JavaScript, where `bridge.sendText("note")` with the argument
            # forgotten sends `undefined` and arrives here as None. Rejected rather than
            # coerced: `String(undefined)` is the string "undefined", which is data that
            # looks real. The page-side `sendText` refuses it too; this is for a host that
            # is not the shipped one.
            _log.error(
                "channel %r: expected text, got %s; the message was dropped",
                channel,
                type(text).__name__,
            )
            return

        binding = self._bindings.get(channel)
        if binding is not None:
            try:
                binding.apply(self.codec.decode(text))
            except Exception:
                _log.exception(
                    "channel %r: could not apply the payload to %s.%s; it was %.200r",
                    channel,
                    type(binding.node).__name__,
                    binding.attribute,
                    text,
                )
        self._app.post_message(BridgeMessage(channel, text, self.codec))


def _host() -> BridgeHost | None:
    """The page's channel object, or None on a runtime that has no page.

    An absent module is the ordinary case for every terminal run, so it is not logged as a
    problem. A module that is present but the wrong shape is: it means a custom page tried
    to provide a channel and got the contract wrong, and silence would present that as a
    terminal run.
    """
    try:
        module = importlib.import_module(BRIDGE_MODULE)
    except ImportError:
        return None

    # `hasattr` rather than `isinstance(module, BridgeHost)`: since CPython 3.12 a
    # runtime-checkable Protocol's instance check uses `inspect.getattr_static`, which does
    # not invoke `__getattr__` - and a `JsProxy` exposes every JavaScript member through
    # exactly that. The isinstance form therefore returns False for an object whose members
    # are all present and callable. `textual_wasm.storage` carries the same comment for the
    # same reason; it cost an afternoon once.
    if not all(hasattr(module, member) for member in ("send", "subscribe")):
        _log.warning("%s is registered but does not satisfy BridgeHost", BRIDGE_MODULE)
        return None
    return cast("BridgeHost", module)
