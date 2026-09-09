"""Sphinx configuration.

Markdown rather than reStructuredText because the pages are also read on GitHub, and Furo
because it is the theme that does the least: two columns, a real search, and a dark mode the
reader chooses rather than one the site imposes.
"""

from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

project = "textual-wasm"
author = "Kai Erik Niermann"
copyright = "2026, Kai Erik Niermann"  # noqa: A001 - the name Sphinx requires
release = importlib.metadata.version("textual-wasm")
version = release

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_design",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "linkify",
    "substitution",
]
myst_heading_anchors = 3

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "textual": ("https://textual.textualize.io", None),
}

templates_path = ["_templates"]
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    # Included into matrix.md rather than built as a page of its own. It is generated, and
    # the generator writes a whole document; the wrapper is what gives it context.
    "porting-matrix.md",
]

html_theme = "furo"
html_title = f"textual-wasm {release}"
html_static_path = ["_static"]
# Named explicitly, because a browser requests /favicon.ico by default and that 404 shows up
# in every page-error check run against this site.
html_favicon = "_static/favicon.svg"
html_css_files = ["custom.css"]
html_theme_options = {
    "source_repository": "https://github.com/KaiErikNiermann/textual-wasm/",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/KaiErikNiermann/textual-wasm",
            "html": (
                '<svg stroke="currentColor" fill="currentColor" stroke-width="0" '
                'viewBox="0 0 16 16"><path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 '
                "3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01."
                "37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-."
                "01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3."
                "64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 "
                "2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1"
                ".16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54."
                '73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0016 8c0'
                '-4.42-3.58-8-8-8z"></path></svg>'
            ),
            "class": "",
        },
    ],
}
