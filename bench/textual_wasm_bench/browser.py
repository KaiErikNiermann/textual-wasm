"""Run one case once, in a fresh browser, through `bench/harness/bench.mjs`."""

from __future__ import annotations

import dataclasses
from typing import Any, Final, cast

from textual_wasm import node
from textual_wasm_bench import paths
from textual_wasm_bench.plan import PAGES, Case, Engine, Mode

HARNESS: Final[str] = "bench.mjs"

TIMEOUT_SECONDS: Final[float] = 1800.0
"""A 200,000-message flood in a slow engine is minutes; a hung one is not worth more."""

NODE_PACKAGES: Final[tuple[str, ...]] = (node.PLAYWRIGHT_PACKAGE, "pidtree", "pidusage")


class BenchmarkError(RuntimeError):
    """A scenario failed. The harness's stderr is in the message, page console included."""


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    """What one run of one case measured, and in which browser build."""

    browser_version: str
    data: dict[str, Any]


def require_node() -> node.NodeAvailability:
    """Node with Playwright and the process samplers, or a failure saying what is missing."""
    available = node.availability(list(NODE_PACKAGES))
    if not available.available or available.node is None or available.resolve_from is None:
        raise BenchmarkError(f"{available.reason} {node.BROWSER_HINT}")
    return available


def run_case(
    case: Case,
    *,
    engine: Engine,
    mode: Mode,
    base_url: str,
    available: node.NodeAvailability,
) -> Outcome:
    """Drive `case` once and return what the harness measured.

    Raises:
        BenchmarkError: If the harness failed, with everything it said on stderr.
    """
    page = PAGES[case.layer]
    if available.node is None:
        raise BenchmarkError("no Node binary; call require_node() first")
    result = node.run_harness(
        HARNESS,
        {
            "resolveFrom": str(available.resolve_from),
            "engine": str(engine),
            "url": page.url(base_url, mode),
            "readyText": page.ready_text,
            "probe": page.probe,
            "scenario": case.scenario,
            "params": dict(case.params),
        },
        node=available.node,
        timeout=TIMEOUT_SECONDS,
        directory=paths.HARNESS,
    )
    if not result.ok:
        raise BenchmarkError(f"{case.name} on {engine}/{mode} failed:\n{result.stderr}")
    version = result.payload.get("browserVersion")
    data = result.payload.get("data")
    if not isinstance(version, str) or not isinstance(data, dict):
        raise BenchmarkError(f"{case.name}: the harness returned an unexpected shape")
    return Outcome(browser_version=version, data=cast("dict[str, Any]", data))
