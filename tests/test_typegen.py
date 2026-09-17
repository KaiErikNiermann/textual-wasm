"""What a Python type becomes on the other side of the boundary.

The generator's whole value is that the declaration and the page cannot disagree, which is
only true if the translation is right - so these are mostly one type in, one line out. The
cases worth reading are the ones that were wrong first: `NotRequired` under postponed
annotations, a union inside an array, and a channel name that is not a TypeScript identifier.

The TypeScript is asserted as text because text is what ships. A structural assertion over
the intermediate form would pass while emitting something `tsc` rejects, which is the one
failure that matters and the one it could not see.
"""

from __future__ import annotations

import enum
import json
from typing import Literal, NotRequired, Required, TypedDict, cast

import pytest

from textual_wasm.channels import Declaration
from textual_wasm.typegen import UnsupportedTypeError, build, render_schema, render_typescript


def _ts(payload: object, *, channel: str = "c") -> str:
    """Render one channel and return only the declarations, without the fixed surface."""
    rendered = render_typescript(build([Declaration(name=channel, symbol="C", payload=payload)]))
    return rendered[: rendered.index("export type ChannelName")]


def _schema_for(payload: object) -> dict[str, object]:
    """Round-tripped through `json` so a test sees exactly what a file would hold."""
    model = build([Declaration(name="c", symbol="C", payload=payload)])
    return cast("dict[str, object]", json.loads(json.dumps(render_schema(model))))


def _definition(schema: dict[str, object], name: str) -> dict[str, object]:
    """One entry from `$defs`, narrowed once here rather than at every assertion."""
    return cast("dict[str, dict[str, object]]", schema["$defs"])[name]


# --- scalars and containers --------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (str, "string"),
        (int, "number"),
        (float, "number"),
        (bool, "boolean"),
        (type(None), "null"),
        (list[int], "number[]"),
        (set[str], "string[]"),
        (dict[str, int], "Record<string, number>"),
        (tuple[int, str], "[number, string]"),
        (tuple[int, ...], "number[]"),
        (int | None, "number | null"),
        (Literal["a", "b"], '"a" | "b"'),
        (Literal[1, 2], "1 | 2"),
        (Literal[True], "true"),
    ],
)
def test_a_payload_renders_as_the_expected_typescript(payload: object, expected: str) -> None:
    assert f"  c: {expected};" in _ts(payload)


def test_a_union_inside_an_array_keeps_its_parentheses() -> None:
    """`string | null[]` is an array of something else entirely, and the difference is one
    pair of brackets that a reader will not notice in a generated file."""
    assert "  c: (string | null)[];" in _ts(list[str | None])


def test_a_channel_name_that_is_not_an_identifier_is_quoted() -> None:
    """Channel names are strings. `echo-back` is a good one and not a property name."""
    assert '  "echo-back": string;' in _ts(str, channel="echo-back")


def test_declaring_no_channels_still_produces_a_usable_interface() -> None:
    """An empty interface makes `keyof Channels` be `never`, which reads at every call site
    as a baffling error rather than as "you have not declared anything yet"."""
    rendered = render_typescript(build([]))
    assert "[channel: string]: unknown;" in rendered


# --- named types -------------------------------------------------------------


class Inner(TypedDict):
    value: int


class Outer(TypedDict):
    inner: Inner
    tags: list[str]


def test_a_typed_dict_becomes_an_interface_referenced_by_name() -> None:
    rendered = _ts(Outer)
    assert "export interface Inner {\n  value: number;\n}" in rendered
    assert "  inner: Inner;" in rendered


def test_a_type_used_twice_is_emitted_once() -> None:
    rendered = render_typescript(
        build(
            [
                Declaration(name="a", symbol="A", payload=Inner),
                Declaration(name="b", symbol="B", payload=list[Inner]),
            ]
        )
    )
    assert rendered.count("export interface Inner") == 1


class SelfReferential(TypedDict):
    child: NotRequired[SelfReferential]


def test_a_type_that_refers_to_itself_terminates() -> None:
    """Not a hypothetical shape: a tree is the obvious thing to put on a channel, and a
    walker without the in-progress set recurses until the stack ends."""
    assert "  child?: SelfReferential;" in _ts(SelfReferential)


class Quality(enum.StrEnum):
    LOW = "low"
    HIGH = "high"


def test_a_string_enum_becomes_a_union_of_its_values() -> None:
    assert 'export type Quality = "low" | "high";' in _ts(Quality)


type Level = Literal["gain", "bass"]


def test_a_pep_695_alias_keeps_its_name() -> None:
    """Inlining would be correct and worse: the author named the union because the name
    means something, and this project writes such aliases itself."""
    rendered = _ts(Level)
    assert 'export type Level = "gain" | "bass";' in rendered
    assert "  c: Level;" in rendered


