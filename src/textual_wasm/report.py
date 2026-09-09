"""Structured result types for the feasibility probe.

Everything the probe learns is expressed here rather than printed, so that the native run
and the Pyodide run produce byte-comparable JSON. The comparison is the experiment.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from collections.abc import Mapping
from typing import Final, cast

from textual_wasm.screen import RenderedScreen, normalise


class CheckId(enum.StrEnum):
    """The individual claims the feasibility study makes, one per check."""

    IMPORT_PURITY = "import_purity"
    """`import textual.app` must not pull a POSIX terminal module into `sys.modules`."""

    DRIVER_HOOK = "driver_hook"
    """`TEXTUAL_DRIVER` must select an out-of-tree `Driver` subclass."""

    RUN_ASYNC = "run_async"
    """`App.run_async()` must complete on the host runtime's event loop."""

    RESIZE_DELIVERED = "resize_delivered"
    """The driver-synthesised `Resize` must reach the app with the forced size."""

    ANSI_OUTPUT = "ansi_output"
    """The compositor must emit truecolor SGR, i.e. real terminal output to feed xterm.js."""

    WIDGET_RENDERED = "widget_rendered"
    """Composed widget text must appear in the captured stream."""

    KEY_INPUT = "key_input"
    """Bytes fed through `XTermParser` must drive an app-level binding."""

    TIMER = "timer"
    """`set_timer` must fire, proving asyncio timing works on the host loop."""


class CheckStatus(enum.StrEnum):
    """Outcome of a single check."""

    PASS = "pass"  # noqa: S105 - a check verdict, not a credential
    FAIL = "fail"
    SKIP = "skip"


@dataclasses.dataclass(frozen=True, slots=True)
class CheckResult:
    """One claim, its verdict, and the evidence that produced the verdict."""

    check: CheckId
    status: CheckStatus
    detail: str
    """Human-readable statement of what was observed."""


@dataclasses.dataclass(frozen=True, slots=True)
class RuntimeFacts:
    """Properties of the host runtime that shape what a Textual app may do there.

    These are reported rather than asserted: they differ legitimately between the native and
    WASM runs, and the differences are precisely the portability constraints the study needs.
    """

    platform: str
    python_version: str
    textual_version: str
    event_loop: str
    """Class name of the running event loop, e.g. `WebLoop` under Pyodide."""

    threads_available: bool
    """Whether `@work(thread=True)` can work here at all."""

    eager_task_factory_accepted: bool
    """Whether the loop honoured `set_task_factory`, which `App.run_async` attempts."""

    runtime: str
    """The host: "native", "Node.js/26", or a browser user-agent.

    Node and a browser disagree about several capabilities in both directions, so a fact
    gathered under one is not a fact about the other.
    """

    jspi: bool
    """Whether stack switching is available, letting synchronous Python await a promise."""

    shared_memory: bool
    """Whether SharedArrayBuffer exists. Gates interrupts and streaming - never threads."""

    cross_origin_isolated: bool | None
    """Whether the page is cross-origin isolated, or None outside a browser."""

    polyfills_applied: tuple[str, ...]
    """Runtime shims this host needed, so a WASM run can never look accidentally native."""


