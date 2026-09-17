"""Turn channel declarations into type declarations the page can be checked against.

The bridge carries JSON text, which is why this is possible at all: there is no FFI object
graph to describe, only a value that both runtimes already agree how to write down. Had the
wire carried live `JsProxy` objects, "what does the page see" would have depended on the
threading mode and no generator could have answered it.

**Why a printer here rather than `json-schema-to-typescript`.** The obvious pipeline is
Python type to JSON Schema to a Node tool, and it works - measured, off the shelf. Two things
rule it out as *the* path. It puts Node on the critical path of a generated artifact, which
makes the drift gate unrunnable wherever Node is not installed, and the project's other
generated documents (`matrix --check`, `libraries --check`) are gated in exactly that way. And
JSON Schema cannot express the part that is actually worth generating: a mapped type tying a
channel *name* to its payload, so `bridge.send("gian", …)` is a type error rather than a
message into the void.

So the schema is emitted too, as a first-class output, for runtime validation and for anyone
who wants a different generator - and both come off the same walk, so they cannot describe
two different things.

**The type algebra is closed**, and deliberately small: what survives `json.dumps` and
`json.loads` unchanged. Scalars, `Literal`, `list`, `tuple`, `dict[str, …]`, unions with
`None`, `TypedDict`, and `Enum` whose members are strings or numbers. Anything else raises
with the offending type named, because a generator that silently emits `unknown` for a type
it did not understand produces a page that type-checks and is wrong.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import types
import typing
from typing import TYPE_CHECKING, Final, Literal

from typing_extensions import TypeIs

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from textual_wasm.channels import Declaration

PrimitiveKind = Literal["string", "number", "boolean", "null"]

_PRIMITIVES: Final[dict[object, PrimitiveKind]] = {
    str: "string",
    int: "number",
    float: "number",
    # Ahead of `int` in intent though not in lookup: `bool` is a subclass of `int`, so any
    # check that used `issubclass` would report every boolean as a number.
    bool: "boolean",
    types.NoneType: "null",
    type(None): "null",
}

_JSON_SCHEMA_TYPES: Final[dict[PrimitiveKind, str]] = {
    "string": "string",
    # `number` for both, because the wire is JSON and JSON has one numeric type. A schema
    # saying `integer` would be a claim this generator cannot make good on: TypeScript has
    # no integer type, so the page is free to send 1.5 and nothing would have caught it.
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}


_UNION_ORIGINS: Final[frozenset[object]] = frozenset({types.UnionType, typing.Union})
"""Both spellings of a union. `int | None` has `types.UnionType`; `Optional[int]` written
before PEP 604 still resolves to `typing.Union`, and a generator that handled one and not the
other would fail on somebody's older module for no reason they could see."""

_ARRAY_ORIGINS: Final[frozenset[object]] = frozenset({list, set, frozenset})
"""All of these are a JSON array. A set loses its order on the way out, which is a fact about
JSON rather than about this generator."""

_VARIADIC_TUPLE_LENGTH: Final[int] = 2
"""`tuple[T, ...]` - one argument and an ellipsis - as opposed to a fixed-length tuple."""


class UnsupportedTypeError(TypeError):
    """A payload contains something that cannot cross a JSON channel.

    Its own class so a caller can tell "you wrote a type I do not handle" from any other
    `TypeError` raised while importing a module of declarations.
    """


# --- the intermediate form ---------------------------------------------------
#
# One walk of the Python types produces this; each printer reads it. The alternative - a
# printer that walks the types itself - is two walks that agree until one of them is edited.


@dataclasses.dataclass(frozen=True, slots=True)
class Primitive:
    kind: PrimitiveKind


