"""A signal explorer built from four third-party Textual libraries, shipped to a browser.

The point of this example is that **none of these libraries knows it is in a browser**, and
neither does this file. There is no shim, no conditional import and no vendored fork: four
packages off PyPI, installed by `micropip` at boot, driving the same widgets they drive in a
terminal.

The four were not picked for variety. They are the most-downloaded add-ons in the ecosystem
that survived all four tiers of the survey in `docs/library-support.md` - installed, imported,
scanned, and then actually mounted and rendered inside Pyodide:

* `textual-autocomplete` (675k downloads/month) - completion on the waveform field.
* `textual-plotext` (207k) - the static chart.
* `textual-plot` (31k) - the same data in a pannable, zoomable widget, so the two plotting
  libraries in the ecosystem can be compared side by side.
* `textual-slider` (3k) - frequency and sample count.

What makes this build work is not in this file at all: it is the `-r` flags on the build
command, which is what puts these four in the manifest for `micropip` to install. A missing
`-r` produces a page that fetches an interpreter, boots it, and then fails on the first
import - so `textual-wasm doctor -r <dist>` is worth running before the build rather than
after the deploy.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, ClassVar, Final

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, Label
from textual_autocomplete import AutoComplete
from textual_plot import PlotWidget
from textual_plotext import PlotextPlot
from textual_slider import Slider

if TYPE_CHECKING:
    from collections.abc import Callable

SAMPLES: Final[int] = 240
"""Points per trace. Small enough that a redraw is imperceptible on the one thread Pyodide
has - there is no worker to offload the arithmetic to, and `@work(thread=True)` does not
exist here."""

WAVEFORMS: Final[dict[str, Callable[[float], float]]] = {
    "sine": math.sin,
    "cosine": math.cos,
    "sawtooth": lambda phase: 2.0 * (phase / math.tau % 1.0) - 1.0,
    "square": lambda phase: 1.0 if math.sin(phase) >= 0 else -1.0,
    "triangle": lambda phase: 2.0 * abs(2.0 * (phase / math.tau % 1.0) - 1.0) - 1.0,
    "damped sine": lambda phase: math.sin(phase) * math.exp(-phase / 20.0),
}
"""The completion candidates and the maths behind them, in one place so the dropdown cannot
offer a name that does not plot."""

DEFAULT_WAVEFORM: Final[str] = "damped sine"


def trace(name: str, frequency: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    r"""Sample one waveform.

    $y_i = f\left(\frac{2\pi \cdot \text{frequency} \cdot i}{\text{SAMPLES}}\right)$ for
    $i \in [0, \text{SAMPLES})$, where $f$ is the waveform named by `name`.

    Args:
        name: A key of `WAVEFORMS`. An unknown name falls back to the default rather than
            raising - it arrives from a free-text `Input`, so a half-typed word is ordinary
            rather than exceptional.
        frequency: Cycles across the full window.

    Returns:
        The x and y series, as tuples because neither is mutated after this.
    """
    function = WAVEFORMS.get(name, WAVEFORMS[DEFAULT_WAVEFORM])
    xs = tuple(index / SAMPLES for index in range(SAMPLES))
    ys = tuple(function(math.tau * frequency * x) for x in xs)
    return xs, ys


class Gallery(App[None]):
    """Four add-on libraries driving one dataset."""

    CSS_PATH = "app.tcss"
    TITLE = "Add-on gallery"
    SUB_TITLE = "four third-party libraries, one Pyodide"

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [("q", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="controls"):
            with Vertical(classes="control"):
                yield Label("Waveform (try typing 's')")
                yield Input(value=DEFAULT_WAVEFORM, id="waveform")
            with Vertical(classes="control"):
                yield Label("Frequency", id="frequency-label")
                yield Slider(min=1, max=12, value=3, id="frequency")
        # Mounted as a sibling of the Input rather than inside it: the dropdown is an overlay
        # positioned against its target, which it finds by the selector.
        yield AutoComplete(target="#waveform", candidates=sorted(WAVEFORMS))
        with Horizontal(id="plots"):
            yield PlotextPlot(id="static")
            yield PlotWidget(id="interactive")
        yield Footer()

    def on_mount(self) -> None:
        self._redraw()

    @property
    def _frequency(self) -> int:
        return self.query_one("#frequency", Slider).value

    def _redraw(self) -> None:
        """Repaint both plots from the current controls.

        One method for both libraries on purpose: the data is computed once and handed to
        each, which is the comparison the example is for. `textual-plotext` exposes a
        `plt` object with the Plotext API; `textual-plot` has its own `plot`/`clear`.
        """
        name = self.query_one("#waveform", Input).value.strip()
        frequency = self._frequency
        xs, ys = trace(name, frequency)
        self.query_one("#frequency-label", Label).update(f"Frequency: {frequency}")

        static = self.query_one("#static", PlotextPlot)
        static.plt.clear_figure()
        static.plt.title(f"{name or DEFAULT_WAVEFORM} - plotext")
        static.plt.plot(list(xs), list(ys))
        static.refresh()

        interactive = self.query_one("#interactive", PlotWidget)
        interactive.clear()
        interactive.plot(list(xs), list(ys))

    @on(Input.Changed, "#waveform")
    @on(Slider.Changed, "#frequency")
    def controls_changed(self) -> None:
        self._redraw()


def main() -> None:
    Gallery().run()


if __name__ == "__main__":
    main()
