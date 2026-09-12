# addon-gallery

A signal explorer built from **four third-party Textual libraries**, running in a browser.

```
gallery_app/
  app.py      the whole application - ordinary Textual, no WASM awareness
  app.tcss    layout only; each add-on brings its own styling
```

| Library | Downloads/month | Job in this app |
|---|---|---|
| [`textual-autocomplete`](https://pypi.org/project/textual-autocomplete/) | 675k | completion on the waveform field |
| [`textual-plotext`](https://pypi.org/project/textual-plotext/) | 207k | the static chart |
| [`textual-plot`](https://pypi.org/project/textual-plot/) | 31k | the same data, pannable and zoomable |
| [`textual-slider`](https://pypi.org/project/textual-slider/) | 3k | frequency |

Two plotting libraries on purpose: they are the two options in the ecosystem, and this puts
them side by side on identical data.

## The point

**None of these libraries knows it is in a browser, and neither does `app.py`.** No shim, no
conditional import, no vendored fork — four packages off PyPI, installed by `micropip` at
boot, driving the same widgets they drive in a terminal.

What makes the build work is not in the application at all. It is the `-r` flags:

```bash
textual-wasm build gallery_app.app:Gallery gallery_app -o dist/ --worker \
  -r textual-autocomplete -r textual-plotext -r textual-plot -r textual-slider
```

A missing `-r` produces a page that fetches a 10 MB interpreter, boots it, and *then* fails
on the first import. So check first:

```bash
textual-wasm doctor gallery_app.app:Gallery \
  -r textual-autocomplete -r textual-plotext -r textual-plot -r textual-slider
```

## Run it

```bash
poetry install
poetry run addon-gallery       # a terminal
```

```bash
textual-wasm dev dist/         # a browser, after the build above
```

Type `s` in the waveform field to see the dropdown; drag or arrow the slider to change
frequency. Both charts repaint from one dataset.

## Picking add-ons that will actually work

These four were not chosen for variety — they are the most-downloaded libraries that survived
all four tiers of the [library support survey](https://kaierikniermann.github.io/textual-wasm/library-support.html):
installed under `micropip`, imported, scanned, and then **mounted and rendered inside a real
Pyodide**. That last tier is the one that matters, and it is the one a README cannot tell you
about.

Three traps the survey found, worth knowing before you add a fifth library:

**"It installed" is not "it works".** The most-downloaded add-on in the whole ecosystem,
`textual-serve`, installs cleanly under Pyodide and passes the static scan — and is the one
thing you definitely should not combine with this, because it *is* the server-side
alternative.

**`micropip.install(name)` can succeed by downgrading Textual underneath you.** Five
libraries cap Textual below the version this project pins; on its own each installs fine,
having quietly resolved Textual *down*. You find out later, as missing widgets.

**A clean `doctor` run on a dependency is not evidence.** Not one library in the ecosystem
tripped a single static-scan finding. That says more about what the scan covers than about
the libraries.

## Measured

Built with `--worker` and driven in Chromium and Firefox: all four libraries mounted, the
plotext chart rendered with real axes and data, arrow keys on the slider moved the frequency
and repainted both plots, and **neither engine logged a console error**.
