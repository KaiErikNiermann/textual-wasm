"""Capture what a real terminal renders, to use as the reference the other runtimes are
checked against.

`pyte` was the first oracle and turned out to have a blind spot exactly where the open
question was: it discards the rest of a line after a zero-width joiner or a variation
selector, so it cannot adjudicate emoji. This module replaces it with an actual terminal.

`tmux` is the choice because it is the only terminal emulator that will hand its screen back
as text. It runs the app on a real pty through Textual's own platform driver - not this
project's - so the reference is Textual behaving normally on a terminal, with nothing from
the WASM work in the path. A browser render that matches this is a browser render that
matches what a user would see.

Reproducibility comes from refusing the ambient environment: `-f /dev/null` ignores the
user's tmux config, `-u` forces UTF-8, and the status bar is turned off because it would
otherwise take one of the rows being compared.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess  # textual-wasm: allow subprocess.run - drives tmux, native-only
import sys
import time
import uuid
from typing import TYPE_CHECKING, Final

from textual_wasm.screen import RenderedScreen, normalise

if TYPE_CHECKING:
    from textual_wasm.target import AppTarget

TMUX: Final[str | None] = shutil.which("tmux")
"""The tmux binary, or None. Callers skip rather than fail: a machine without tmux can still
run every other part of the experiment."""

MINIMUM_VERSION: Final[tuple[int, int]] = (3, 5)
"""Oldest tmux whose character widths can be trusted as a reference.

Measured, and the reason is worth stating precisely: fed the identical byte stream, tmux 3.4
and Chrome place `\N{WARNING SIGN}\ufe0f` in different columns, while tmux 3.7c and Chrome
agree exactly. A variation selector requests emoji presentation, and emulators only honour it
consistently once their Unicode width data is recent enough.

