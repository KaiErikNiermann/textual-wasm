"""Structured result types for the feasibility probe.

Everything the probe learns is expressed here rather than printed, so that the native run
and the Pyodide run produce byte-comparable JSON. The comparison is the experiment.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from typing import Final


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

    polyfills_applied: tuple[str, ...]
    """Runtime shims this host needed, so a WASM run can never look accidentally native."""


@dataclasses.dataclass(frozen=True, slots=True)
class ProbeReport:
    """The complete result of one probe run."""

    runtime: RuntimeFacts
    checks: tuple[CheckResult, ...]

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


REPORT_SENTINEL: Final[str] = "TEXTUAL_WASM_PROBE_JSON"
"""Delimiter the Pyodide harness greps for, so stray runtime chatter cannot corrupt the report."""
