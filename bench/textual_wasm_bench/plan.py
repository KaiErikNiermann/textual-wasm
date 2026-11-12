"""What a benchmark run measures: the pages, the scenarios, and the sizes for each profile.

Everything a run does is a `Case` here, so a run is reproducible from its profile name and
a result file can be read back against the plan that produced it.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, Literal

from bench_apps.idle import READY_TEXT as IDLE_READY
from bench_apps.probe import READY_TEXT as PROBE_READY


class Engine(enum.StrEnum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class Mode(enum.StrEnum):
    """Where the interpreter runs. `NONE` for a page with no interpreter to place."""

    MAIN = "main"
    WORKER = "worker"
    NONE = "-"


class Site(enum.StrEnum):
    """The builds a run serves, one per app per mode."""

    PROBE = "probe"
    IDLE = "idle"


SITE_ENTRIES: Final[Mapping[Site, str]] = MappingProxyType(
    {Site.PROBE: "bench_apps.probe:BenchProbe", Site.IDLE: "bench_apps.idle:BlinkingInput"}
)


class Layer(enum.StrEnum):
    """One rung of the attribution ladder, from an empty tab up to a running app.

    Ordered: each layer is the one before it plus one thing, and that one thing is what the
    difference between them measures.
    """

    BLANK = "blank"
    """`about:blank` in the same browser: the engine's own cost, before any page."""
    PYODIDE = "pyodide"
    """An interpreter booted and doing nothing."""
    TEXTUAL = "textual"
    """The build's requirements installed and Textual imported, still running nothing."""
    TICK = "tick"
    """The above plus the driver's 50ms parser timer, and nothing else of the driver."""
    APP = "app"
    """The benchmark app: static, running, idle."""
    INPUT = "input"
    """An app with a focused, blinking input: the common case above the floor."""


@dataclasses.dataclass(frozen=True, slots=True)
class Page:
    """How to reach one layer: which site, which file, and what says it is running."""

    site: Site | None
    path: str
    ready_text: str | None
    probe: bool
    """Whether the page runs the benchmark app and so answers on the data channel."""

    def url(self, base: str, mode: Mode) -> str:
        """The page's full URL, given its site's base URL."""
        if self.site is None:
            return self.path
        if self.ready_text is None:
            return f"{base}{self.path}&worker={int(mode is Mode.WORKER)}"
        return f"{base}{self.path}"


PAGES: Final[Mapping[Layer, Page]] = MappingProxyType(
    {
        Layer.BLANK: Page(site=None, path="about:blank", ready_text=None, probe=False),
        Layer.PYODIDE: Page(Site.PROBE, "baseline.html?level=pyodide", None, probe=False),
        Layer.TEXTUAL: Page(Site.PROBE, "baseline.html?level=textual", None, probe=False),
        Layer.TICK: Page(Site.PROBE, "baseline.html?level=tick", None, probe=False),
        Layer.APP: Page(Site.PROBE, "index.html", PROBE_READY, probe=True),
        Layer.INPUT: Page(Site.IDLE, "index.html", IDLE_READY, probe=False),
    }
)

Scenario = Literal[
    "boot", "idle", "latency", "drain", "payload", "latest", "stall", "control", "leak"
]


@dataclasses.dataclass(frozen=True, slots=True)
class Case:
    """One measurement: a scenario on a page, with its sizes and how often to repeat it.

    Each repeat is a separate browser, so `repeats` is the number of independent samples
    of the whole scenario rather than of something inside it.
    """

    name: str
    scenario: Scenario
    layer: Layer
    params: Mapping[str, object]
    repeats: int = 1

    @property
    def per_mode(self) -> bool:
        """Whether the case runs once per interpreter placement, or once in total."""
        return PAGES[self.layer].site is not None


