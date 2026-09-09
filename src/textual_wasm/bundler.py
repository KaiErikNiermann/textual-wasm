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

import contextlib
import dataclasses
import http.server
import json
import mimetypes
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Final

from textual_wasm.pins import resolve_pins

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

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

_SHUTDOWN_TIMEOUT: Final[float] = 5.0
"""How long to wait for the serving thread after `shutdown()`; it should be immediate."""

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

    title: str | None = None
    """Document title. Defaults to the application class's name.

    The page is the user's, not this project's: a heading naming `textual-wasm` on someone
    else's application would be branding, and a tab labelled "spike" is worse.
    """

    worker: bool = False
    """Run the interpreter in a Web Worker instead of on the page's main thread.

    Off by default because it is a different failure surface, not because it is worse: a
    worker build needs no COOP/COEP headers (measured - `crossOriginIsolated` is `False`
    inside one and Pyodide boots anyway), so it deploys anywhere the default does.

    What it buys is that a slow Python call stops freezing the tab. What it does not buy is
    threads: `sys._emscripten_info.pthreads` is `False` in a worker exactly as it is on the
    main thread, so `@work(thread=True)` remains unavailable either way.
    """

    template: Path | None = None
    """A directory of files copied over the default page, or None for the default.

    The whole customisation story, and deliberately a directory rather than a set of options:
    what people want to change is a *document*, and every option that tries to parameterise
    one ends up reinventing a worse templating language. Anything here wins over the shipped
    asset of the same name, so overriding `index.html` alone is a two-file directory.
    """


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


def _copy_assets(output: Path, template: Path | None) -> None:
    """Copy the shipped page, then let a template overwrite any part of it.

    Raises:
        FileNotFoundError: If a template directory was named and does not exist. Silently
            building the default page instead would look like the override was ignored.
    """
    shutil.copytree(ASSETS, output, dirs_exist_ok=True)
    if template is None:
        return
    if not template.is_dir():
        raise FileNotFoundError(template)
    shutil.copytree(template, output, dirs_exist_ok=True)


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
    _copy_assets(spec.output, spec.template)

    own_package = Path(__file__).parent
    sources = {
        own_package.name: _collect_sources(own_package),
        spec.package.name: _collect_sources(spec.package),
    }
    (spec.output / SOURCES_NAME).write_text(json.dumps(sources), encoding="utf-8")

    requirements = (*resolve_pins(), *spec.requirements)
    manifest = {
        "entry": spec.entry,
        "title": spec.title or spec.entry.partition(":")[2],
        "requirements": list(requirements),
        "worker": spec.worker,
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
    with _server(directory, port=port, host=host, quiet=False) as server:
        server.serve_forever()


@contextlib.contextmanager
def background_server(directory: Path, *, port: int = 0, host: str = "127.0.0.1") -> Generator[str]:
    """Serve a built directory on a thread, yielding the URL it is reachable at.

    The browser leg of a check drives a real `build` through a real `dev`, because checking
    something other than what ships is how a harness comes to pass while the product is
    broken. Port 0 by default so two checks running at once cannot collide.

    Args:
        directory: A directory produced by `build`.
        port: Port to listen on, or 0 to let the OS choose.
        host: Interface to bind.

    Yields:
        The base URL, with the port actually bound.
    """
    with _server(directory, port=port, host=host, quiet=True) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://{host}:{server.server_address[1]}/"
        finally:
            server.shutdown()
            thread.join(timeout=_SHUTDOWN_TIMEOUT)


def _server(
    directory: Path, *, port: int, host: str, quiet: bool
) -> http.server.ThreadingHTTPServer:
    """Bind a static file server for `directory`.

    `quiet` silences the access log, which a developer watching `dev` wants and a check
    running four runtimes does not - there it would bury the report in request lines.
    """
    # Neither type is in every platform's registry, and a wasm module served as
    # application/octet-stream fails instantiation with a message about the MIME type.
    mimetypes.add_type("application/wasm", ".wasm")
    mimetypes.add_type("text/javascript", ".mjs")
    return http.server.ThreadingHTTPServer((host, port), _handler_for(directory, quiet=quiet))


def _handler_for(directory: Path, *, quiet: bool) -> type[http.server.SimpleHTTPRequestHandler]:
    """Build a request handler rooted at `directory`, with caching off."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, directory=str(directory), **kwargs)  # type: ignore[arg-type]

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib name
            if not quiet:
                super().log_message(format, *args)

        def end_headers(self) -> None:
            # A development server that caches is a development server people restart for no
            # reason. The Pyodide runtime is fetched from a CDN and cached there instead.
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    return Handler


def default_requirements() -> Sequence[str]:
    """This project's own dependency closure, as a build would install it."""
    return resolve_pins()
