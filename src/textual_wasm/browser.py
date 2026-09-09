"""A `WasmDriverBase` whose terminal emulator is a real `xterm.js` instance.

This is the concrete driver the feasibility study describes, and the thing that would grow
into a shippable `textual-wasm`. It exists here to test the one claim the Node probe cannot:
that the byte stream Textual produces is rendered correctly by a browser terminal emulator,
including cell widths.

The host contract is four members on a JavaScript object, and nothing else:

    { write(text), onData(callback), onResize(callback), cols, rows }

`_emit` is the only method the base class requires; the rest of this module is the capability
overrides that would otherwise shell out to a process that does not exist in a browser tab.
"""

from __future__ import annotations

import base64
import importlib
import logging
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from pyodide.ffi import create_proxy

from textual_wasm.driver import DEFAULT_SIZE, WasmDriverBase

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import App

_log: Final = logging.getLogger(__name__)

HOST_MODULE: Final[str] = "textual_wasm_host"
"""Name the page registers its terminal object under via `pyodide.registerJsModule`."""


class TerminalHost(Protocol):
    """The complete contract a page must satisfy to host a Textual app.

    Written as a Protocol rather than prose so that adding a fifth requirement is a type
    error rather than a documentation update nobody reads. `xterm.js` satisfies all of it
    directly; the page only has to forward `onResize` as two integers.
    """

    cols: int
    rows: int

    def write(self, data: str) -> None: ...

    # camelCase because these are JavaScript members, not Python ones.
    def onData(self, callback: Callable[[str], None]) -> None: ...  # noqa: N802

    def onResize(self, callback: Callable[[int, int], None]) -> None: ...  # noqa: N802


def _host() -> TerminalHost:
    """Return the page's terminal object.

    Raises:
        RuntimeError: If the page did not register one, which is the single most likely
            bootstrap mistake and is otherwise reported as a confusing import error.
    """
    try:
        return cast("TerminalHost", importlib.import_module(HOST_MODULE))
    except ImportError as error:
        raise RuntimeError(
            f"the page must register a terminal object as {HOST_MODULE!r} via "
            "pyodide.registerJsModule() before importing this driver"
        ) from error


class BrowserDriver(WasmDriverBase):
    """Drives a Textual app against `xterm.js` in the page that loaded Pyodide."""

    def __init__(
        self,
        app: App[Any],
        *,
        debug: bool = False,
        mouse: bool = True,
        size: tuple[int, int] | None = None,
    ) -> None:
        self._terminal = _host()
        super().__init__(app, debug=debug, mouse=mouse, size=size or self._terminal_size())

        # Every Python callable handed to JavaScript must be an explicitly created proxy.
        # The automatic one is *borrowed*: it is destroyed when the call it was passed into
        # returns, so a listener registered with a bare method appears to work and then
        # throws "This borrowed proxy was automatically destroyed" on the first keystroke -
        # into the browser console, where a Textual app will never see it. Keeping the
        # handles is what lets them be released in `close`.
        self._on_data = create_proxy(self.feed_input)
        self._on_resize = create_proxy(self.on_resize)
        self._terminal.onData(self._on_data)
        self._terminal.onResize(self._on_resize)

    def _terminal_size(self) -> tuple[int, int]:
        """Ask the emulator for its grid, falling back if it has not laid out yet."""
        try:
            return int(self._terminal.cols), int(self._terminal.rows)
        except (AttributeError, TypeError, ValueError):
            _log.warning("terminal reported no size; falling back to %s", DEFAULT_SIZE)
            return DEFAULT_SIZE

    def _emit(self, data: str) -> None:
        self._terminal.write(data)

    def close(self) -> None:
        """Release the callback proxies; they are not garbage collected on either side."""
        self._on_data.destroy()
        self._on_resize.destroy()

    def open_url(self, url: str, new_tab: bool = True) -> None:
        """Open in the page rather than via `webbrowser`, which would try to spawn a process."""
        from js import window  # noqa: PLC0415 - only importable inside a browser runtime

        window.open(url, "_blank" if new_tab else "_self")

    def deliver_file(self, payload: bytes, *, filename: str, mime_type: str) -> None:
        """Hand the viewer a file as a data URL.

        Textual's `Driver.deliver_binary` writes to a filesystem path in a background thread;
        neither the path nor the thread exists here. A page-driven download is the browser's
        equivalent, and keeping it a separate method means the base signature is untouched.
        """
        from js import document  # noqa: PLC0415 - only importable inside a browser runtime

        anchor = document.createElement("a")
        anchor.href = f"data:{mime_type};base64,{base64.b64encode(payload).decode('ascii')}"
        anchor.download = filename
        anchor.click()