def _layers_case(
    scenario: Scenario, params: Mapping[str, object], repeats: int
) -> tuple[Case, ...]:
    """The same scenario on every layer, which is what makes its numbers attributable."""
    return tuple(
        Case(f"{scenario}/{layer}", scenario, layer, MappingProxyType(dict(params)), repeats)
        for layer in Layer
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Sizes:
    """Every count and duration a profile chooses. Smoke and full differ only here."""

    idle_window_ms: int
    idle_settle_ms: int
    idle_repeats: int
    boot_repeats: int
    latency_trips: int
    drain_messages: int
    flood_messages: int
    payload_bytes: tuple[int, ...]
    latest_calls: int
    stall_messages: int
    repeats: int
    self_flood: int
    spin: int
    churn: int
    leak_rounds: int
    leak_messages: int
    leak_widgets: int


MEBIBYTE: Final[int] = 1 << 20

FULL: Final[Sizes] = Sizes(
    idle_window_ms=10_000,
    idle_settle_ms=3_000,
    idle_repeats=3,
    boot_repeats=3,
    latency_trips=1_000,
    drain_messages=10_000,
    flood_messages=200_000,
    payload_bytes=(MEBIBYTE, 8 * MEBIBYTE),
    latest_calls=20_000,
    stall_messages=5_000,
    repeats=5,
    self_flood=10_000,
    spin=3_000_000,
    churn=200,
    leak_rounds=10,
    leak_messages=5_000,
    leak_widgets=200,
)

SMOKE: Final[Sizes] = Sizes(
    idle_window_ms=2_000,
    idle_settle_ms=1_000,
    idle_repeats=1,
    boot_repeats=1,
    latency_trips=50,
    drain_messages=500,
    flood_messages=2_000,
    payload_bytes=(64 * 1024,),
    latest_calls=500,
    stall_messages=500,
    repeats=2,
    self_flood=500,
    spin=100_000,
    churn=20,
    leak_rounds=4,
    leak_messages=500,
    leak_widgets=50,
)

PROFILES: Final[Mapping[str, Sizes]] = MappingProxyType({"full": FULL, "smoke": SMOKE})


def cases(sizes: Sizes) -> tuple[Case, ...]:
    """Every case a run with these sizes performs, in the order it performs them."""
    idle = {"windowMs": sizes.idle_window_ms, "settleMs": sizes.idle_settle_ms}
    channel = (
        Case("latency", "latency", Layer.APP, {"n": sizes.latency_trips}),
        Case("drain", "drain", Layer.APP, {"n": sizes.drain_messages, "repeats": sizes.repeats}),
        Case("flood", "drain", Layer.APP, {"n": sizes.flood_messages, "repeats": 1}),
        Case(
            "payload",
            "payload",
            Layer.APP,
            {"sizes": list(sizes.payload_bytes), "repeats": sizes.repeats},
        ),
        Case("latest", "latest", Layer.APP, {"n": sizes.latest_calls}),
        Case("stall", "stall", Layer.APP, {"n": sizes.stall_messages, "repeats": sizes.repeats}),
        Case(
            "control",
            "control",
            Layer.APP,
            {
                "selfFlood": sizes.self_flood,
                "spin": sizes.spin,
                "churn": sizes.churn,
                "repeats": sizes.repeats,
            },
        ),
        Case(
            "leak/bridge",
            "leak",
            Layer.APP,
            {"rounds": sizes.leak_rounds, "perRound": sizes.leak_messages, "workload": "bridge"},
        ),
        Case(
            "leak/churn",
            "leak",
            Layer.APP,
            {"rounds": sizes.leak_rounds, "perRound": sizes.leak_widgets, "workload": "churn"},
        ),
    )
    return (
        *_layers_case("idle", idle, sizes.idle_repeats),
        *_layers_case(
            "boot", {"settleMs": sizes.idle_settle_ms, "warm": False}, sizes.boot_repeats
        ),
        Case(
            "boot/app-warm",
            "boot",
            Layer.APP,
            {"settleMs": sizes.idle_settle_ms, "warm": True},
            sizes.boot_repeats,
        ),
        *channel,
    )


def record_key(engine: Engine | Literal["native"], mode: Mode, case: str) -> str:
    """The key a result is stored under. Stable, so a rerun replaces rather than duplicates."""
    return f"{engine}/{mode}/{case}"
