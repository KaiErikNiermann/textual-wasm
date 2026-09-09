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
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Final

from textual_wasm.app import MARKER
from textual_wasm.screen import RenderedScreen, normalise

TMUX: Final[str | None] = shutil.which("tmux")
"""The tmux binary, or None. Callers skip rather than fail: a machine without tmux can still
run every other part of the experiment."""

POLL_INTERVAL: Final[float] = 0.1
"""Gap between screen captures while waiting for the app to draw."""

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


def _wait_for(session: str, marker: str, timeout: float) -> str:
    """Poll the pane until `marker` appears, returning the capture that contained it.

    Raises:
        CaptureTimeoutError: If the marker never appeared, with the last screen attached -
            without it the failure says only that something did not happen.
    """
    deadline = time.monotonic() + timeout
    pane = ""
    while time.monotonic() < deadline:
        pane = _tmux("capture-pane", "-p", "-t", session)
        if marker in pane:
            return pane
        time.sleep(POLL_INTERVAL)
    raise CaptureTimeoutError(f"{marker!r} never appeared within {timeout}s; last screen:\n{pane}")


@dataclasses.dataclass(frozen=True, slots=True)
class CaptureRequest:
    """Everything one capture needs to be reproducible."""

    command: tuple[str, ...]
    """Argv of the program to run in the pane."""

    columns: int
    rows: int

    ready_marker: str
    """Text that means the app has finished its first render."""

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
        pane = _wait_for(session, request.settled_marker or request.ready_marker, request.timeout)
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


SPIKE_ENTRY: Final[Path] = Path(__file__).resolve().parents[2] / "scripts" / "terminal_entry.py"
"""The reference runner. Outside the package because it must set `TEXTUAL_DRIVER` back to
Textual's own platform driver before anything imports `textual`, and importing this package
is what sets it to ours."""

SETTLED_MARKER: Final[str] = "pressed 1"
"""Proof the app handled the keystroke, not merely that it started."""


def capture_spike(*, columns: int, rows: int) -> RenderedScreen:
    """Capture the spike app's render from a real terminal.

    Shared by the CLI and the tests so there is one definition of what the reference run is.
    """
    return capture(
        CaptureRequest(
            command=(sys.executable, str(SPIKE_ENTRY)),
            columns=columns,
            rows=rows,
            ready_marker=MARKER,
            keys="a",
            settled_marker=SETTLED_MARKER,
        )
    )


def version() -> str:
    """Report the tmux build, so a capture records which emulator produced it."""
    return _tmux("-V").strip()
