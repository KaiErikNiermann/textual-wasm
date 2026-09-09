"""Run one application on every runtime available, and compare what they did.

This is the project's strongest claim made available to someone else's code. The spike
answered "does Textual work under WASM" for one demo app; `check` answers it for yours, on
as many of four runtimes as this machine can offer:

* **native** - CPython, the app as a terminal TUI. The baseline.
* **wasm** - the same source under Pyodide in Node. Settles everything on the Python side.
* **browser** - a real `build` served by a real `dev`, driven by Chrome. Settles rendering.
* **terminal** - the app on a real pty through Textual's own driver, via tmux. The reference
  the browser render is judged against, because a browser matching a *replay* of the stream
  is a weaker claim than a browser matching what a user would actually see.

Two of those need tools this package cannot install, and one needs a terminal multiplexer.
So a leg that cannot run is *reported as skipped, with the command that would fix it*, and
the legs that did run still produce a verdict. A check that fails for a missing tool teaches
people to ignore its result; a check that silently drops half its legs is worse.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import re
import subprocess  # textual-wasm: allow subprocess.run - runs the native leg, native-only
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from textual_wasm import node
from textual_wasm.bundler import BuildSpec, background_server
from textual_wasm.bundler import build as build_site
from textual_wasm.compare import Comparison, compare_screens
from textual_wasm.compare import compare as compare_reports
from textual_wasm.driver import DEFAULT_SIZE
from textual_wasm.pins import resolve_pins
from textual_wasm.report import ProbeReport, screen_from
from textual_wasm.terminal import capture_target
from textual_wasm.terminal import usable as terminal_usable

if TYPE_CHECKING:
    from textual_wasm.screen import LineDiff, RenderedScreen
    from textual_wasm.target import AppTarget

_log: Final = logging.getLogger(__name__)

DEFAULT_BROWSER: Final[str] = "chromium"
"""Engine used when none is named.

Playwright's own build rather than an installed Chrome, so that a check produces the same
answer on a developer's machine as in CI. `chrome` and `msedge` drive the installed browsers
when what you want is the one your users actually have.
"""

BROWSERS: Final[tuple[str, ...]] = (
    "chromium",
    "firefox",
    "webkit",
    "chrome",
    "msedge",
    "safari",
)
"""What `--browser` accepts.

The three engines, two channels for installed browsers, and Safari. `msedge` is Chromium with
the same `xterm.js` on top - accepted for completeness, and not part of the matrix, because
running it measures the same renderer twice.
"""

_SAFARI: Final[str] = "safari"
"""Driven through WebDriver rather than Playwright, which has no channel for it. Needs macOS
and a one-time `sudo safaridriver --enable`."""

MOUNT_ROOT: Final[str] = "/mnt/src"
"""Where the harness mounts each package inside Pyodide's filesystem.

Each package is mounted at its own point under here rather than mounting a whole
`site-packages`: that directory holds native extensions Pyodide cannot load, and putting it
on `sys.path` would shadow the wheels micropip just installed.
"""

PROBE_TIMEOUT: Final[float] = 300.0


class Leg(enum.StrEnum):
    """The runtimes a check can cover."""

    NATIVE = "native"
    WASM = "wasm"
    BROWSER = "browser"
    TERMINAL = "terminal"


class LegStatus(enum.StrEnum):
    """What happened to one leg."""

    RAN = "ran"
    SKIPPED = "skipped"
    """The machine cannot run it. Not a failure - `detail` says what would fix it."""

    FAILED = "failed"


@dataclasses.dataclass(frozen=True, slots=True)
class LegOutcome:
    """One runtime's participation in a check."""

    leg: Leg
    status: LegStatus
    detail: str


@dataclasses.dataclass(frozen=True, slots=True)
class CheckReport:
    """What every runtime did, and whether they agreed."""

    target: str
    size: tuple[int, int]
    legs: tuple[LegOutcome, ...]

    runtimes: Comparison | None = None
    """Native against WASM: checks, runtime facts and replayed grids."""

    render_diffs: tuple[LineDiff, ...] | None = None
    """A real terminal against the browser, or None if either leg did not run."""

    @property
    def skipped(self) -> tuple[LegOutcome, ...]:
        return tuple(leg for leg in self.legs if leg.status is LegStatus.SKIPPED)

    @property
    def failed(self) -> tuple[LegOutcome, ...]:
        return tuple(leg for leg in self.legs if leg.status is LegStatus.FAILED)

    @property
    def ok(self) -> bool:
        """True when nothing failed and everything that ran agreed.

        A skipped leg is deliberately not a failure here; `strict` at the command line is
        how a CI run says it wants the whole matrix.
        """
        return (
            not self.failed
            and (self.runtimes is None or self.runtimes.equivalent)
            and not self.render_diffs
        )


