"""The minimal Textual application the probe drives.

Deliberately tiny, and deliberately ordinary: it uses nothing a WASM host has to special-case,
so that any failure the probe reports is a failure of the *runtime*, not of the app.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Resize
from textual.geometry import Size
from textual.widgets import Label, Static

MARKER: Final[str] = "TEXTUAL-WASM-SPIKE"
"""Text the probe looks for in the captured stream to prove the compositor ran."""

HINT_ID: Final[str] = "hint"
"""Widget whose text reports the key-press count, so input is visible and not just asserted."""

WIDTH_SAMPLES: Final[tuple[tuple[str, str], ...]] = (
    ("ascii", "abcdef"),
    ("box", "\u2500\u2502\u250c\u2510\u2514\u2518\u251c\u2524"),
    ("arrows", "\u2190\u2191\u2192\u2193"),
    ("braille", "\u2801\u2802\u2803\u2804\u2805"),
    ("cjk", "\u4e16\u754c\u65e5\u672c\u8a9e"),
    ("combining", "e\u0301a\u0300"),
    ("astral", "\U0001f680\U0001f4bb"),
    ("vs16", "\u2705\u26a0\ufe0f"),
    ("zwj", "\U0001f469\u200d\U0001f4bb"),
)
"""Character classes whose cell width three different tables have to agree on.

Textual lays out with rich's `cell_len`, `pyte` replays with `wcwidth`, and `xterm.js` uses
its own - none of them shared code. Each sample is followed by a terminator in
:data:`WIDTH_TERMINATOR`, so a disagreement moves that character into a different column and
the screen diff names the row and the column rather than merely failing.

Ordered easiest-first: ASCII and box drawing are unanimous, CJK is where a naive table goes
wrong, and astral-plane characters are where a UTF-16 emulator can miscount.

Two classes are deliberately absent, and their absence is a finding rather than an
omission. `pyte` 0.8.2 **silently discards the remainder of the line** after a zero-width
joiner (U+200D) or a variation selector (U+FE0F): fed `"\N{WARNING SIGN}\ufe0f|"` it
renders `"\N{WARNING SIGN}"` and the terminator is gone. `xterm.js` preserves both. So on
emoji sequences the oracle is wrong and the browser is right, which means pyte cannot
adjudicate them at all - including them would only measure the measuring instrument.
Settling emoji needs a different reference, such as a real terminal captured through
`tmux capture-pane`.
"""

WIDTH_TERMINATOR: Final[str] = "|"
"""Marks where the preceding sample ended. A width disagreement shifts it."""

EXIT_CODE: Final[int] = 7
"""Arbitrary non-zero, non-default value, so `run_async` returning it cannot be a coincidence."""

TIMER_DELAY: Final[float] = 0.05
"""Short enough to keep the probe quick, long enough to be a real `call_later` round trip."""


class SpikeApp(App[int]):
    """A one-widget app with a keybinding and a timer — the three things a host must support."""

    CSS = """
    Screen { align: center middle; }
    #marker { color: $success; border: round $accent; padding: 1 2; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # `priority` so the binding fires from the app regardless of what holds focus; the
        # probe is testing the input path, not Textual's focus resolution.
        Binding("a", "bump", "Bump the counter", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.bump_count: int = 0
        """Incremented by the `a` binding, i.e. by bytes that went through `XTermParser`."""

        self.timer_fired: bool = False
        """Set by `set_timer`, i.e. by the host event loop's timer implementation."""

        self.observed_size: Size | None = None
        """The size carried by the `Resize` the driver synthesised."""

    def compose(self) -> ComposeResult:
        yield Label(MARKER, id="marker")
        yield Static(id=HINT_ID)
        for name, sample in WIDTH_SAMPLES:
            yield Static(f"{name:<10}{sample}{WIDTH_TERMINATOR}", classes="width-sample")

    def on_mount(self) -> None:
        self._refresh_hint()
        self.set_timer(TIMER_DELAY, self._mark_timer_fired)

    def on_resize(self, event: Resize) -> None:
        self.observed_size = event.size

    def action_bump(self) -> None:
        self.bump_count += 1
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        """Put the count on screen.

        The probe asserts the counter in memory, which a driver could satisfy without ever
        having rendered anything; showing it means the browser demo fails visibly too.
        """
        self.query_one(f"#{HINT_ID}", Static).update(f"press 'a' - pressed {self.bump_count}")

    def _mark_timer_fired(self) -> None:
        self.timer_fired = True
