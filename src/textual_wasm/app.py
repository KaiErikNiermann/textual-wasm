"""The minimal Textual application the probe drives by default.

Deliberately tiny, and deliberately ordinary: it uses nothing a WASM host has to special-case,
so that any failure the probe reports is a failure of the *runtime*, not of the app.

It carries no probe instrumentation, and that is the point. The probe schedules its own
timer, reads the resize off the `Screen`, and judges input by what appears on the grid - so
this app is measured by exactly the code that measures anyone else's, and a check that only
passes because the app cooperated cannot exist.
"""

from __future__ import annotations

from typing import ClassVar, Final

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Label, Static

MARKER: Final[str] = "TEXTUAL-WASM-SPIKE"
"""Text that means this app has drawn - `AppTarget.ready_marker` for the default target."""

HINT_ID: Final[str] = "hint"
"""Widget whose text reports the key-press count, so input is visible and not just asserted."""

HINT_TEMPLATE: Final[str] = "press 'a' - pressed {count}"
"""What that widget says. Module level because `AppTarget.settled_marker` is a substring of
it, and a test pins the two together - a settled marker that no longer matches what the app
draws does not fail loudly, it makes every harness wait out its timeout."""

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


class SpikeApp(App[int]):
    """A one-widget app with a keybinding, drawn at a range of awkward character widths."""

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

    def compose(self) -> ComposeResult:
        yield Label(MARKER, id="marker")
        yield Static(id=HINT_ID)
        for name, sample in WIDTH_SAMPLES:
            yield Static(f"{name:<10}{sample}{WIDTH_TERMINATOR}", classes="width-sample")

    def on_mount(self) -> None:
        self._refresh_hint()

    def action_bump(self) -> None:
        self.bump_count += 1
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        """Put the count on screen.

        On screen rather than only in an attribute: every harness judges input by what it can
        read back off the grid, so a counter that is not drawn is a counter no leg can see.
        """
        self.query_one(f"#{HINT_ID}", Static).update(HINT_TEMPLATE.format(count=self.bump_count))