def _target_arguments(target: AppTarget) -> list[str]:
    """The command-line form of a target, for handing to a subprocess."""
    arguments = ["--app", target.entry, "--keys", target.keys]
    if target.ready_marker is not None:
        arguments += ["--ready-marker", target.ready_marker]
    if target.settled_marker is not None:
        arguments += ["--settled-marker", target.settled_marker]
    return arguments


def _native_leg(target: AppTarget, size: tuple[int, int]) -> tuple[LegOutcome, ProbeReport | None]:
    """Run the probe in a fresh interpreter through the shipped CLI.

    A subprocess rather than an in-process call because `import_purity` asserts on
    `sys.modules`, which is interpreter-global: measured from inside a process that has
    already imported this whole package it would be measuring the wrong thing. It is also
    the more faithful comparison, since every other leg is a fresh process too.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "textual_wasm",
            "probe",
            "--json",
            *_target_arguments(target),
            "--width",
            str(size[0]),
            "--height",
            str(size[1]),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=PROBE_TIMEOUT,
    )
    if not completed.stdout.strip():
        return (
            LegOutcome(Leg.NATIVE, LegStatus.FAILED, completed.stderr.strip()[-400:]),
            None,
        )
    report = ProbeReport.from_json(completed.stdout)
    detail = f"{len(report.checks)} checks, {len(report.failures)} failed"
    status = LegStatus.RAN if report.ok else LegStatus.FAILED
    return LegOutcome(Leg.NATIVE, status, detail), report


def _wasm_config(target: AppTarget, size: tuple[int, int], resolve_from: Path) -> dict[str, object]:
    """Everything the Pyodide harness needs, as JSON."""
    packages = [Path(__file__).parent, target.package_directory()]
    mounts = [
        {"root": str(package), "point": f"{MOUNT_ROOT}/{package.name}"}
        for package in dict.fromkeys(packages)
    ]
    return {
        "resolveFrom": str(resolve_from),
        "entryScript": str(node.HARNESS_DIR / "wasm_entry.py"),
        "requirements": list(resolve_pins()),
        "mounts": mounts,
        "sys_path": [MOUNT_ROOT],
        "target": dataclasses.asdict(target),
        "columns": size[0],
        "rows": size[1],
    }


def _wasm_leg(target: AppTarget, size: tuple[int, int]) -> tuple[LegOutcome, ProbeReport | None]:
    """Run the same probe under Pyodide, if Node and the pyodide package are here."""
    available = node.availability([node.PYODIDE_PACKAGE])
    if not available.available or available.node is None or available.resolve_from is None:
        return LegOutcome(Leg.WASM, LegStatus.SKIPPED, available.reason), None

    result = node.run_harness(
        "pyodide-probe.mjs",
        _wasm_config(target, size, available.resolve_from),
        node=available.node,
    )
    report = ProbeReport.from_json(json.dumps(result.payload))
    status = LegStatus.RAN if result.ok and report.ok else LegStatus.FAILED
    return LegOutcome(Leg.WASM, status, f"{len(report.failures)} check(s) failed"), report


def _browser_leg(
    target: AppTarget, size: tuple[int, int], browser: str
) -> tuple[LegOutcome, RenderedScreen | None]:
    """Build the app, serve it, and read the grid a real browser engine renders."""
    driver_package = node.SELENIUM_PACKAGE if browser == _SAFARI else node.PLAYWRIGHT_PACKAGE
    script = "safari-check.mjs" if browser == _SAFARI else "browser-check.mjs"
    available = node.availability([driver_package])
    if not available.available or available.node is None or available.resolve_from is None:
        return (
            LegOutcome(Leg.BROWSER, LegStatus.SKIPPED, f"{available.reason} {node.BROWSER_HINT}"),
            None,
        )

    try:
        with tempfile.TemporaryDirectory(prefix="textual-wasm-site-") as directory:
            built = build_site(
                BuildSpec(
                    entry=target.entry,
                    package=target.package_directory(),
                    output=Path(directory),
                )
            )
            _log.debug("built %s for the browser leg", built.summary)
            with background_server(Path(directory)) as url:
                result = node.run_harness(
                    script,
                    {
                        "resolveFrom": str(available.resolve_from),
                        "url": url,
                        "columns": size[0],
                        "rows": size[1],
                        "browser": browser,
                        "target": dataclasses.asdict(target),
                    },
                    node=available.node,
                )
    except node.HarnessError as error:
        # A driver that will not start - an engine that was never downloaded, a missing system
        # library - is a fact about this machine, and reporting it as a traceback buries the
        # one line that says which. Every other unavailable runtime here names its own fix.
        return LegOutcome(Leg.BROWSER, LegStatus.FAILED, _first_lines(str(error))), None

    screen = screen_from(_screen_object(result.payload))
    if not result.ok:
        # The page rendered, but it also logged errors - which is a failure of the claim
        # being made, since nobody watching a browser console is the normal case.
        return LegOutcome(Leg.BROWSER, LegStatus.FAILED, result.stderr.strip()[-400:]), screen
    detail = f"{_engine_description(result.payload)}, {len(screen.lines)} rows rendered"
    return LegOutcome(Leg.BROWSER, LegStatus.RAN, detail), screen


_NOISE: Final[re.Pattern[str]] = re.compile(
    r"^(node:internal|\s*at\s|\s*\^|Node\.js v|\s*throw\b|\s*\}|\s*\{)"
)
"""Lines that are the runtime talking about itself rather than about the failure."""

_BOX: Final[str] = "╔╗╚╝║═│┌┐└┘─"
"""Drivers print their advice inside a drawn box, which survives into a table cell as noise."""


def _first_lines(message: str, limit: int = 4) -> str:
    """The informative lines of a harness failure.

    A driver that cannot start says why - "Host system is missing dependencies", and the
    command that fixes it - but says it inside a drawn box, under a Node stack trace. Dropping
    the frames and the box art is the difference between a cell someone can act on and a cell
    they skim past.
    """
    lines: list[str] = []
    for raw in message.splitlines():
        line = raw.strip().strip(_BOX).strip()
        if line and not _NOISE.match(raw.strip()):
            lines.append(line)
    return " ".join(lines[:limit])[:400]


def _engine_description(payload: dict[str, object]) -> str:
    """Name the engine a capture came from, so a report says which browser it is about."""
    runtime = payload.get("runtime")
    if not isinstance(runtime, dict):
        return "unknown browser"
    facts = cast("dict[str, object]", runtime)
    return f"{facts.get('browser', '?')} {facts.get('browser_version', '')}".strip()


def _screen_object(payload: dict[str, object]) -> dict[str, object]:
    """Pull the grid out of a harness payload.

    Raises:
        node.HarnessError: If there is none, which means the harness returned something
            other than what it documents.
    """
    screen = payload.get("screen")
    if not isinstance(screen, dict):
        raise node.HarnessError("harness payload carries no 'screen' object")
    return dict(screen)  # pyright: ignore[reportUnknownArgumentType] - checked above


def _terminal_leg(
    target: AppTarget, size: tuple[int, int]
) -> tuple[LegOutcome, RenderedScreen | None]:
    """Capture the app from a real terminal, if one that can be trusted is installed."""
    ready, reason = terminal_usable()
    if not ready:
        return LegOutcome(Leg.TERMINAL, LegStatus.SKIPPED, reason), None
    grid = capture_target(target, columns=size[0], rows=size[1])
    return LegOutcome(Leg.TERMINAL, LegStatus.RAN, reason), grid


def _runtime_comparison(native: ProbeReport | None, wasm: ProbeReport | None) -> Comparison | None:
    return None if native is None or wasm is None else compare_reports(native, wasm)


def _render_comparison(
    terminal: RenderedScreen | None, browser: RenderedScreen | None
) -> tuple[LineDiff, ...] | None:
    """Diff the real terminal against the browser, if both legs ran.

    Deliberately not native-against-browser: the native grid is a `pyte` replay, and pyte
    discards the rest of a line after a zero-width joiner, so an app containing emoji would
    be reported as a browser bug that is really an artefact of the oracle.
    """
    return None if terminal is None or browser is None else compare_screens(terminal, browser)


def run_check(
    target: AppTarget,
    *,
    size: tuple[int, int] = DEFAULT_SIZE,
    browser: str = DEFAULT_BROWSER,
) -> CheckReport:
    """Run `target` on every runtime this machine offers and compare the results.

    Args:
        target: The application, and the text that says it is ready and settled.
        size: The grid every leg is forced to, so the renders are comparable at all.
        browser: Which engine the browser leg uses. One of :data:`BROWSERS`.

    Returns:
        What each leg did, and the two comparisons that can be made from what ran.
    """
    native_outcome, native = _native_leg(target, size)
    wasm_outcome, wasm = _wasm_leg(target, size)
    browser_outcome, browser_screen = _browser_leg(target, size, browser)
    terminal_outcome, terminal = _terminal_leg(target, size)
    return CheckReport(
        target=target.entry,
        size=size,
        legs=(native_outcome, wasm_outcome, browser_outcome, terminal_outcome),
        runtimes=_runtime_comparison(native, wasm),
        render_diffs=_render_comparison(terminal, browser_screen),
    )
