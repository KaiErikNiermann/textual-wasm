"""What the channel does with what a page should not send, in real browsers.

`test_bridge.py` covers this against a fake page and proves the Python logic. It cannot
prove the part that matters most here, which is that the *whole system* survives: a bad
payload crosses two runtimes, a structured clone, a JSON decoder, Textual's message pump and
a reactive setter before anything notices, and an exception at any of those points lands in
a browser console rather than anywhere an application can see.

So one run per engine, asserting that the application is still drawing at the end and that
every failure said something an operator could act on. Chromium and Firefox both, because a
case that behaves differently between engines is exactly what a single-engine suite cannot
see - and this channel is the one place the two runtimes' type systems meet.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Final, cast

import pytest

from textual_wasm import node
from textual_wasm.bundler import BuildSpec, background_server, build

pytestmark = [pytest.mark.slow, pytest.mark.browser]

HARNESS: Final[str] = "bridge-errors.mjs"
HARNESS_DIR: Final[Path] = Path(__file__).parent / "harness"
ERRORS_APP: Final[str] = "tests.bridge_errors_app:ErrorApp"
PACKAGE: Final[Path] = Path(__file__).parent

ENGINES: Final[tuple[str, ...]] = ("chromium", "firefox")
"""Both engines this suite can drive headlessly. WebKit is covered by `safari.yml`, which
runs weekly against a real Safari rather than Playwright's port."""

HOSTILE_TEXT: Final[str] = "\x1b[31m \x00 \u202e \U0001f600 done"
"""What the harness puts on the raw pipe. Chosen so that anything which decodes, re-encodes
or normalises on the way through would mangle it: a terminal escape the driver's own parser
would act on, a null JSON refuses, a right-to-left override, and an astral-plane character
that is two UTF-16 units and one Python character."""


def _run(engine: str) -> dict[str, object]:
    """Build the fixture in worker mode and drive it through `engine`.

    Worker mode because it is the harder transport - every payload crosses a structured
    clone - and because the error handling itself is identical in both, which
    `test_bridge_browser.py` already establishes.
    """
    available = node.availability([node.PLAYWRIGHT_PACKAGE])
    if not available.available or available.node is None or available.resolve_from is None:
        raise RuntimeError(f"{available.reason} {node.BROWSER_HINT}")

    with tempfile.TemporaryDirectory(prefix="textual-wasm-errors-") as directory:
        build(
            BuildSpec(
                entry=ERRORS_APP,
                package=PACKAGE,
                output=Path(directory),
                worker=True,
                verify_entry=False,
            )
        )
        with background_server(Path(directory)) as url:
            result = node.run_harness(
                HARNESS,
                {
                    "resolveFrom": str(available.resolve_from),
                    "url": url,
                    "worker": True,
                    "browser": engine,
                },
                node=available.node,
                directory=HARNESS_DIR,
            )
    if not result.ok:
        raise RuntimeError(f"the error harness failed on {engine}:\n{result.stderr}")
    return result.payload


@pytest.fixture(scope="module")
def browser_available() -> None:
    available = node.availability([node.PLAYWRIGHT_PACKAGE])
    if not available.available:
        pytest.skip(f"{available.reason} {node.BROWSER_HINT}")


@pytest.fixture(params=ENGINES, scope="module")
def observed(request: pytest.FixtureRequest, browser_available: None) -> dict[str, object]:
    """One full hostile-input run, per engine."""
    return _run(str(request.param))


def _field(observed: dict[str, object], name: str) -> dict[str, object]:
    """One nested object from the harness, narrowed once here rather than at every use."""
    value = observed[name]
    assert isinstance(value, dict), f"{name} came back as {type(value).__name__}"
    return cast("dict[str, object]", value)


# --- the application survives ------------------------------------------------


def test_the_app_is_still_drawing_after_every_hostile_input(
    observed: dict[str, object],
) -> None:
    """The claim that matters most, and the one no message can make on its own: a channel
    that survives bad input by killing the application has not survived it."""
    assert observed["aliveAfterMalformed"] is True
    assert observed["aliveAtEnd"] is True


def test_nothing_reached_the_page_as_an_uncaught_error(observed: dict[str, object]) -> None:
    """An uncaught error on the page is the failure mode this whole design is arranged
    against: it lands in a console nobody has open and the application never hears of it."""
    assert observed["pageErrors"] == []


# --- refused where it was written --------------------------------------------


