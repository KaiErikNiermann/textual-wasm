"""The benchmark infrastructure, kept honest by the suite.

Two halves. The plain tests check the plan and the arithmetic and run the native controls,
which need no browser. The browser tests run a smoke-sized benchmark through the real
harness and assert only what is *counted* - frames written, messages received, the order of
boot marks - never a duration or a percentage: a timing threshold flakes on a loaded runner,
and a count either matches or the code changed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from textual_wasm import node
from textual_wasm_bench import native, results
from textual_wasm_bench.plan import FULL, PAGES, PROFILES, SMOKE, Engine, Layer, Mode, cases
from textual_wasm_bench.runner import Selection, run
from textual_wasm_bench.summary import median, p95, slope


def test_every_layer_has_a_page() -> None:
    assert set(PAGES) == set(Layer)


def test_profiles_differ_only_in_size() -> None:
    """Smoke exists to exercise the same harness paths the full run takes."""
    assert [case.name for case in cases(SMOKE)] == [case.name for case in cases(FULL)]


def test_case_names_are_unique() -> None:
    names = [case.name for case in cases(FULL)]
    assert len(names) == len(set(names))


def test_profiles_are_registered() -> None:
    assert set(PROFILES) == {"full", "smoke"}


def test_statistics() -> None:
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert p95([5.0]) == 5.0
    assert p95([float(value) for value in range(1, 101)]) == pytest.approx(95.05)
    assert slope([1.0, 3.0, 5.0]) == pytest.approx(2.0)
    assert slope([1.0]) is None


@pytest.mark.slow
def test_native_controls_lose_nothing() -> None:
    """The bridge, fed directly, delivers every message - the control is only a control if
    it does the same work as the browser run."""
    measured = native.controls(SMOKE)
    assert [run["received"] for run in measured["drain"]["runs"]] == [SMOKE.drain_messages] * (
        SMOKE.repeats
    )
    assert len(measured["leakChurn"]["interpreter"]) == SMOKE.leak_rounds + 1


# --- through a real browser ------------------------------------------------------------

BROWSER_CASES = ("idle/app", "boot/app", "drain", "flood", "latest", "leak/bridge")


@pytest.fixture(scope="module")
def smoke(tmp_path_factory: pytest.TempPathFactory) -> results.ResultFile:
    """One smoke run on Chromium, in both modes, for the cases asserted below."""
    if not node.availability([node.PLAYWRIGHT_PACKAGE, "pidtree", "pidusage"]).available:
        pytest.skip(f"no browser to drive. {node.BROWSER_HINT}")
    out: Path = tmp_path_factory.mktemp("bench") / "smoke.json"
    return run(
        "smoke",
        out,
        Selection(
            engines=(Engine.CHROMIUM,),
            modes=(Mode.MAIN, Mode.WORKER),
            only=BROWSER_CASES,
            include_native=False,
        ),
    )


def _runs(data: results.ResultFile, mode: str, case: str) -> list[dict[str, Any]]:
    return data["records"][f"chromium/{mode}/{case}"]["runs"]


MODES = pytest.mark.parametrize("mode", ["main", "worker"])


@pytest.mark.browser
@pytest.mark.slow
@MODES
def test_an_idle_static_app_writes_nothing(smoke: results.ResultFile, mode: str) -> None:
    """The sanity check behind the idle CPU numbers: no redraw loop, no stray frames."""
    assert [run["writes"] for run in _runs(smoke, mode, "idle/app")] == [0] * SMOKE.idle_repeats


@pytest.mark.browser
@pytest.mark.slow
@MODES
def test_the_page_is_published_only_after_the_app_has_drawn(
    smoke: results.ResultFile, mode: str
) -> None:
    """On the main thread the page once announced itself ready 600ms before the first frame.

    The boot marks must also be in order, since the boot table subtracts adjacent ones.
    """
    for boot in _runs(smoke, mode, "boot/app"):
        assert boot["writesAtPublish"] >= 1
        marks = boot["marks"]
        assert marks["interpreter"] < marks["packages"] < marks["app"] < marks["ready"]


@pytest.mark.browser
@pytest.mark.slow
@MODES
@pytest.mark.parametrize(
    ("case", "count"), [("drain", SMOKE.drain_messages), ("flood", SMOKE.flood_messages)]
)
def test_a_burst_arrives_whole(smoke: results.ResultFile, mode: str, case: str, count: int) -> None:
    received = [entry["received"] for entry in _runs(smoke, mode, case)[0]["runs"]]
    assert set(received) == {count}


@pytest.mark.browser
@pytest.mark.slow
@MODES
def test_send_latest_coalesces_a_frame_into_one_message(
    smoke: results.ResultFile, mode: str
) -> None:
    assert _runs(smoke, mode, "latest")[0]["received"] == 1