So an older tmux is not a *worse* reference, it is a reference for a different question - "how
does this tmux measure emoji" rather than "what would a user see". Using one anyway produces a
diff that reads as a browser bug and is not one. The leg reports itself unavailable instead.
"""

POLL_INTERVAL: Final[float] = 0.1
"""Gap between screen captures while waiting for the app to draw."""

SETTLE_INTERVAL: Final[float] = 0.25
"""Gap between the two captures that have to match for the screen to count as settled."""

SETTLE_TIMEOUT: Final[float] = 15.0
"""How long to keep waiting for two identical captures before using the last one anyway."""

DEFAULT_TIMEOUT: Final[float] = 30.0
"""Generous: a cold Textual start on a loaded machine is seconds."""


class TmuxUnavailableError(RuntimeError):
    """Raised when a capture is attempted without tmux installed."""


class CaptureTimeoutError(RuntimeError):
    """Raised when the expected text never appeared on the pane."""


def _tmux(*args: str) -> str:
    """Run a tmux command with the user's configuration deliberately excluded."""
    if TMUX is None:
        raise TmuxUnavailableError("tmux is not installed; cannot capture a real terminal")
    completed = subprocess.run(  # noqa: S603 - fixed binary, no shell, arguments are ours
        [TMUX, "-f", "/dev/null", "-u", *args],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return completed.stdout


def _pane_shows(pane: str, marker: str | None) -> bool:
    """Whether a capture is the one being waited for."""
    return marker in pane if marker is not None else bool(pane.strip())


def _wait_for(session: str, marker: str | None, timeout: float) -> str:
    """Poll the pane until `marker` appears, returning the capture that contained it.

    A marker of None waits for any non-blank pane instead. Weaker, and the honest fallback
    for an app whose output is unknown: without it a target with no markers could not be
    captured at all, and with it the capture is at least not of an empty screen.

    Raises:
        CaptureTimeoutError: If it never appeared, with the last screen attached - without
            it the failure says only that something did not happen.
    """
    deadline = time.monotonic() + timeout
    pane = ""
    while time.monotonic() < deadline:
        pane = _tmux("capture-pane", "-p", "-t", session)
        if _pane_shows(pane, marker):
            return pane
        # textual-wasm: allow time.sleep - native-only reference capture, no event loop
        time.sleep(POLL_INTERVAL)
    wanted = repr(marker) if marker is not None else "any non-blank screen"
    raise CaptureTimeoutError(f"{wanted} never appeared within {timeout}s; last screen:\n{pane}")


def _wait_until_stable(session: str, timeout: float) -> str:
    """Poll until two captures a moment apart are identical, and return the later one.

    A marker says the app *reached* a state, not that it has finished drawing it. Textual
    composes in frames, and the frame carrying the marker is not always the last one - so a
    capture taken the instant a marker appears can be missing whatever the next frame draws.
    Measured in the browser leg, where a slower engine had not yet painted the footer at the
    moment a faster one had, and the row diff reported it as a rendering divergence.

    Degrades rather than fails: an app that never settles - a clock, an animation - uses the
    last reading, which is the screen the comparison would have taken regardless.
    """
    deadline = time.monotonic() + timeout
    previous = ""
    while time.monotonic() < deadline:
        current = _tmux("capture-pane", "-p", "-t", session)
        if current == previous:
            return current
        previous = current
        # textual-wasm: allow time.sleep - native-only reference capture, no event loop
        time.sleep(SETTLE_INTERVAL)
    return previous


@dataclasses.dataclass(frozen=True, slots=True)
class CaptureRequest:
    """Everything one capture needs to be reproducible."""

    command: tuple[str, ...]
    """Argv of the program to run in the pane."""

    columns: int = 80
    rows: int = 24

    ready_marker: str | None = None
    """Text that means the app has finished its first render, or None for any output."""

    keys: str = ""
    """Literal keystrokes to send once ready."""

    settled_marker: str | None = None
    """Text that means those keystrokes have been handled.

    Without it there is no way to tell a screen that has processed the input from one that
    has not, and the capture races the app.
    """

    timeout: float = DEFAULT_TIMEOUT


def capture(request: CaptureRequest) -> RenderedScreen:
    """Run a command in a real terminal and return the grid it drew.

    Returns:
        The final grid, normalised the same way every other runtime's is.

    Raises:
        TmuxUnavailableError: If tmux is not installed.
    """
    session = f"textual-wasm-{uuid.uuid4().hex[:8]}"
    _tmux(
        "new-session",
        "-d",
        "-s",
        session,
        "-x",
        str(request.columns),
        "-y",
        str(request.rows),
        *request.command,
    )
    try:
        # The status bar occupies a row, and that row is part of what is being compared.
        _tmux("set-option", "-t", session, "status", "off")
        _wait_for(session, request.ready_marker, request.timeout)
        if request.keys:
            _tmux("send-keys", "-t", session, "-l", request.keys)
        _wait_for(session, request.settled_marker or request.ready_marker, request.timeout)
        pane = _wait_until_stable(session, SETTLE_TIMEOUT)
    finally:
        subprocess.run(  # noqa: S603 - same fixed binary; teardown must not mask the error
            [TMUX or "true", "-f", "/dev/null", "kill-session", "-t", session],
            capture_output=True,
            check=False,
        )
    return RenderedScreen(
        columns=request.columns,
        rows=request.rows,
        lines=normalise(tuple(pane.splitlines())),
    )


REFERENCE_MODULE: Final[str] = "textual_wasm.reference"
"""The runner, invoked with `-m` so it works from an installed package as well as a checkout."""


def capture_target(target: AppTarget, *, columns: int, rows: int) -> RenderedScreen:
    """Capture any target's render from a real terminal.

    Shared by the CLI, the check orchestrator and the tests, so there is one definition of
    what the reference run is - and so the markers that decide when to capture are the same
    ones the browser harness waits for.

    Args:
        target: The application, and the text that says it is ready and settled.
        columns: Pane width.
        rows: Pane height.

    Returns:
        The grid the terminal drew.
    """
    return capture(
        CaptureRequest(
            command=(sys.executable, "-m", REFERENCE_MODULE, target.entry),
            columns=columns,
            rows=rows,
            ready_marker=target.ready_marker,
            keys=target.keys,
            settled_marker=target.settled_marker,
        )
    )


def version() -> str:
    """Report the tmux build, so a capture records which emulator produced it."""
    return _tmux("-V").strip()


def _parse_version(reported: str) -> tuple[int, int] | None:
    """Pull `(major, minor)` out of `tmux 3.5a`, or None if it is not shaped like that.

    tmux appends a letter to patch releases and `-rc` to candidates, so the minor component is
    read up to the first non-digit rather than parsed as an integer.
    """
    match = re.search(r"(\d+)\.(\d+)", reported)
    return (int(match.group(1)), int(match.group(2))) if match else None


def usable() -> tuple[bool, str]:
    """Whether a capture from this machine can serve as the render reference.

    Returns:
        Whether to use it, and a sentence saying why - which is what the check prints when a
        leg does not run, so it names the fix rather than the symptom.
    """
    if TMUX is None:
        return False, (
            "tmux is not installed; it is the only emulator that will hand its screen back "
            "as text, and without it there is no render reference"
        )
    reported = version()
    parsed = _parse_version(reported)
    if parsed is None:
        return False, f"could not read a version from {reported!r}"
    if parsed < MINIMUM_VERSION:
        wanted = ".".join(str(part) for part in MINIMUM_VERSION)
        return False, (
            f"{reported} is older than {wanted}, whose Unicode width data is where terminals "
            f"start agreeing with browsers about emoji presentation; a capture from it would "
            f"report a disagreement about tmux as though it were one about the browser"
        )
    return True, reported
