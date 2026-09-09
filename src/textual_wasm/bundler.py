"""Turn a Textual app into a directory you can serve.

The output is static files and nothing else: no server, no build toolchain at the far end,
and nothing for the person deploying it to install. That is the whole claim of the project
made concrete - the same source runs in a terminal and, after this, in a browser.

Python is written as *source* rather than wheels. It costs a little size and buys two things
worth more: a development server can serve straight from the working tree so an edit needs
only a reload, and the browser demonstrably runs the same files the other runtimes do, which
is what the cross-runtime comparison depends on.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Final

from textual_wasm.pins import resolve_pins

if TYPE_CHECKING:
    from collections.abc import Sequence

ASSETS: Final[Path] = Path(__file__).parent / "assets"
"""The page, its stylesheet and the entry script, shipped with the package."""

PYODIDE_VERSION: Final[str] = "314.0.6"
"""Pinned deliberately. Pyodide's ABI changes between releases and its versions now track
the CPython they ship, so "latest" is a different interpreter, not a patch."""

XTERM_VERSION: Final[str] = "6.0.0"
FIT_ADDON_VERSION: Final[str] = "0.11.0"

_JSDELIVR: Final[str] = "https://cdn.jsdelivr.net"

ASSET_URLS: Final[dict[str, str]] = {
    "pyodideIndexUrl": f"{_JSDELIVR}/pyodide/v{PYODIDE_VERSION}/full/",
    "xtermUrl": f"{_JSDELIVR}/npm/@xterm/xterm@{XTERM_VERSION}/lib/xterm.mjs",
    "xtermCssUrl": f"{_JSDELIVR}/npm/@xterm/xterm@{XTERM_VERSION}/css/xterm.css",
    "fitAddonUrl": f"{_JSDELIVR}/npm/@xterm/addon-fit@{FIT_ADDON_VERSION}/lib/addon-fit.mjs",
}
"""Runtime dependencies, by pinned version.

Written into the manifest rather than hard-coded in the page, so these versions exist in one
place. The page imports them dynamically at boot; a second copy in JavaScript is precisely
the drift this project keeps finding elsewhere."""

MANIFEST_NAME: Final[str] = "app.json"
SOURCES_NAME: Final[str] = "sources.json"
ENTRY_NAME: Final[str] = "entry.py"

SOURCE_SUFFIXES: Final[tuple[str, ...]] = (".py", ".tcss", ".css")
"""What gets copied into the browser's filesystem. Textual apps carry stylesheets next to
their code, and a `.tcss` left behind fails at mount time rather than at build time."""


@dataclasses.dataclass(frozen=True, slots=True)
class BuildSpec:
    """What to build."""

    entry: str
    """`module:AppClass`, the same form Textual's own runner accepts."""

    package: Path
    """Directory of the application's Python package."""

    output: Path

    requirements: tuple[str, ...] = ()
    """Extra distributions to install, on top of this project's own closure."""


@dataclasses.dataclass(frozen=True, slots=True)
class BuildResult:
    """What was built."""

    output: Path
    entry: str
    requirements: tuple[str, ...]
    packages: tuple[str, ...]
    file_count: int
    total_bytes: int

    @property
    def summary(self) -> str:
        kilobytes = self.total_bytes / 1024
        return (
            f"{self.file_count} files, {kilobytes:.0f} KiB, {len(self.requirements)} requirement(s)"
        )


def _collect_sources(package: Path) -> dict[str, str]:
    """Read a package's shippable files, keyed by path relative to the package root."""
    return {
        str(path.relative_to(package)): path.read_text(encoding="utf-8")
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.suffix in SOURCE_SUFFIXES and "__pycache__" not in path.parts
    }


def _copy_assets(output: Path) -> None:
    """Copy the page and its stylesheet, leaving the entry script to be placed by name."""
    shutil.copytree(ASSETS, output, dirs_exist_ok=True)


def _measure(output: Path) -> tuple[int, int]:
    files = [path for path in output.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def build(spec: BuildSpec) -> BuildResult:
    """Produce a self-contained static site for `spec`.

    Args:
        spec: What to build and where.

    Returns:
        A description of the output, for the CLI to report.

    Raises:
        FileNotFoundError: If the application package does not exist.
        NotADirectoryError: If it is not a directory - the entry names a module inside a
            package, so a single file is not enough to reconstruct the import path.
    """
    if not spec.package.exists():
        raise FileNotFoundError(spec.package)
    if not spec.package.is_dir():
        raise NotADirectoryError(spec.package)

    spec.output.mkdir(parents=True, exist_ok=True)
    _copy_assets(spec.output)

    own_package = Path(__file__).parent
    sources = {
        own_package.name: _collect_sources(own_package),
        spec.package.name: _collect_sources(spec.package),
    }
    (spec.output / SOURCES_NAME).write_text(json.dumps(sources), encoding="utf-8")

    requirements = (*resolve_pins(), *spec.requirements)
    manifest = {
        "entry": spec.entry,
        "requirements": list(requirements),
        **ASSET_URLS,
        "sourcesUrl": f"./{SOURCES_NAME}",
        "entryUrl": f"./{ENTRY_NAME}",
    }
    (spec.output / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    file_count, total_bytes = _measure(spec.output)
    return BuildResult(
        output=spec.output,
        entry=spec.entry,
        requirements=requirements,
        packages=tuple(sources),
        file_count=file_count,
        total_bytes=total_bytes,
    )


def serve(directory: Path, *, port: int, host: str = "127.0.0.1") -> None:
    """Serve a built directory until interrupted.

    Uses the standard library's server rather than shipping one: the output is static files,
    and requiring Node to look at them would undo the point of a Python package that builds
    a static site.

    Args:
        directory: A directory produced by `build`.
        port: Port to listen on.
        host: Interface to bind. Loopback by default - a development server is not a
            deployment target.
    """
    import http.server  # noqa: PLC0415 - only needed by this command
    import mimetypes  # noqa: PLC0415 - only needed by this command

    # Neither type is in every platform's registry, and a wasm module served as
    # application/octet-stream fails instantiation with a message about the MIME type.
    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/javascript", ".mjs")

    handler = _handler_for(directory)
    with http.server.ThreadingHTTPServer((host, port), handler) as server:
        server.serve_forever()


def _handler_for(directory: Path) -> type:
    """Build a request handler rooted at `directory`, with caching off."""
    import http.server  # noqa: PLC0415 - only needed by serve()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(directory), **kwargs)  # type: ignore[arg-type]

        def end_headers(self) -> None:
            # A development server that caches is a development server people restart for no
            # reason. The Pyodide runtime is fetched from a CDN and cached there instead.
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    return Handler


def default_requirements() -> Sequence[str]:
    """This project's own dependency closure, as a build would install it."""
    return resolve_pins()