@dataclasses.dataclass(frozen=True, slots=True)
class LiteralUnion:
    """`Literal["flat", "loud"]`, which is the reason to bother with any of this: it is the
    constraint most often written in Python and most often lost on the way out."""

    values: tuple[str | int | bool, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ArrayOf:
    item: TypeNode


@dataclasses.dataclass(frozen=True, slots=True)
class TupleOf:
    """A fixed-length tuple. `tuple[T, ...]` is an `ArrayOf`; this is `tuple[int, str]`."""

    items: tuple[TypeNode, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class RecordOf:
    """`dict[str, T]`. Only string keys, because a JSON object has no others."""

    value: TypeNode


@dataclasses.dataclass(frozen=True, slots=True)
class UnionOf:
    members: tuple[TypeNode, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class Ref:
    """A reference to a named type, emitted once and pointed at from everywhere else."""

    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class Field:
    name: str
    type: TypeNode
    required: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Struct:
    """A `TypedDict`, as an interface."""

    name: str
    fields: tuple[Field, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class Alias:
    """A PEP 695 `type X = ...`, kept as a name rather than inlined.

    Inlining would be correct and worse: the author gave the union a name because the name
    means something, and a generated file that spells it out five times loses that.
    """

    name: str
    target: TypeNode


@dataclasses.dataclass(frozen=True, slots=True)
class EnumOf:
    """An `Enum` whose members are strings or numbers, as a union of its values."""

    name: str
    values: tuple[str | int | float, ...]


type TypeNode = Primitive | LiteralUnion | ArrayOf | TupleOf | RecordOf | UnionOf | Ref

type Named = Struct | EnumOf | Alias


@dataclasses.dataclass(frozen=True, slots=True)
class ChannelType:
    """One channel, resolved."""

    name: str
    type: TypeNode


@dataclasses.dataclass(frozen=True, slots=True)
class Model:
    """Everything a printer needs: the channels, and the named types they reach."""

    channels: tuple[ChannelType, ...]
    named: tuple[Named, ...]


# --- the walk ----------------------------------------------------------------


class _Walker:
    """Resolves Python types to :data:`TypeNode`, collecting named types on the way.

    A class rather than functions with an accumulator argument, because the accumulator is
    shared across a recursion whose shape is the type's, and threading it by hand is how a
    self-referential `TypedDict` turns into a stack overflow.
    """

    def __init__(self) -> None:
        self._named: dict[str, Named] = {}
        self._in_progress: set[str] = set()
        self._origins: dict[str, object] = {}

    @property
    def named(self) -> tuple[Named, ...]:
        """Named types in the order they were first reached, which keeps the output stable
        across runs - a generated file that reorders itself is a diff nobody can read."""
        return tuple(self._named.values())

    def resolve(self, annotation: object) -> TypeNode:
        """One Python type to one node.

        Raises:
            UnsupportedTypeError: If the type cannot cross a JSON channel.
        """
        if isinstance(annotation, typing.TypeAliasType):
            return self._alias(annotation)
        if (kind := _PRIMITIVES.get(annotation)) is not None:
            return Primitive(kind)
        if _is_typed_dict(annotation):
            return self._struct(annotation)
        if _is_enum(annotation):
            return self._enum(annotation)
        if (origin := typing.get_origin(annotation)) is not None:
            return self._parameterised(annotation, origin)
        raise UnsupportedTypeError(_unsupported(annotation))

    def _parameterised(self, annotation: object, origin: object) -> TypeNode:
        """`list[int]`, `dict[str, X]`, `Literal[...]`, `A | B`, and the rest."""
        arguments = typing.get_args(annotation)
        if origin is Literal:
            return LiteralUnion(tuple(typing.cast("tuple[str | int | bool, ...]", arguments)))
        if origin in _UNION_ORIGINS:
            return UnionOf(tuple(self.resolve(argument) for argument in arguments))
        if origin in _ARRAY_ORIGINS:
            return ArrayOf(self.resolve(arguments[0]))
        if origin is tuple:
            return self._tuple(arguments)
        if origin is dict:
            return self._record(annotation, arguments)
        raise UnsupportedTypeError(_unsupported(annotation))

    def _tuple(self, arguments: Sequence[object]) -> TypeNode:
        if len(arguments) == _VARIADIC_TUPLE_LENGTH and arguments[1] is Ellipsis:
            return ArrayOf(self.resolve(arguments[0]))
        return TupleOf(tuple(self.resolve(argument) for argument in arguments))

    def _record(self, annotation: object, arguments: Sequence[object]) -> TypeNode:
        if arguments[0] is not str:
            raise UnsupportedTypeError(
                f"{_label(annotation)}: a JSON object has only string keys, so a mapping "
                f"keyed by {_label(arguments[0])} cannot cross a channel"
            )
        return RecordOf(self.resolve(arguments[1]))

    def _struct(self, annotation: object) -> Ref:
        """A `TypedDict`, registered once and referenced thereafter."""
        name = _named_as(annotation)
        if name in self._named or name in self._in_progress:
            # Already emitted, or currently being emitted - the second case is a type that
            # refers to itself, where returning the reference is both correct and the only
            # thing that terminates.
            self._check_collision(name, annotation)
            return Ref(name)
        self._origins[name] = annotation
        self._in_progress.add(name)
        total = bool(getattr(annotation, "__total__", True))
        fields = tuple(
            self._field(key, hint, total=total)
            for key, hint in typing.get_type_hints(annotation, include_extras=True).items()
        )
        self._in_progress.discard(name)
        self._named[name] = Struct(name=name, fields=fields)
        return Ref(name)

    def _field(self, key: str, hint: object, *, total: bool) -> Field:
        """One `TypedDict` key, with optionality read from the annotation.

        Not from `__required_keys__`, and that is a measured bug rather than a preference.
        Under `from __future__ import annotations` - which this project and most others turn
        on everywhere - a `TypedDict` sees its annotations as strings and computes
        `__required_keys__` from them, and gets it wrong: `label: NotRequired[str]` lands in
        `__required_keys__` and `__optional_keys__` comes back empty. Measured on 3.14.7.
        The generated page would then require a key the application treats as optional, which
        is a type error on correct code.

        `get_type_hints(..., include_extras=True)` keeps `Required`/`NotRequired` as the
        wrapper it is, which survives postponed annotations because it is resolved rather
        than parsed.
        """
        origin = typing.get_origin(hint)
        if origin is typing.NotRequired:
            return Field(name=key, type=self.resolve(typing.get_args(hint)[0]), required=False)
        if origin is typing.Required:
            return Field(name=key, type=self.resolve(typing.get_args(hint)[0]), required=True)
        return Field(name=key, type=self.resolve(hint), required=total)

    def _alias(self, annotation: typing.TypeAliasType) -> Ref:
        """A `type X = ...` alias, emitted under its own name.

        Worth handling rather than rejecting: PEP 695 aliases are how a `Literal` union gets
        a name, which is the single most useful thing to put on a channel, and this project
        writes them itself. A parameterised alias - `type Pair[T] = tuple[T, T]` used as
        `Pair[int]` - arrives as a generic alias instead and is refused by name, because
        substituting the parameters here would be reimplementing the type system.
        """
        name = annotation.__name__
        if name in self._named or name in self._in_progress:
            self._check_collision(name, annotation)
            return Ref(name)
        self._origins[name] = annotation
        self._in_progress.add(name)
        target = self.resolve(annotation.__value__)
        self._in_progress.discard(name)
        self._named[name] = Alias(name=name, target=target)
        return Ref(name)

    def _enum(self, annotation: type[enum.Enum]) -> Ref:
        name = _named_as(annotation)
        if name in self._named:
            self._check_collision(name, annotation)
            return Ref(name)
        values = tuple(member.value for member in annotation)
        if not all(isinstance(value, str | int | float) for value in values):
            raise UnsupportedTypeError(
                f"{name}: only an Enum whose members are strings or numbers can cross a "
                "channel; this one has values JSON cannot represent"
            )
        self._origins[name] = annotation
        self._named[name] = EnumOf(name=name, values=values)
        return Ref(name)

    def _check_collision(self, name: str, annotation: object) -> None:
        """Two different types cannot share one generated name.

        Raises:
            UnsupportedTypeError: Naming both, because the output would otherwise contain one
                declaration silently standing in for two shapes.
        """
        first = self._origins.get(name)
        if first is not None and first is not annotation:
            raise UnsupportedTypeError(
                f"two different types are both called {name} "
                f"({_module_of(first)} and {_module_of(annotation)}); rename one, because a "
                "generated declaration cannot mean both"
            )


def build(declarations: Iterable[Declaration]) -> Model:
    """Resolve every declared channel into the form the printers read.

    Raises:
        UnsupportedTypeError: If any payload contains something JSON cannot carry.
    """
    walker = _Walker()
    channels = tuple(
        ChannelType(name=declaration.name, type=walker.resolve(declaration.payload))
        for declaration in declarations
    )
    _reject_duplicate_names(channels)
    return Model(channels=channels, named=walker.named)


def _reject_duplicate_names(channels: Sequence[ChannelType]) -> None:
    """Two declarations naming one channel is a copy-paste, not a design.

    Raises:
        UnsupportedTypeError: Naming the channel, because the generated interface would keep
            whichever came last and the other application code would keep sending.
    """
    seen: set[str] = set()
    for channel in channels:
        if channel.name in seen:
            raise UnsupportedTypeError(
                f"{channel.name!r} is declared twice; one channel carries one payload type"
            )
        seen.add(channel.name)


# --- naming and errors -------------------------------------------------------


def _is_enum(annotation: object) -> TypeIs[type[enum.Enum]]:
    """Whether this is an `Enum` subclass.

    A `TypeIs` rather than the `isinstance`/`issubclass` pair written inline, because
    `issubclass` narrowing leaves `type[Unknown]` in the *negative* branch - so every
    subsequent call in `resolve` would take a partially unknown argument, and pyright is
    right to say so.
    """
    return isinstance(annotation, type) and issubclass(annotation, enum.Enum)


def _is_typed_dict(annotation: object) -> bool:
    """Whether this is a `TypedDict` class.

    By its marker attributes rather than `issubclass`, which is what the standard library
    itself does: a `TypedDict` is not a class you can subclass-test against.
    """
    return (
        isinstance(annotation, type)
        and hasattr(annotation, "__annotations__")
        and (hasattr(annotation, "__required_keys__") or hasattr(annotation, "__optional_keys__"))
    )


def _named_as(annotation: object) -> str:
    return getattr(annotation, "__name__", str(annotation))


def _module_of(annotation: object) -> str:
    return getattr(annotation, "__module__", "?")


def _label(annotation: object) -> str:
    """How a type is named in an error message, preferring what the author wrote."""
    return getattr(annotation, "__name__", None) or str(annotation)


_KNOWN_AWKWARD: Final[dict[object, str]] = {
    datetime.datetime: "send an ISO 8601 string and parse it on the page",
    datetime.date: "send an ISO 8601 string and parse it on the page",
    bytes: "base64 it into a str, or use the raw pipe and skip the codec",
    complex: "send it as a pair of numbers",
}


def _unsupported(annotation: object) -> str:
    """The message for a type this generator will not guess at.

    Worth the extra sentence: the whole class of failure here is someone writing a perfectly
    reasonable Python type and being told no, and "no" without "instead, do this" is how a
    generator gets worked around rather than used.
    """
    hint = _KNOWN_AWKWARD.get(annotation)
    advice = (
        f"; {hint}"
        if hint is not None
        else ". A channel carries what JSON carries: str, int, float, bool, None, Literal, "
        "list, tuple, dict[str, ...], unions, TypedDict and string or numeric Enum"
    )
    return f"{_label(annotation)} cannot cross a JSON channel{advice}"


# --- the TypeScript printer --------------------------------------------------

GENERATED_NOTICE: Final[str] = """\
/* Generated by `textual-wasm channels`. Do not edit.
 *
 * The channel names and payloads below come from one declaration in Python, so this file and
 * the application cannot disagree about what a channel carries. Regenerate after changing
 * that declaration; `--check` fails a build when this file is stale.
 */
"""


def render_typescript(model: Model) -> str:
    """The `.d.ts` a page is checked against.

    Includes the fixed `globalThis.textualWasm` surface as well as the channels, because
    splitting them would mean a page importing two files to type one object - and the
    interesting part is precisely where they meet, in a `send` whose payload type follows
    from its channel name.
    """
    blocks = [GENERATED_NOTICE, *(_ts_named(named) for named in model.named)]
    blocks.append(_ts_channels(model.channels))
    blocks.append(_TS_SURFACE)
    return "\n".join(blocks)


def _ts_named(named: Named) -> str:
    if isinstance(named, Alias):
        return f"export type {named.name} = {_ts(named.target)};\n"
    if isinstance(named, EnumOf):
        members = " | ".join(_ts_literal(value) for value in named.values)
        return f"export type {named.name} = {members};\n"
    fields = "\n".join(
        f"  {field.name}{'' if field.required else '?'}: {_ts(field.type)};"
        for field in named.fields
    )
    return f"export interface {named.name} {{\n{fields}\n}}\n"


def _ts_channels(channels: Sequence[ChannelType]) -> str:
    if not channels:
        # An empty interface would make `keyof Channels` be `never`, which reads as a
        # baffling error at every call site rather than as "you declared no channels".
        return (
            "/** No channels are declared. */\n"
            "export interface Channels {\n  [channel: string]: unknown;\n}\n"
        )
    entries = "\n".join(f"  {_ts_key(channel.name)}: {_ts(channel.type)};" for channel in channels)
    return (
        "/** Every channel this application declares, and what it carries. */\n"
        f"export interface Channels {{\n{entries}\n}}\n"
    )


def _ts_key(name: str) -> str:
    """Quote a channel name unless it is a plain identifier.

    Channel names are strings, and `echo-back` is a perfectly good one that is not a valid
    TypeScript property name.
    """
    return name if name.isidentifier() else f'"{name}"'


def _ts(node: TypeNode) -> str:  # noqa: PLR0911 - one return per variant, exhaustively
    match node:
        case Primitive(kind):
            return kind
        case LiteralUnion(values):
            return _ts_union(_ts_literal(value) for value in values)
        case ArrayOf(item):
            return _ts_array(item)
        case TupleOf(items):
            return _ts_tuple(items)
        case RecordOf(value):
            return f"Record<string, {_ts(value)}>"
        case UnionOf(members):
            return _ts_union(_ts(member) for member in members)
        case Ref(name):
            return name


def _ts_union(parts: Iterable[str]) -> str:
    """A union. Its own function so the printer above is one line per variant, which is what
    keeps an exhaustive dispatcher readable as a table rather than as a program."""
    return " | ".join(parts)


def _ts_tuple(items: Iterable[TypeNode]) -> str:
    return f"[{', '.join(_ts(item) for item in items)}]"


def _ts_array(item: TypeNode) -> str:
    """An array, parenthesised when its element is a union.

    `string | null[]` is an array of something else entirely, and the difference is one pair
    of brackets nobody will notice in a generated file.
    """
    rendered = _ts(item)
    return f"({rendered})[]" if " | " in rendered else f"{rendered}[]"


def _ts_literal(value: str | int | float | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return f'"{value}"' if isinstance(value, str) else str(value)


_TS_SURFACE: Final[str] = """\
export type ChannelName = keyof Channels;

/** What `textual_wasm.bridge.Codec` is on this side. */
export interface Codec {
  encode(value: unknown): string;
  decode(text: string): unknown;
}

export interface Bridge {
  /** Encode with the codec and send. The payload type follows from the channel name. */
  send<K extends ChannelName>(channel: K, value: Channels[K]): void;
  /** Send as-is, with no codec in the way. Any name: the pipe has no schema. */
  sendText(channel: string, text: string): void;
  /** Receive decoded. Returns an unsubscribe function. */
  on<K extends ChannelName>(channel: K, callback: (value: Channels[K]) => void): () => void;
  /** Receive raw. Returns an unsubscribe function. */
  onText(channel: string, callback: (text: string) => void): () => void;
  codec: Codec;
}

export interface Screen {
  columns: number;
  rows: number;
  lines: string[];
}

/** Published on `globalThis` once the application is driving the terminal, not before. */
export interface TextualWasm {
  columns: number;
  rows: number;
  worker: boolean;
  finished: Promise<unknown>;
  /** Keystrokes, as if typed. For control; use `bridge` for values. */
  input(data: string): void;
  screen(): Screen;
  bridge: Bridge;
}

declare global {
  // Optional, and that is the contract rather than caution: it appears seconds after the
  // page does, so a page must wait for it.
  // eslint-disable-next-line no-var
  var textualWasm: TextualWasm | undefined;
}
"""


# --- the JSON Schema printer -------------------------------------------------

type JsonSchema = dict[str, object]


def render_schema(model: Model) -> JsonSchema:
    """The same model as JSON Schema, for validation and other generators.

    Draft 2020-12, with every named type in `$defs` so the document mirrors the TypeScript
    one entry for entry rather than inlining what the other file references.
    """
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Channels",
        "description": "Generated by `textual-wasm channels`. One entry per declared channel.",
        "type": "object",
        "properties": {channel.name: _schema(channel.type) for channel in model.channels},
        "additionalProperties": False,
        "$defs": {named.name: _schema_named(named) for named in model.named},
    }


def _schema_named(named: Named) -> JsonSchema:
    if isinstance(named, Alias):
        return _schema(named.target)
    if isinstance(named, EnumOf):
        return {"enum": list(named.values)}
    return {
        "type": "object",
        "properties": {field.name: _schema(field.type) for field in named.fields},
        "required": [field.name for field in named.fields if field.required],
        "additionalProperties": False,
    }


def _schema(node: TypeNode) -> JsonSchema:  # noqa: PLR0911 - one return per variant
    match node:
        case Primitive(kind):
            return {"type": _JSON_SCHEMA_TYPES[kind]}
        case LiteralUnion(values):
            return {"enum": list(values)}
        case ArrayOf(item):
            return {"type": "array", "items": _schema(item)}
        case TupleOf(items):
            return {
                "type": "array",
                "prefixItems": [_schema(item) for item in items],
                "items": False,
            }
        case RecordOf(value):
            return {"type": "object", "additionalProperties": _schema(value)}
        case UnionOf(members):
            return {"anyOf": [_schema(member) for member in members]}
        case Ref(name):
            return {"$ref": f"#/$defs/{name}"}


def walk_nodes(node: TypeNode) -> Iterator[TypeNode]:
    """Yield `node` and everything nested in it, for callers inspecting a model."""
    yield node
    match node:
        case ArrayOf(item):
            yield from walk_nodes(item)
        case RecordOf(value):
            yield from walk_nodes(value)
        case TupleOf(items) | UnionOf(items):
            for item in items:
                yield from walk_nodes(item)
        case _:
            return
