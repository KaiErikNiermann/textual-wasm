"""Put diagnostics where a terminal-app developer is actually looking.

Textual builds `error_console = Console(..., stderr=True)` (`textual/app.py:636`) and prints
every crash traceback and `panic()` renderable through it (`app.py:3298`). Under Pyodide
`stderr` is the browser console, so a Textual app that crashes in the browser writes its
traceback to a place the user cannot see and the developer has no reason to open. The app
just vanishes.

Redirecting that console through the driver puts the traceback in the terminal the user is
already looking at. The timing works out: Textual prints exit renderables after the driver
has left application mode, so the output lands on the normal screen buffer once the alt
screen is torn down - which is exactly what happens in a real terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from rich.console import Console

from textual_wasm.diagnostics.guards import recorded
from textual_wasm.diagnostics.translate import translate

if TYPE_CHECKING:
    from textual.app import App

    from textual_wasm.driver import WasmDriverBase

DEFAULT_WIDTH: Final[int] = 80
"""Used when the driver has no size yet, matching `shutil.get_terminal_size`'s fallback."""


class _DriverStream:
    """A minimal text sink that writes through a Textual driver.

    Deliberately not a full `TextIO`: Rich only needs `write` and `flush`, and implementing
    the rest would mean pretending to support seeking on a terminal.
    """

    def __init__(self, sink: WasmDriverBase) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        # Rich emits bare newlines; a terminal that has left application mode needs CRLF or
        # every line after the first starts wherever the previous one ended.
        self._sink.write(text.replace("\n", "\r\n"))
        return len(text)

    def flush(self) -> None:
        self._sink.flush()


def attach(app: App[object], driver: WasmDriverBase) -> None:
    """Route the app's error output through `driver` instead of stderr.

    Typed against this project's driver rather than Textual's base class because it only
    makes sense for one: a real terminal already puts stderr where the user can see it.

    Args:
        app: The running application.
        driver: The driver whose terminal should receive crash output.
    """
    app.error_console = Console(
        file=_DriverStream(driver),  # type: ignore[arg-type]  # see _DriverStream
        force_terminal=True,
        color_system="truecolor",
        width=driver.size.width or DEFAULT_WIDTH,
        markup=False,
        highlight=False,
    )


def describe_recorded() -> str:
    """Render the warnings the guards collected, for a host that wants to show them.

    `warnings.warn` writes to stderr, so under Pyodide every guard warning goes to the same
    invisible console the tracebacks do. This is the readable copy.
    """
    warnings_ = recorded()
    if not warnings_:
        return ""
    lines = [f"{len(warnings_)} compatibility warning(s):"]
    lines += [f"  - {warning.substitution.id}: {warning.detail}" for warning in warnings_]
    return "\n".join(lines)


__all__ = ["attach", "describe_recorded", "translate"]
