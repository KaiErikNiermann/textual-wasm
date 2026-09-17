"""The data channel, measured in a real browser, on the main thread and in a Web Worker.

`test_bridge.py` proves the Python side against a fake page, which is most of the behaviour
and none of the risk. The risk is the seam: two transports, written in JavaScript, either
side of a boundary that the unit tests replace with a direct call. A channel that works on
the main thread and quietly drops messages in a worker would pass every test in that file.

So this asserts the two modes by running the *same* harness against both builds and
comparing what came back. The comparison is the point: an assertion that each mode works
would still pass if they worked differently.

Marked slow and browser because each case builds a site and boots a real Pyodide in a real
Chromium, which is about a minute for the pair.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Final

import pytest

from textual_wasm import node
from textual_wasm.bundler import BuildSpec, background_server, build

pytestmark = [pytest.mark.slow, pytest.mark.browser]

HARNESS: Final[str] = "bridge-round-trip.mjs"
HARNESS_DIR: Final[Path] = Path(__file__).parent / "harness"
BRIDGE_APP: Final[str] = "tests.bridge_app:BridgeApp"
PACKAGE: Final[Path] = Path(__file__).parent

RAW_PAYLOAD: Final[str] = "not json \x1b[31m \x00 done"
"""What the harness puts on the raw channel. Text the pipe carries only if nothing along the
way decodes it: an escape sequence the terminal leg would act on, and a null JSON refuses."""


def _run(*, worker: bool) -> dict[str, object]:
    """Build the fixture app, serve it, and drive the channel through a real browser."""
    available = node.availability([node.PLAYWRIGHT_PACKAGE])
    if not available.available or available.node is None or available.resolve_from is None:
        raise RuntimeError(f"{available.reason} {node.BROWSER_HINT}")

    with tempfile.TemporaryDirectory(prefix="textual-wasm-bridge-") as directory:
        build(
            BuildSpec(
                entry=BRIDGE_APP,
                package=PACKAGE,
                output=Path(directory),
                worker=worker,
                # The fixture lives in `tests/`, which is not an installed package, so the
                # entry cannot be imported to be verified. The harness importing it inside
                # Pyodide is the verification.
                verify_entry=False,
            )
        )
        with background_server(Path(directory)) as url:
            result = node.run_harness(
                HARNESS,
                {
                    "resolveFrom": str(available.resolve_from),
                    "url": url,
                    "worker": worker,
                },
                node=available.node,
                directory=HARNESS_DIR,
            )

    if not result.ok:
        raise RuntimeError(f"the bridge harness failed:\n{result.stderr}")
    return result.payload


@pytest.fixture(scope="module")
def browser_available() -> None:
    """Skip the module rather than fail it when this machine has no browser to drive."""
    available = node.availability([node.PLAYWRIGHT_PACKAGE])
    if not available.available:
        pytest.skip(f"{available.reason} {node.BROWSER_HINT}")


@pytest.fixture(scope="module")
def on_main_thread(browser_available: None) -> dict[str, object]:
    return _run(worker=False)


@pytest.fixture(scope="module")
def in_worker(browser_available: None) -> dict[str, object]:
    return _run(worker=True)


@pytest.fixture(params=["main", "worker"], scope="module")
def either_mode(
    request: pytest.FixtureRequest,
    on_main_thread: dict[str, object],
    in_worker: dict[str, object],
) -> dict[str, object]:
    """Every behavioural assertion runs against both builds.

    Parametrised rather than duplicated, because a claim that holds in one mode and not the
    other is the failure this file exists for, and a copied assertion is how one of the two
    copies ends up quietly deleted.
    """
    return on_main_thread if request.param == "main" else in_worker


def test_the_app_publishes_its_state_before_the_page_subscribes(
    either_mode: dict[str, object],
) -> None:
    """`bind(initial=True)` sends during `on_mount`, which is before a page that polls for
    `globalThis.textualWasm` can have registered anything. The relay is what makes that
    arrive rather than vanish, and it is the difference between a page that loads in step
    and one that loads showing whatever its markup happened to declare."""
    assert either_mode["initial"] == ["0"]


def test_a_page_value_reaches_a_bound_reactive(either_mode: dict[str, object]) -> None:
    """The slider case, end to end: the page sends a number, Textual repaints the grid."""
    assert either_mode["applied"] == "gain=42"


def test_the_raw_pipe_does_not_interpret_what_it_carries(
    either_mode: dict[str, object],
) -> None:
    """A round trip of text that only survives untouched: through the page, into Python as
    a `BridgeMessage`, back out via `send_text`, and onto a page listener."""
    assert either_mode["echoed"] == [RAW_PAYLOAD]


def test_a_change_inside_the_app_reaches_the_page(either_mode: dict[str, object]) -> None:
    """The direction that did not exist before this module, triggered by a keystroke so that
    nothing the page sent can explain the value.

    Two payloads, not three, and the missing one is the assertion: 0 on mount, then 52 after
    the keystroke added ten to the 42 the page sent. The 42 itself never comes back, because
    a value the page just sent is the one thing it does not need to be told about.
    """
    assert either_mode["fromApp"] == ["0", "52"]


def test_both_transports_behave_identically(
    on_main_thread: dict[str, object], in_worker: dict[str, object]
) -> None:
    """The claim the whole module is for, asserted as one comparison rather than inferred
    from two passing parametrisations.

    `--worker` is meant to be a performance flag. The moment it changes what an application
    can say to its page, it is an API flag, and every page written against one mode becomes
    a page that may or may not work in the other.
    """
    assert json.dumps(_observations(on_main_thread), sort_keys=True) == json.dumps(
        _observations(in_worker), sort_keys=True
    )


def _observations(payload: dict[str, object]) -> dict[str, object]:
    """Everything the harness saw, minus which mode saw it."""
    return {key: value for key, value in payload.items() if key != "runtime"}
