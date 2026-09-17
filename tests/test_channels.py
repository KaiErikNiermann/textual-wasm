"""Declaring a channel, and finding the declarations again.

Two things are worth asserting here and one of them is unusual. The ordinary one is that
`collect` finds what a module declared. The unusual one is that `Channel` carries *only* a
name - the payload type comes from the annotation - because the obvious alternative silently
turns off type checking at every call site, which no test of the happy path would notice.

The generated example declarations are checked against the committed file here as well, so a
change to the generator or to the example fails in the suite rather than only in the
`channels-check` gate. A gate that lives in one place is a gate somebody runs a different way.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Final

import pytest

from textual_wasm.channels import Channel, collect
from textual_wasm.typegen import build, render_typescript

EXAMPLE_ROOT: Final[Path] = Path(__file__).resolve().parent.parent / "examples" / "page-bridge"
EXAMPLE_MODULE: Final[str] = "mixer_app.channels"
EXAMPLE_OUTPUT: Final[Path] = EXAMPLE_ROOT / "page" / "channels.d.ts"


def _module(source: str) -> types.ModuleType:
    """Build a module from source, so a test can declare channels the way a user does.

    Executed rather than written to a file: what `collect` reads is the module object's
    annotations, and the import machinery is not part of what is being tested.
    """
    module = types.ModuleType("declared_channels")
    module.__dict__["__builtins__"] = __builtins__
    exec(compile(source, "<declared_channels>", "exec"), module.__dict__)  # noqa: S102
    return module


PREAMBLE: Final[str] = """\
from __future__ import annotations

from typing import Literal, TypedDict

from textual_wasm.channels import Channel


class Levels(TypedDict):
    gain: int
    mode: Literal["flat", "loud"]

"""
"""What every declaration module under test starts with. Declared here as source rather than
imported, because `collect` resolves annotations against the module it is given and a name
borrowed from this file would not be there."""


def test_a_channel_is_its_name_on_the_wire() -> None:
    """It goes where a `str` goes, because that is what the bridge sends."""
    gain: Channel[int] = Channel("gain")
    assert str(gain) == "gain"
    assert f"{gain}" == "gain"


def test_collect_finds_the_payload_type_from_the_annotation() -> None:
    declarations = collect(_module(f"{PREAMBLE}\nGAIN: Channel[int] = Channel('gain')\n"))
    assert [(d.name, d.symbol, d.payload) for d in declarations] == [("gain", "GAIN", int)]


def test_collect_keeps_declaration_order() -> None:
    """The generated file is committed and diffed, so an order that varies between runs is a
    diff nobody can read."""
    declarations = collect(
        _module(
            f"{PREAMBLE}\n"
            "A: Channel[int] = Channel('a')\n"
            "B: Channel[str] = Channel('b')\n"
            "C: Channel[Levels] = Channel('c')\n"
        )
    )
    assert [d.name for d in declarations] == ["a", "b", "c"]


def test_a_channel_without_a_payload_annotation_is_refused() -> None:
    """The one mistake that would otherwise produce a generated file quietly missing a
    channel: it works at runtime, the `.d.ts` does not mention it, and the page gets a type
    error on a name that is plainly correct."""
    with pytest.raises(TypeError, match="declared without a payload type"):
        collect(_module(f"{PREAMBLE}\nLOOSE = Channel('loose')\n"))


def test_the_refusal_names_the_symbol_and_the_fix() -> None:
    with pytest.raises(TypeError, match="LOOSE: Channel\\[YourPayload\\]"):
        collect(_module(f"{PREAMBLE}\nLOOSE = Channel('loose')\n"))


def test_a_module_with_no_channels_collects_nothing() -> None:
    assert collect(_module(f"{PREAMBLE}\nNOT_A_CHANNEL = 3\n")) == ()


def test_channel_helpers_read_a_message() -> None:
    """`matches` and `decode` are what an `on_bridge_message` is written against."""
    from textual_wasm.bridge import BridgeMessage, JsonCodec  # noqa: PLC0415 - local to one test

    gain: Channel[int] = Channel("gain")
    assert gain.matches(BridgeMessage("gain", "7", JsonCodec()))
    assert not gain.matches(BridgeMessage("bass", "7", JsonCodec()))
    assert gain.decode(BridgeMessage("gain", "7", JsonCodec())) == 7


# --- the committed example artifact ------------------------------------------


@pytest.fixture(scope="module")
def example_channels() -> types.ModuleType:
    """Import the example's declarations without installing the example.

    `--path` does the same thing for the CLI, and for the same reason: the declarations live
    in an application package that is read straight off disk, exactly as `build` reads it.
    """
    sys.path.insert(0, str(EXAMPLE_ROOT))
    try:
        return importlib.import_module(EXAMPLE_MODULE)
    finally:
        sys.path.remove(str(EXAMPLE_ROOT))


def test_the_committed_declarations_match_the_example(
    example_channels: types.ModuleType,
) -> None:
    """The same assertion `channels-check` makes, here so it also fails in the suite.

    The failure it prevents is a page type-checking green against channels the application
    stopped sending - which is worse than no generated file, because it reads as proof.
    """
    rendered = render_typescript(build(collect(example_channels)))
    assert EXAMPLE_OUTPUT.read_text(encoding="utf-8") == rendered, (
        "examples/page-bridge/page/channels.d.ts is out of date; run `just channels`"
    )


def test_the_example_declares_every_channel_its_app_binds(
    example_channels: types.ModuleType,
) -> None:
    """A channel the application uses but never declared is invisible to the page's type
    check, which is the quiet way a generated file stops covering everything."""
    declared = {declaration.name for declaration in collect(example_channels)}
    assert {"gain", "bass", "treble", "clipping", "note"} <= declared
