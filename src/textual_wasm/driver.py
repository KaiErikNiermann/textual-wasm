"""An out-of-tree Textual `Driver` for single-threaded, non-tty hosts.

The point of this module is that it is selected purely through Textual's public
`TEXTUAL_DRIVER=module:Symbol` environment hook (`textual.app.App.get_driver_class`), so no
patch to Textual is required to run an app on a host that has no terminal.

`WasmDriverBase` holds everything that is genuinely platform-independent — application-mode
escape sequences, the `XTermParser` pump, resize dispatch, and the browser-shaped capability
overrides. A concrete driver supplies only a sink:

* `CaptureDriver` (here) appends to a list, which is what the probe and the tests assert on.
* A browser driver would implement `_emit` as `xterm_js_terminal.write(...)` and bind
  `feed_input` to its `onData` callback. There is no third thing it would need.

Threading note: the native drivers wrap `XTermParser` in a reader thread only because
`os.read` blocks. Here input arrives as a callback on the one and only thread, so the parser
is driven synchronously and no thread exists to synchronise with.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Final

from textual import events
from textual._xterm_parser import XTermParser
from textual.driver import Driver
from textual.geometry import Size

if TYPE_CHECKING:
    from textual.app import App

_log: Final = logging.getLogger(__name__)

DEFAULT_SIZE: Final[tuple[int, int]] = (80, 24)
"""Fallback grid used when the host does not report one."""

_TICK_INTERVAL: Final[float] = 0.05
"""How often to poll `XTermParser.tick()` for the escape-sequence timeout.

Half of Textual's 100 ms `ESCDELAY` default, which is what distinguishes a bare `Escape`
keypress from the start of a CSI sequence. The native drivers get this from a `select`
timeout; without a blocking read there has to be a timer instead.
"""

ENTER_APPLICATION_MODE: Final[tuple[str, ...]] = (
    # Public because they are the protocol a host terminal emulator has to support, not an
    # implementation detail: anyone writing a second sink needs to know exactly this set.
    "\x1b[?1049h",  # alternate screen buffer
    "\x1b[?1000h",  # SET_VT200_MOUSE
    "\x1b[?1003h",  # SET_ANY_EVENT_MOUSE
    "\x1b[?1015h",  # SET_VT200_HIGHLIGHT_MOUSE
    "\x1b[?1006h",  # SET_SGR_EXT_MODE_MOUSE
    "\x1b[?25l",  # hide cursor
    "\x1b[?2004h",  # bracketed paste
)

EXIT_APPLICATION_MODE: Final[tuple[str, ...]] = (
    "\x1b[?2004l",
    "\x1b[?1006l",
    "\x1b[?1015l",
    "\x1b[?1003l",
    "\x1b[?1000l",
    "\x1b[?25h",
    "\x1b[?1049l",
)


class WasmDriverBase(Driver):
    """Driver core for a host that provides a terminal emulator rather than a tty."""

    def __init__(
        self,
        app: App[Any],
        *,
        debug: bool = False,
        mouse: bool = True,
        size: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(app, debug=debug, mouse=mouse, size=size)
        # `debug=True` makes XTermParser open a `keys.log` in the working directory, which is
        # a pointless write under an in-memory filesystem.
        self._parser = XTermParser(debug=False)
        self._tick_task: asyncio.Task[None] | None = None
        self._input_enabled = False

    @property
    def is_web(self) -> bool:
        """Report as a web driver so app code can branch the same way it does under
        textual-serve."""
        return True

    @property
    def can_suspend(self) -> bool:
        """No `SIGTSTP` here; this gates `App.suspend` off before it reaches `os.kill`."""
        return False

    @abstractmethod
    def _emit(self, data: str) -> None:
        """Hand encoded terminal output to the host's terminal emulator."""

    def write(self, data: str) -> None:
        self._emit(data)

    def flush(self) -> None:
        """No-op: a terminal emulator owns its own buffering."""

    @property
    def size(self) -> Size:
        """The grid Textual should lay out against."""
        return Size(*(self._size or DEFAULT_SIZE))

    def feed_input(self, data: str) -> None:
        """Feed decoded terminal input to the app.

        This is the host callback seam: bind it to `xterm.js`'s `onData`. It is a plain
        synchronous call because the browser delivers input on the same thread that runs the
        event loop.
        """
        if not self._input_enabled:
            return
        for message in self._parser.feed(data):
            self.process_message(message)

    def on_resize(self, width: int, height: int) -> None:
        """Report a new grid size, e.g. from an `xterm.js` `onResize` or a window resize."""
        self._size = (width, height)
        size = Size(width, height)
        self.process_message(events.Resize(size, size))

    def start_application_mode(self) -> None:
        for sequence in ENTER_APPLICATION_MODE:
            self.write(sequence)
        self._input_enabled = True
        self._tick_task = asyncio.get_running_loop().create_task(self._pump_parser_timeouts())
        width, height = self._size or DEFAULT_SIZE
        self.on_resize(width, height)
        # The page owns keyboard focus for as long as the app is mounted; the terminal
        # drivers infer this from the tty, and there is nothing to infer from here.
        self._app.call_later(self._app.post_message, events.AppFocus())

    def disable_input(self) -> None:
        self._input_enabled = False
        if self._tick_task is not None:
            self._tick_task.cancel()
            self._tick_task = None

    def stop_application_mode(self) -> None:
        self.disable_input()
        for sequence in EXIT_APPLICATION_MODE:
            self.write(sequence)

    def open_url(self, url: str, new_tab: bool = True) -> None:
        """Log rather than shell out.

        The base implementation calls `webbrowser.open`, which under a browser runtime would
        try to spawn a process. A real browser driver overrides this with `window.open`.
        """
        _log.info("open_url requested url=%s new_tab=%s", url, new_tab)

    async def _pump_parser_timeouts(self) -> None:
        """Drive `XTermParser.tick()` so a lone `Escape` resolves without a following byte."""
        try:
            while True:
                await asyncio.sleep(_TICK_INTERVAL)
                for message in self._parser.tick():
                    self.process_message(message)
        except asyncio.CancelledError:
            pass