@dataclasses.dataclass(frozen=True, slots=True)
class ProbeReport:
    """The complete result of one probe run."""

    runtime: RuntimeFacts
    checks: tuple[CheckResult, ...]
    screen: RenderedScreen
    """The grid the emitted stream leaves behind, so runtimes can be compared on what they
    *render* and not only on the bytes they produce."""

    @property
    def ok(self) -> bool:
        """True when no check failed."""
        return all(result.status is not CheckStatus.FAIL for result in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Only the failing checks, in declaration order."""
        return tuple(r for r in self.checks if r.status is CheckStatus.FAIL)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialise to stable JSON so the two runtimes' reports can be diffed."""
        return json.dumps(dataclasses.asdict(self), indent=indent, default=str, sort_keys=True)

    @classmethod
    def from_json(cls, payload: str) -> ProbeReport:
        """Rebuild a report written by another runtime.

        The WASM run happens in a separate process under a separate interpreter, so its
        report reaches the comparison as text and has to be revalidated at that boundary
        rather than trusted.

        Raises:
            TypeError: If any field is present with the wrong JSON type.
            ValueError: If a check id or status is not one this build knows.
        """
        decoded: object = json.loads(payload)
        if not isinstance(decoded, dict):
            raise _wrong_type("report", "an object", decoded)
        report = cast("dict[str, object]", decoded)
        return cls(
            runtime=_runtime_from(_as_object(report, "runtime")),
            checks=tuple(_check_from(entry) for entry in _as_array(report, "checks")),
            screen=screen_from(_as_object(report, "screen")),
        )


def screen_from(source: Mapping[str, object]) -> RenderedScreen:
    """Rebuild a grid written by another runtime, or by the browser harness.

    Public because the browser report carries a screen and nothing else - it cannot run the
    Python checks - so the screen comparison has to be able to read one on its own.
    """
    return RenderedScreen(
        columns=_as_int(source, "columns"),
        rows=_as_int(source, "rows"),
        lines=normalise(tuple(str(line) for line in _as_array(source, "lines"))),
    )


def _wrong_type(label: str, expected: str, value: object) -> TypeError:
    """Build the one error message every boundary check in this module raises."""
    return TypeError(f"{label} must be {expected}, got {type(value).__name__}")


def _as_object(source: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = source.get(key)
    if not isinstance(value, dict):
        raise _wrong_type(repr(key), "an object", value)
    return cast("dict[str, object]", value)


def _as_array(source: Mapping[str, object], key: str) -> list[object]:
    value = source.get(key)
    if not isinstance(value, list):
        raise _wrong_type(repr(key), "an array", value)
    return cast("list[object]", value)


def _as_str(source: Mapping[str, object], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str):
        raise _wrong_type(repr(key), "a string", value)
    return value


def _as_int(source: Mapping[str, object], key: str) -> int:
    value = source.get(key)
    # bool is an int subclass; a JSON true here means the payload is wrong, not that it is 1.
    if not isinstance(value, int) or isinstance(value, bool):
        raise _wrong_type(repr(key), "an integer", value)
    return value


def _as_bool(source: Mapping[str, object], key: str) -> bool:
    value = source.get(key)
    if not isinstance(value, bool):
        raise _wrong_type(repr(key), "a boolean", value)
    return value


def _as_optional_bool(source: Mapping[str, object], key: str) -> bool | None:
    value = source.get(key)
    if value is not None and not isinstance(value, bool):
        raise _wrong_type(repr(key), "a boolean or null", value)
    return value


def _runtime_from(source: Mapping[str, object]) -> RuntimeFacts:
    return RuntimeFacts(
        platform=_as_str(source, "platform"),
        python_version=_as_str(source, "python_version"),
        textual_version=_as_str(source, "textual_version"),
        event_loop=_as_str(source, "event_loop"),
        threads_available=_as_bool(source, "threads_available"),
        eager_task_factory_accepted=_as_bool(source, "eager_task_factory_accepted"),
        runtime=_as_str(source, "runtime"),
        jspi=_as_bool(source, "jspi"),
        shared_memory=_as_bool(source, "shared_memory"),
        cross_origin_isolated=_as_optional_bool(source, "cross_origin_isolated"),
        polyfills_applied=tuple(str(item) for item in _as_array(source, "polyfills_applied")),
    )


def _check_from(entry: object) -> CheckResult:
    if not isinstance(entry, dict):
        raise _wrong_type("each check", "an object", entry)
    mapping = cast("dict[str, object]", entry)
    return CheckResult(
        check=CheckId(_as_str(mapping, "check")),
        status=CheckStatus(_as_str(mapping, "status")),
        detail=_as_str(mapping, "detail"),
    )


REPORT_SENTINEL: Final[str] = "TEXTUAL_WASM_PROBE_JSON"
"""Delimiter the Pyodide harness greps for, so stray runtime chatter cannot corrupt the report."""
