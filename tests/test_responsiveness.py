"""Pin the one claim worker mode makes that a render comparison cannot see.

`check` already proves a worker build draws the same cells as a real terminal. What it cannot
show is why anyone would build one, which is that a slow Python call stops freezing the page.
That is a measurement, so it is measured here rather than asserted in the documentation.

Marked slow because each case boots a real Pyodide in a real browser.
"""

from __future__ import annotations

import pytest

from textual_wasm import node
from textual_wasm.responsiveness import FROZEN_THRESHOLD_MS, Responsiveness, measure
from textual_wasm.target import AppTarget, resolve_target

pytestmark = [pytest.mark.slow, pytest.mark.browser]

BLOCKING_APP = "tests.blocking_app:BlockingApp"
BLOCK_KEY = "b"


def _target() -> AppTarget:
    return resolve_target(BLOCKING_APP, ready_marker="ready", keys=None, settled_marker=None)


@pytest.fixture(scope="module")
def browser_available() -> None:
    """Skip the module rather than fail it when this machine has no browser to drive."""
    available = node.availability([node.PLAYWRIGHT_PACKAGE])
    if not available.available:
        pytest.skip(f"{available.reason} {node.BROWSER_HINT}")


@pytest.fixture(scope="module")
def on_main_thread(browser_available: None) -> Responsiveness:
    return measure(_target(), worker=False, keys=BLOCK_KEY)


@pytest.fixture(scope="module")
def in_worker(browser_available: None) -> Responsiveness:
    return measure(_target(), worker=True, keys=BLOCK_KEY)


def test_main_thread_freezes_while_python_blocks(on_main_thread: Responsiveness) -> None:
    """The default build stalls the page, which is the limitation worker mode addresses.

    Asserted rather than assumed because it is the baseline the other half of this file is
    measured against: if this ever stops being true, the comparison below stops meaning
    anything and should fail loudly rather than keep passing.
    """
    assert not on_main_thread.responsive
    assert on_main_thread.longest_gap_ms is not None
    assert on_main_thread.longest_gap_ms > FROZEN_THRESHOLD_MS


def test_worker_keeps_the_page_responsive(in_worker: Responsiveness) -> None:
    """A worker build renders throughout the same call."""
    assert in_worker.responsive
    assert in_worker.longest_gap_ms is not None
    assert in_worker.longest_gap_ms < FROZEN_THRESHOLD_MS


def test_the_difference_is_large_enough_to_be_the_point(
    on_main_thread: Responsiveness, in_worker: Responsiveness
) -> None:
    """The gap between the two modes is an order of magnitude, not a measurement artefact.

    A factor of four is far below what was measured (1333ms against 16.8ms, so about 79x)
    and far above anything scheduling noise produces, which is the range a threshold wants
    to sit in: loose enough not to flake on a loaded CI runner, tight enough that a
    regression which quietly reintroduced main-thread execution could not pass.
    """
    assert on_main_thread.longest_gap_ms is not None
    assert in_worker.longest_gap_ms is not None
    assert in_worker.longest_gap_ms * 4 < on_main_thread.longest_gap_ms