class CaptureDriver(WasmDriverBase):
    """A `WasmDriverBase` whose terminal emulator is a list of strings.

    Standing in for `xterm.js` this way is what lets one probe run unchanged on CPython and
    on Pyodide: the assertions are about the byte stream Textual produces, and that stream is
    identical whether it is appended to a list or handed to a canvas.
    """

    def __init__(
        self,
        app: App[Any],
        *,
        debug: bool = False,
        mouse: bool = True,
        size: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(app, debug=debug, mouse=mouse, size=size)
        self._frames: list[str] = []
        self._app_mode_started = False
        _register_active(self)

    def _emit(self, data: str) -> None:
        self._frames.append(data)

    def start_application_mode(self) -> None:
        super().start_application_mode()
        self._app_mode_started = True

    @property
    def output(self) -> str:
        """Everything written since the driver was constructed."""
        return "".join(self._frames)

    @property
    def rendered_output(self) -> str:
        """Output excluding this driver's own application-mode preamble.

        Assertions about "did the compositor actually render" must not be satisfiable by the
        escape sequences the driver itself wrote, or the check proves nothing.
        """
        preamble = len(ENTER_APPLICATION_MODE) if self._app_mode_started else 0
        return "".join(self._frames[preamble:])


_active: CaptureDriver | None = None
"""The most recently constructed `CaptureDriver`.

Textual constructs the driver itself, from a class name in an environment variable, so a
caller has no other handle on the instance. A real browser driver needs exactly the same
seam in order to expose `feed_input`/`on_resize` to JavaScript. Single-app by construction:
the probe runs one `App` at a time.
"""


def _register_active(driver: CaptureDriver) -> None:
    global _active  # noqa: PLW0603 - see `_active`; the alternative is reaching into App._driver
    _active = driver


def active_driver() -> CaptureDriver:
    """Return the live `CaptureDriver`.

    Raises:
        RuntimeError: If no driver has been constructed yet, which means Textual never
            reached application mode.
    """
    if _active is None:
        raise RuntimeError("no CaptureDriver has been constructed; did the app start?")
    return _active