def test_a_non_string_payload_is_refused_at_the_call_site(
    observed: dict[str, object],
) -> None:
    """`JSON.stringify(undefined)` is `undefined`, not a string, so a forgotten argument
    would otherwise put a non-string on the wire and arrive as None several runtimes later.
    Throwing keeps the stack pointing at the caller.

    Coercing would be worse than throwing: `String(undefined)` is the string "undefined",
    which is data that looks real all the way into the application.
    """
    refused = _field(observed, "refusedAtCallSite")
    for attempt in ("sendUndefined", "sendTextUndefined", "sendTextNumber", "sendTextMissing"):
        raised = refused[attempt]
        assert isinstance(raised, str), f"{attempt} was accepted"
        assert "TypeError" in raised
        assert "textual-wasm" in raised, "the message must say what refused it"


# --- malformed and mistyped payloads -----------------------------------------


def test_malformed_json_on_a_bound_channel_leaves_the_value_alone(
    observed: dict[str, object],
) -> None:
    """Dropped rather than applied, and the application keeps running - the alternative is
    an exception inside a JavaScript callback, which is unreachable from Python."""
    state = _field(observed, "afterMalformed")
    assert state["loose"] == "0"
    assert state["looseType"] == "int"


def test_an_unvalidated_binding_lets_the_page_change_the_type(
    observed: dict[str, object],
) -> None:
    """Asserted rather than prevented, because it is the documented behaviour and the reason
    `validate=` exists: Textual's reactives are not checked at runtime, so a `reactive[int]`
    sent a string holds a string afterwards.

    If this ever starts failing, the bridge grew validation nobody asked for - or Textual
    started type-checking, in which case the warning `bind` emits can go.
    """
    state = _field(observed, "afterWrongType")
    assert state["looseType"] == "str"
    assert state["loose"] == "'not a number'"


def test_a_validated_binding_rejects_what_it_cannot_convert(
    observed: dict[str, object],
) -> None:
    """The same payload, one argument different. The attribute is untouched and the
    application is none the wiser."""
    state = _field(observed, "afterWrongType")
    assert state["strict"] == 0
    assert state["strictType"] == "int"


def test_a_validator_converts_what_it_can(observed: dict[str, object]) -> None:
    """`validate=int` is a conversion, not only a gate: a page sending `"17"` - which is
    what an `<input>` value is - should not need the page to know it must send a number."""
    state = _field(observed, "afterCoercible")
    assert state["strict"] == 17
    assert state["strictType"] == "int"


# --- errors that say something -----------------------------------------------


def test_a_decode_failure_names_its_channel(observed: dict[str, object]) -> None:
    """In a browser the only diagnostic is a console nobody has open, so `Expecting value:
    line 1 column 1` on its own names nothing anyone can act on."""
    report = _field(observed, "decodeError")
    error = report["error"]
    assert isinstance(error, str)
    assert "decode" in error, f"the channel is not named: {error}"
    assert "could not decode" in error


def test_the_app_cannot_send_what_json_cannot_carry(observed: dict[str, object]) -> None:
    """NaN and Infinity are the ones with teeth. `json.dumps` writes the bare token `NaN`,
    which `JSON.parse` rejects - so without `allow_nan=False` an application that divided by
    zero would fail inside a page listener with nothing pointing back at the sender."""
    outcomes = _field(_field(observed, "sendBad"), "outcomes")
    for name in ("nan", "inf", "object"):
        message = outcomes[name]
        assert isinstance(message, str)
        assert "could not encode" in message, f"{name} was sent: {message}"
        assert "never-arrives" in message, f"{name} did not name its channel: {message}"


# --- the pipe carries what it is given ---------------------------------------


def test_hostile_text_survives_the_raw_pipe_unchanged(observed: dict[str, object]) -> None:
    """Through the page, a structured clone, Python, and back. Anything that decoded,
    re-encoded or normalised on the way would mangle at least one of these characters."""
    assert observed["echoed"] == HOSTILE_TEXT
    assert observed["echoSent"] == HOSTILE_TEXT


def test_a_two_megabyte_payload_crosses_intact(observed: dict[str, object]) -> None:
    """Not a performance assertion - it is about whether anything truncates."""
    large = _field(observed, "large")
    assert large["echoed"] == large["sent"]


# --- coalescing ---------------------------------------------------------------


def test_send_latest_keeps_only_the_newest_value(observed: dict[str, object]) -> None:
    """500 sends in a synchronous loop become one message, because the loop never yields and
    the frame it schedules fires once, after it.

    This is the documented answer to the channel having no backpressure, and the assertion
    is that it really does drop - a coalescing send that quietly delivered everything would
    be worse than not having one.
    """
    state = _field(observed, "coalescing")
    assert state["loose"] == "499", "the newest value is the one that should arrive"
    assert state["looseType"] == "int"
