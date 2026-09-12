"""Which Textual add-on libraries work in a browser, measured rather than assumed.

A registry, for the same reason `substitutions.py` is one: a compatibility table written by
hand is wrong within a release and nothing fails when it drifts. `docs/library-support.md` is
rendered from here, a test asserts the committed file matches, and every verdict below came
from a probe rather than from reading a README.

**What was measured.** Each distribution was installed with `micropip` into a real Pyodide
314.0.6, imported, scanned with this project's own `doctor`, and then - the part that
actually decides a port - every `Widget` subclass it defines was constructed and mounted in a
running Textual application under the capture driver. The four tiers disagree often enough
that any one of them alone would mislead:

* `textual-serve` passes install and import, and is nonetheless the wrong answer: it is the
  server-side architecture this project is an alternative to.
* Five libraries install cleanly *by silently pulling an older Textual*, which the install
  tier cannot see and the mount tier reports immediately.
* On the first run of this survey the static scan produced **no findings at all**, across
  every library. That was a gap in the rules rather than a clean bill of health, and the two
  failures the runtime tier had already found showed where: `textual-image` interrogating the
  terminal, and `textual-serve` binding a socket. Both now have registry entries, both fire
  on those exact lines, and neither fires on a library that is fine.

**What was not measured.** WebKit would not launch on the machine that ran this, so every
verdict is Chromium and Firefox. Widgets needing constructor arguments were given real ones
for seven libraries and left unexercised elsewhere - recorded as `IMPORTS`, not as working.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Final

MEASURED_AT: Final[str] = "2026-09-12"
"""When the probes ran. Download counts and versions are as of this date and nothing here
re-checks them, so the date is part of the claim."""

MEASURED_AGAINST_TEXTUAL: Final[str] = "8.2.8"
"""The Textual this project pins. `TEXTUAL_CAP` verdicts are relative to it, not absolute."""


class Support(enum.StrEnum):
    """How far a library got, in the order the tiers were applied."""

    VERIFIED = "verified"
    """Installed, imported, and at least one of its widgets mounted and rendered.

    The only verdict that means "this works in a browser". Everything else is weaker, and
    the point of having six values rather than a boolean is that the weaker cases fail for
    unrelated reasons with unrelated fixes.
    """

    IMPORTS = "imports"
    """Installs and imports, but nothing could be exercised automatically.

    Either it defines no Textual widget (a Rich renderable, a stylesheet) or every widget it
    defines needs constructor arguments a generic probe cannot invent. Not a defect, and not
    evidence of working either.
    """

    TEXTUAL_CAP = "textual_cap"
    """Installs only by resolving Textual *down* to a version it allows.

    The most misleading outcome in the ecosystem, because `micropip.install(name)` succeeds:
    it quietly satisfies the cap by fetching an older Textual, and the failure surfaces later
    as missing widgets or changed APIs. Asked to coexist with Textual 8.2.8 it refuses
    outright. Nothing about WASM - the same cap binds a terminal install.
    """

    BLOCKED = "blocked"
    """Cannot be installed under Pyodide at all, for a reason named in `observed`."""

    NOT_ON_PYPI = "not_on_pypi"
    """No distribution to install. `micropip` has no path to a git repository."""

    OUT_OF_SCOPE = "out_of_scope"
    """Works, and is still not something you ship into a page - a development tool, or the
    server-side architecture this project is the alternative to."""


@dataclasses.dataclass(frozen=True, slots=True)
class Library:
    """One distribution, and what the probes saw."""

    distribution: str
    support: Support
    summary: str
    """What the library is for, in one clause."""

    observed: str
    """What the probe actually saw. The evidence, not the conclusion."""

    version: str = ""
    """The version measured, or empty where nothing installed."""

    downloads: int = 0
    """PyPI downloads in the month before `MEASURED_AT`, for ordering by real use."""

    widgets: tuple[str, ...] = ()
    """Widgets that mounted and rendered. Named because "it works" is a weaker claim than
    "these mounted", and the second one is what was tested."""

    guidance: str = ""
    """What to do about it, where there is anything to do."""

    @property
    def usable(self) -> bool:
        """Whether an application can ship this to a browser today."""
        return self.support in {Support.VERIFIED, Support.IMPORTS}


LIBRARIES: Final[tuple[Library, ...]] = (
    # --- VERIFIED: mounted and rendered inside Pyodide -----------------------------------
    Library(
        distribution="textual-autocomplete",
        support=Support.VERIFIED,
        version="4.0.6",
        downloads=675128,
        summary="dropdown autocompletion for Input",
        observed=(
            "`Input` plus `AutoComplete(target='#id', candidates=[...])` mounted and rendered "
            "7796 characters. Pure Python, depends only on textual and typing-extensions."
        ),
        widgets=("AutoComplete", "PathAutoComplete"),
        guidance=(
            "`PathAutoComplete` completes against a filesystem, which in a browser is MEMFS - "
            "it will complete over whatever the build shipped, not the user's disk."
        ),
    ),
    Library(
        distribution="textual-plotext",
        support=Support.VERIFIED,
        version="1.0.1",
        downloads=207180,
        summary="Plotext charts as a Textual widget",
        observed="All 6 widgets constructed, mounted and rendered. No native dependency.",
        widgets=("PlotextPlot",),
    ),
    Library(
        distribution="textual-image",
        support=Support.VERIFIED,
        version="0.13.2",
        downloads=254448,
        summary="images via Sixel and the Terminal Graphics Protocol",
        observed=(
            "`textual_image.widget.Image(pil_image)` - the backend-selecting widget - mounted "
            "and rendered 9115 characters. Pillow is bundled by Pyodide, so it resolves. The "
            "doctor now reports three findings in its source: `fcntl.ioctl` and two "
            "`termios.tcsetattr` calls in `_posix.py`, which is the terminal interrogation "
            "behind the hang below."
        ),
        widgets=("Image",),
        guidance=(
            "Only the auto-selecting widget was verified. A probe that imported every "
            "submodule of the package **hung** rather than failing, so one of the backend "
            "modules blocks on import under this driver - unsurprising for a library whose job "
            "is to ask the terminal what protocols it supports. Import "
            "`textual_image.widget.Image` and let it choose; do not import a specific backend."
        ),
    ),
    Library(
        distribution="textual-universal-directorytree",
        support=Support.VERIFIED,
        version="1.7.0",
        downloads=108980,
        summary="DirectoryTree over local and remote filesystems",
        observed=(
            "`UniversalDirectoryTree('/')` mounted and rendered 11143 characters over Pyodide's "
            "own in-memory filesystem."
        ),
        widgets=("UniversalDirectoryTree",),
        guidance=(
            "Local paths browse MEMFS, which holds only what the build shipped. Its remote "
            "backends (s3://, gs://, github://) are the interesting use and were not measured: "
            "each needs network access and is therefore subject to CORS."
        ),
    ),
    Library(
        distribution="textual-fastdatatable",
        support=Support.VERIFIED,
        version="0.19.2",
        downloads=57158,
        summary="a DataTable backed by Arrow, for large tables",
        observed="Installed and its widget mounted and rendered.",
        widgets=("DataTable",),
        guidance=(
            "It can use pyarrow, which Pyodide bundles at 22.0.0 and no other version. A pin "
            "excluding that is a `version_conflict` the doctor reports before you build."
        ),
    ),
    Library(
        distribution="textual-fspicker",
        support=Support.VERIFIED,
        version="1.0.1",
        downloads=50738,
        summary="file open/save and directory picker dialogs",
        observed=(
            "10 of 11 widgets mounted and rendered, including `FileOpen`, `FileSave` and "
            "`SelectDirectory`. The eleventh, `FileFilter`, needs arguments."
        ),
        widgets=("FileOpen", "FileSave", "SelectDirectory", "DirectoryNavigation"),
        guidance=(
            "It picks paths in Pyodide's filesystem, not the user's. For a real file from the "
            "user's machine you need the browser's own picker; for handing one back, "
            "`App.deliver_binary` and the page's `deliverFile` capability."
        ),
    ),
    Library(
        distribution="textual-hires-canvas",
        support=Support.VERIFIED,
        version="0.14.0",
        downloads=31124,
        summary="a high-resolution drawing canvas",
        observed="Installed and its widget mounted and rendered.",
        widgets=("Canvas",),
    ),
    Library(
        distribution="textual-plot",
        support=Support.VERIFIED,
        version="0.10.1",
        downloads=31046,
        summary="a native plotting widget with zoom and pan",
        observed="All 7 widgets constructed, mounted and rendered.",
        widgets=("PlotWidget",),
    ),
    Library(
        distribution="textual-imageview",
        support=Support.VERIFIED,
        version="0.1.1",
        downloads=14601,
        summary="an image viewer widget",
        observed=(
            "`ImageViewer(Image.new('RGB', (8, 8)))` mounted and rendered 10923 characters. "
            "Pillow is bundled by Pyodide, so the dependency resolves."
        ),
        widgets=("ImageViewer",),
        guidance="Renders with half-block characters, so it needs no terminal graphics protocol.",
    ),
    Library(
        distribution="textual-datepicker",
        support=Support.VERIFIED,
        version="0.2.4",
        downloads=10488,
        summary="a date picker",
        observed="6 of 9 widgets mounted and rendered; the other 3 need constructor arguments.",
        widgets=("DatePicker", "MonthControl"),
    ),
    Library(
        distribution="textual-timepiece",
        support=Support.VERIFIED,
        version="0.7.0",
        downloads=1166,
        summary="date, time, duration and timeline widgets",
        observed=(
            "42 of 50 widgets mounted and rendered. Its Textual requirement is "
            "`>=6.0.0,<9.0.0`, which includes the pinned 8.2.8 - the only library here with a "
            "cap that does."
        ),
        widgets=("DatePicker", "DurationInput", "TimeInput"),
    ),
    Library(
        distribution="textual-slider",
        support=Support.VERIFIED,
        version="0.2.0",
        downloads=3197,
        summary="a slider",
        observed="`Slider(min=0, max=10)` mounted and rendered 9172 characters.",
        widgets=("Slider",),
    ),
    Library(
        distribution="textual-colorpicker",
        support=Support.VERIFIED,
        version="0.1.0",
        downloads=2396,
        summary="a colour picker",
        observed="All 8 widgets mounted and rendered.",
        widgets=("ColorPicker",),
    ),
    Library(
        distribution="textual-canvas",
        support=Support.VERIFIED,
        version="1.1.0",
        downloads=421,
        summary="a character-cell drawing canvas",
        observed="`Canvas(16, 8)` mounted and rendered 5467 characters.",
        widgets=("Canvas",),
    ),
    Library(
        distribution="textual-tags",
        support=Support.VERIFIED,
        version="0.3.3",
        downloads=70,
        summary="a tag-entry widget",
        observed="`Tags(tag_values=[...])` mounted and rendered 6459 characters.",
        widgets=("Tags",),
    ),
    Library(
        distribution="textual-countdown",
        support=Support.VERIFIED,
        version="1.0.0",
        downloads=48,
        summary="a visual countdown timer",
        observed="Its widget mounted and rendered.",
        widgets=("Countdown",),
    ),
    Library(
        distribution="textual-astview",
        support=Support.VERIFIED,
        version="0.8.0",
        downloads=25,
        summary="a Python AST explorer",
        observed="`ASTView(module=path)` mounted and rendered 9613 characters over MEMFS.",
        widgets=("ASTView",),
    ),
    Library(
        distribution="zandev-textual-widgets",
        support=Support.VERIFIED,
        version="1.2.0",
        downloads=4600,
        summary="an assorted widget collection",
        observed=(
            "20 of 28 widgets mounted and rendered; 6 need constructor arguments and 2 are "
            "abstract bases that cannot be constructed anywhere."
        ),
    ),
    Library(
        distribution="textual-dad-joke",
        support=Support.VERIFIED,
        version="0.0.1",
        downloads=8,
        summary="a dad joke widget, seriously",
        observed="Its widget mounted and rendered.",
        widgets=("DadJoke",),
        guidance=(
            "It fetches from icanhazdadjoke.com, so in a browser it is subject to CORS - the "
            "mount succeeding says nothing about the request succeeding."
        ),
    ),
    # --- IMPORTS: installs, nothing a generic probe could exercise -----------------------
    Library(
        distribution="rich-pixels",
        support=Support.IMPORTS,
        version="3.0.1",
        downloads=93903,
        summary="images as Rich renderables",
        observed=(
            "Installs and imports. Defines no Textual widget - it is a Rich renderable, so it "
            "reaches a Textual app through `Static(Pixels.from_image(...))`."
        ),
        guidance="Wrap it in a `Static`; there is nothing browser-specific about it.",
    ),
    Library(
        distribution="textual-select",
        support=Support.IMPORTS,
        version="0.3.4",
        downloads=0,
        summary="a select/dropdown with a searchable list",
        observed=(
            "Installs and imports. All four of its widgets need constructor arguments "
            "(`items`, `list_mount`, `select_list`), so none was exercised."
        ),
    ),
    Library(
        distribution="textual-pdf",
        support=Support.IMPORTS,
        version="0.1.7",
        downloads=7,
        summary="a PDF preview widget, on top of textual-image",
        observed=(
            "Installs and imports; `PDFViewer` needs a `path` and was not exercised. It "
            "renders through textual-image, whose own verdict applies."
        ),
    ),
    Library(
        distribution="tuilwindcss",
        support=Support.IMPORTS,
        version="0.1.0",
        downloads=8,
        summary="Tailwind-like utility classes for Textual CSS",
        observed=(
            "Installs and imports. Ships stylesheets rather than widgets, so nothing to mount."
        ),
    ),
    # --- TEXTUAL_CAP: installs by downgrading Textual underneath you ---------------------
    Library(
        distribution="textual-slidecontainer",
        support=Support.TEXTUAL_CAP,
        version="1.0.0",
        downloads=1587,
        summary="a sliding or hidden menu-bar container",
        observed=(
            "Requires `textual>=3.0.0,<6.0.0`. `micropip.install` alone succeeds by fetching an "
            "older Textual; asked to coexist with 8.2.8 it refuses."
        ),
        guidance=(
            "Not a WASM constraint - the cap binds a terminal install identically. Either pin "
            "your app to a Textual it allows, or wait for the library to widen it."
        ),
    ),
    Library(
        distribution="textual-coloromatic",
        support=Support.TEXTUAL_CAP,
        version="1.0.1",
        downloads=1475,
        summary="animated colour effects and tiled backgrounds",
        observed="Requires `textual>=3.0.0,<6.0.0`; refuses to coexist with 8.2.8.",
        guidance="Same as textual-slidecontainer: a version cap, not a browser problem.",
    ),
    Library(
        distribution="textual-pyfiglet",
        support=Support.TEXTUAL_CAP,
        version="1.1.0",
        downloads=1384,
        summary="Pyfiglet banner text with colour and animation",
        observed="Requires `textual>=3.0.0,<6.0.0`; refuses to coexist with 8.2.8.",
        guidance=(
            "Its own dependency, `pyfiglet`, is pure Python and installs under Pyodide "
            "cleanly - so calling it directly and rendering into a `Static` is a working "
            "route that does not need this wrapper at all."
        ),
    ),
    Library(
        distribution="textual-window",
        support=Support.TEXTUAL_CAP,
        version="0.8.1",
        downloads=78,
        summary="floating, draggable windows and a window manager",
        observed="Requires `textual>=5.1.0,<6.0.0`; refuses to coexist with 8.2.8.",
        guidance=(
            "The narrowest cap in the survey - one minor version wide - so it is the most "
            "likely of these to be widened by its next release. Pin Textual to 5.x if you "
            "need it now."
        ),
    ),
    Library(
        distribution="textual-spinbox",
        support=Support.TEXTUAL_CAP,
        version="0.8.2",
        downloads=13,
        summary="a spinbox",
        observed="Requires `textual>=1.0.0,<2.1.3`; refuses to coexist with 8.2.8.",
        guidance=(
            "Seven majors behind, so pinning Textual down to satisfy it costs more than the "
            "widget is worth. An `Input` with `type='integer'` plus two key bindings is the "
            "shorter route."
        ),
    ),
    # --- BLOCKED: cannot be installed under Pyodide --------------------------------------
    Library(
        distribution="textual-textarea",
        support=Support.BLOCKED,
        downloads=48465,
        summary="a full text editor widget, from the Harlequin project",
        observed=(
            "Depends on `textual[syntax]`, and that extra requires `tree-sitter>=0.25.0` while "
            "Pyodide bundles 0.23.2 as a native wheel - so it cannot be fetched from PyPI at "
            "any version. Measured directly: `micropip.install('textual[syntax]')` fails, "
            "`micropip.install('textual')` succeeds."
        ),
        guidance=(
            "This is the widest-reaching finding in the survey and it is not really about this "
            "library: **`textual[syntax]` does not install under Pyodide 314.0.6**, so Textual's "
            "own `TextArea` syntax highlighting is unavailable too. micropip's message - \"can't "
            'find a pure Python wheel for tree-sitter" - is misleading: it exists, one minor '
            "version too old."
        ),
    ),
    Library(
        distribution="textual-pandas",
        support=Support.BLOCKED,
        downloads=27,
        summary="display Pandas dataframes in Textual",
        observed=(
            "Pins `pandas<=2.2.3`; Pyodide bundles pandas 3.0.2 as a native wheel. The pin "
            "excludes the only version obtainable, so the install fails outright."
        ),
        guidance=(
            "The textbook version-conflict case, and exactly what `textual-wasm build` now "
            "refuses before writing a site. Use `textual-fastdatatable`, or read the frame "
            "yourself into a `DataTable`."
        ),
    ),
    Library(
        distribution="textual-filedrop",
        support=Support.BLOCKED,
        downloads=72,
        summary="a drag-and-drop FileDrop widget",
        observed=(
            "Requires `markdown-it-py>=2.1.0,<3.0.0`, which conflicts with the 4.2.0 that "
            "current Textual itself installs."
        ),
        guidance=(
            "A stale transitive pin rather than a browser constraint. Drag-and-drop into a page "
            "is a browser API anyway, so a terminal FileDrop is not the right mechanism here."
        ),
    ),
    Library(
        distribution="textual-terminal",
        support=Support.BLOCKED,
        version="0.3.0",
        downloads=2695,
        summary="embed another terminal application inside Textual",
        observed=(
            "Installs, then fails to import: `cannot import name 'DEFAULT_COLORS' from "
            "'textual.app'`, a symbol current Textual no longer has."
        ),
        guidance=(
            "Unfixable here even once that import is repaired: it needs a pty and a child "
            "process, and a browser tab has neither. `subprocess` raises and `os.system` "
            "silently does nothing - see the porting matrix."
        ),
    ),
    Library(
        distribution="textual-qrcode",
        support=Support.BLOCKED,
        version="0.2.0",
        downloads=11,
        summary="a QR code widget",
        observed=(
            "Pins `textual==0.10.1` exactly, and its import fails against anything current. "
            "Generates codes by calling qrenco.de over HTTP."
        ),
        guidance="Both halves would need fixing: the exact pin, and then CORS on qrenco.de.",
    ),
    Library(
        distribution="textual-effects",
        support=Support.NOT_ON_PYPI,
        summary="transition effects for widgets",
        observed=(
            "`micropip` cannot fetch metadata for it - there is no PyPI distribution, only a "
            "repository."
        ),
        guidance=(
            "micropip installs from PyPI or a URL, never from git. Vendor the source into your "
            "own package, where the build will ship it like any other module."
        ),
    ),
    # --- OUT_OF_SCOPE: works, but not something you ship into a page ---------------------
    Library(
        distribution="textual-serve",
        support=Support.OUT_OF_SCOPE,
        version="1.1.3",
        downloads=1128421,
        summary="serve a Textual app over HTTP from a Python server",
        observed=(
            "Installs and imports under Pyodide, which is precisely why the install tier alone "
            "is not a verdict. The doctor now flags `web.run_app` at `server.py:229` - and "
            "that call is the divergent kind: silently fine under Node, `OSError 138` in a "
            "browser, so a Node-only check would have passed it."
        ),
        guidance=(
            "It is the *other* architecture: a server runs Python and streams the terminal to a "
            "browser. This project runs Python in the browser and needs no server. Pick one - "
            "there is nothing to compose. It is also the most-downloaded package in this survey, "
            "so the comparison is the one most people actually want."
        ),
    ),
    Library(
        distribution="textual-dev",
        support=Support.OUT_OF_SCOPE,
        version="1.8.0",
        downloads=397962,
        summary="Textual's development tools and console",
        observed="Installs and imports under Pyodide.",
        guidance=(
            "A development dependency: run it on your machine against the terminal build. Its "
            "console talks to a devtools server over a socket, which a page cannot open."
        ),
    ),
    Library(
        distribution="pytest-textual-snapshot",
        support=Support.OUT_OF_SCOPE,
        version="1.1.0",
        downloads=281667,
        summary="snapshot testing for Textual apps",
        observed="Installs and imports under Pyodide.",
        guidance=(
            "Test on the terminal build, where it runs under pytest normally. For checking that "
            "the browser renders identically, `textual-wasm check` compares the runtimes cell "
            "by cell."
        ),
    ),
)
"""Every library probed, grouped by verdict and ordered by downloads within each group."""


SUPPORT_ORDER: Final[tuple[Support, ...]] = (
    Support.VERIFIED,
    Support.IMPORTS,
    Support.TEXTUAL_CAP,
    Support.BLOCKED,
    Support.NOT_ON_PYPI,
    Support.OUT_OF_SCOPE,
)
"""Presentation order: what works first, then what needs a decision, then what cannot."""


def with_support(support: Support) -> tuple[Library, ...]:
    """Every library with `support`, most-downloaded first."""
    return tuple(
        sorted(
            (item for item in LIBRARIES if item.support is support),
            key=lambda item: -item.downloads,
        )
    )


def by_distribution(distribution: str) -> Library:
    """Look one up by name.

    Raises:
        KeyError: If it was not probed. A miss is an error rather than None because the
            caller is asking about a specific library and "no opinion" is not an answer the
            registry can give while pretending to be complete.
    """
    for item in LIBRARIES:
        if item.distribution == distribution:
            return item
    raise KeyError(f"{distribution} is not in the library registry")