# --- optionality, which was wrong first --------------------------------------


class WithOptional(TypedDict):
    always: int
    sometimes: NotRequired[str]


class TotalFalse(TypedDict, total=False):
    maybe: int
    always: Required[str]


def test_not_required_renders_as_optional_despite_postponed_annotations() -> None:
    """The bug this pins, measured on 3.14.7: with `from __future__ import annotations` - on
    in this file and in most modules anyone would write - a TypedDict computes
    `__required_keys__` from the *string* form and gets it wrong. `sometimes` lands in
    `__required_keys__` and `__optional_keys__` comes back empty, so a generator trusting
    them emits a page that requires a key the application treats as optional.
    """
    assert WithOptional.__optional_keys__ == frozenset(), (
        "the standard library stopped getting this wrong; the workaround can be reconsidered"
    )
    rendered = _ts(WithOptional)
    assert "  always: number;" in rendered
    assert "  sometimes?: string;" in rendered


def test_total_false_makes_keys_optional_unless_marked_required() -> None:
    rendered = _ts(TotalFalse)
    assert "  maybe?: number;" in rendered
    assert "  always: string;" in rendered


# --- refusals ----------------------------------------------------------------


class NotJson:
    pass


@pytest.mark.parametrize("payload", [NotJson, bytes, complex, dict[int, str]])
def test_a_type_json_cannot_carry_is_refused_by_name(payload: object) -> None:
    """Named, because the whole class of failure here is someone writing a reasonable Python
    type and being told no - and "no" without "instead, do this" gets a generator worked
    around rather than used."""
    with pytest.raises(UnsupportedTypeError) as caught:
        _ts(payload)
    assert str(caught.value)


def test_bytes_is_refused_with_advice() -> None:
    with pytest.raises(UnsupportedTypeError, match="base64"):
        _ts(bytes)


def test_two_channels_with_one_name_is_refused() -> None:
    with pytest.raises(UnsupportedTypeError, match="declared twice"):
        build(
            [
                Declaration(name="same", symbol="A", payload=int),
                Declaration(name="same", symbol="B", payload=str),
            ]
        )


def test_two_different_types_sharing_a_name_is_refused() -> None:
    """The generated file would otherwise contain one declaration silently standing in for
    two shapes, and the page would type-check against whichever was reached first."""

    class ClashA(TypedDict):
        a: int

    class ClashB(TypedDict):
        b: str

    # The collision is in `__name__`, which is what the generator emits, so that is what has
    # to collide - two classes with different identities and one generated name.
    ClashA.__name__ = "Clash"
    ClashB.__name__ = "Clash"

    with pytest.raises(UnsupportedTypeError, match="both called Clash"):
        build(
            [
                Declaration(name="x", symbol="X", payload=ClashA),
                Declaration(name="y", symbol="Y", payload=ClashB),
            ]
        )


# --- the JSON Schema, off the same walk --------------------------------------


def test_the_schema_describes_the_same_channels() -> None:
    schema = _schema_for(Outer)
    assert schema["properties"] == {"c": {"$ref": "#/$defs/Outer"}}
    assert _definition(schema, "Inner") == {
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
        "additionalProperties": False,
    }


def test_the_schema_calls_an_integer_a_number() -> None:
    """A schema saying `integer` would be a claim this cannot make good on: TypeScript has
    no integer type, so the page is free to send 1.5 and nothing would have caught it."""
    assert _schema_for(int)["properties"] == {"c": {"type": "number"}}


def test_the_two_outputs_agree_on_optionality() -> None:
    """One walk, two printers, and this is the assertion that keeps them one walk."""
    assert _definition(_schema_for(WithOptional), "WithOptional")["required"] == ["always"]
    assert "  sometimes?: string;" in _ts(WithOptional)


# --- the fixed surface -------------------------------------------------------


def test_the_generated_file_types_the_bridge_against_the_channels() -> None:
    """The part JSON Schema cannot express, and the reason this emits TypeScript directly:
    a mapped type tying a channel *name* to its payload, so a typo is a type error."""
    rendered = render_typescript(build([Declaration(name="gain", symbol="G", payload=int)]))
    assert "send<K extends ChannelName>(channel: K, value: Channels[K]): void;" in rendered
    assert "on<K extends ChannelName>(channel: K, callback: (value: Channels[K]) => void)" in (
        rendered
    )


def test_the_raw_pipe_is_not_restricted_to_declared_channels() -> None:
    """`sendText` is the layer with no schema, and a generator that narrowed it would be
    imposing one exactly where the design says there is none."""
    rendered = render_typescript(build([Declaration(name="gain", symbol="G", payload=int)]))
    assert "sendText(channel: string, text: string): void;" in rendered
