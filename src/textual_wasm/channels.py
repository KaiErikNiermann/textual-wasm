"""Declaring what a channel carries, once, for both sides of the boundary.

`textual_wasm.bridge` is deliberately untyped below the codec: a pipe with an opinion about
its payload is a pipe that gets in the way of a protocol it has never heard of. That is the
right default and it leaves a real gap - `bridge.send("gain", value)` accepts any name and
any value, on both sides, and a typo is a message that silently goes nowhere.

A :class:`Channel` closes the gap without closing the pipe. It is a name plus a payload type,
and it is the *only* thing the TypeScript generator reads, so one declaration types the
application, types the page, and cannot describe two different things at once.

    class Levels(TypedDict):
        gain: int
        mode: Literal["flat", "loud"]

    LEVELS: Channel[Levels] = Channel("levels")

    bridge.send(LEVELS, {"gain": 40, "mode": "flat"})   # checked
    bridge.send(LEVELS, {"gain": 40, "mode": "nope"})   # a type error

The payload type comes from the **annotation**, not from an argument, and that is not a style
choice. A `payload: type[T]` field looks more explicit and quietly destroys inference:
`type[SomeTypedDict]` is not a valid type, so pyright stops solving `T` and every call above
passes. Measured, and the reason this class carries only a name.

TypedDict rather than a dataclass, because the value has to survive `json.dumps` and
`json.loads` unchanged. A TypedDict *is* the decoded object, so there is no structuring step
to get wrong, no serialiser to add, and no third dependency to choose between. Anything that
needs real validation swaps the bridge's codec for pydantic or cattrs, which the codec
protocol exists for, and this module stays out of it.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual_wasm.bridge import Bridge, BridgeMessage


@dataclasses.dataclass(frozen=True, slots=True)
class Channel[T]:
    """One named channel and, through its annotation, what it carries.

    Use it wherever the bridge takes a channel name; it is accepted anywhere a `str` is,
    because that is what it becomes on the wire.
    """

    name: str

    def __str__(self) -> str:
        """The wire name, so a channel can be formatted into a log line or a message."""
        return self.name

    def send(self, bridge: Bridge, value: T) -> None:
        """Put `value` on this channel, checked against the declared payload type.

        The argument order is `(bridge, value)` rather than `(value, bridge)` so that a
        reader sees where it is going before what is going there.
        """
        bridge.send(self.name, value)

    def matches(self, message: BridgeMessage) -> bool:
        """Whether `message` arrived on this channel."""
        return message.channel == self.name

    def decode(self, message: BridgeMessage) -> T:
        """Read `message` as this channel's payload type.

        A cast rather than a validation, and the docstring is the place to be honest about
        it: the guarantee is that both sides were generated from one declaration, not that
        the page kept its half of the bargain. A page that sends the wrong shape produces a
        `KeyError` at the point of use rather than an error here.

        Swap the bridge's codec for one that validates - `Levels.model_validate_json` and
        friends - when the payload comes from somewhere you do not control.
        """
        return typing.cast("T", message.data)


@dataclasses.dataclass(frozen=True, slots=True)
class Declaration:
    """One channel found in a module, and the type its annotation gave it."""

    name: str
    """The wire name, from the `Channel` instance rather than from the variable."""

    symbol: str
    """The module-level name it was bound to, for error messages that can be acted on."""

    payload: object
    """The declared payload type, as a typing object rather than a string."""


def collect(module: types.ModuleType) -> tuple[Declaration, ...]:
    """Every channel a module declares, in declaration order.

    Reads annotations rather than values, because the annotation is where the payload type
    is: `LEVELS: Channel[Levels] = Channel("levels")` puts `Levels` in the annotation and
    nothing but the name in the object.

    Args:
        module: An imported module of channel declarations.

    Returns:
        One entry per annotated `Channel`, ordered as written.

    Raises:
        TypeError: If a `Channel` is assigned without a parameterised annotation, which is
            the one mistake that would otherwise produce a generated file quietly missing a
            channel.
    """
    hints = typing.get_type_hints(module)
    declarations = [
        Declaration(name=value.name, symbol=symbol, payload=typing.get_args(hint)[0])
        for symbol, hint in hints.items()
        if typing.get_origin(hint) is Channel
        and isinstance(value := getattr(module, symbol, None), Channel)
    ]
    _reject_unannotated(module, {declaration.symbol for declaration in declarations})
    return tuple(declarations)


def _reject_unannotated(module: types.ModuleType, annotated: set[str]) -> None:
    """Fail on a `Channel` that was assigned without saying what it carries.

    Silence here is the worst outcome available: the channel works at runtime, the generated
    `.d.ts` simply does not mention it, and the page gets a type error on a name that is
    plainly correct.

    Raises:
        TypeError: Naming every symbol that needs an annotation.
    """
    missing = sorted(
        symbol
        for symbol, value in vars(module).items()
        if isinstance(value, Channel) and symbol not in annotated
    )
    if missing:
        listed = ", ".join(missing)
        raise TypeError(
            f"{module.__name__}: {listed} declared without a payload type. "
            f"Write `{missing[0]}: Channel[YourPayload] = Channel(...)`; the generator reads "
            "the annotation, because a type[] field would stop pyright checking your sends."
        )
