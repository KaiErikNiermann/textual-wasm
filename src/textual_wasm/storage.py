"""One persistent directory, on a terminal and in a browser, with the same code.

The temptation is to write a storage *abstraction* - a `Store` protocol with a SQLite
backend for the terminal and an IndexedDB backend for the page. That is the wrong shape for
this runtime, and measurably so: Pyodide can mount IndexedDB *as a filesystem*, so ordinary
`open()` and `sqlite3.connect()` already work in a browser and already persist. An
abstraction over two backends would be a reimplementation of the one the runtime hands you,
with a second set of bugs and no structured queries.

What genuinely differs is not the API but the durability model. On a terminal a write is
durable when `write()` returns. Under IDBFS it is durable when someone calls `syncfs`, which
is asynchronous, whole-file, and nobody's default. So this module is deliberately thin:

* `location()` - where the files go, which is the only thing that differs by runtime.
* `Store.flush()` - the one call a browser needs and a terminal does not, written so that
  calling it unconditionally is correct on both.

Everything else is `pathlib` and the standard library, because that is what already works.

The mount itself is the page's job, not Python's: it has to exist before the interpreter
runs. `boot.mjs` performs it when a build asks for storage and registers the flush callback
as a JavaScript module, the same contract `textual_wasm.browser` uses for the terminal. A
build without storage leaves that module absent, which is how `location()` knows.
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable

_log: Final = logging.getLogger(__name__)

STORAGE_MODULE: Final[str] = "textual_wasm_storage"
"""Name the page registers its storage object under via `pyodide.registerJsModule`."""

DEFAULT_MOUNT: Final[str] = "/persist"
"""Where `boot.mjs` mounts IDBFS. Named here so the two sides cannot drift apart."""


class StorageHost(Protocol):
    """The contract a page satisfies to give an application a persistent directory.

    One method and one attribute, for the same reason `TerminalHost` is four members: the
    page owns the mount, and anything more would be this module reaching into the runtime.

    Not `@runtime_checkable`: the object that satisfies this is always a `JsProxy`, and a
    protocol instance check cannot see through one. `_host` checks the members by name and
    says why.
    """

    mountPoint: str  # noqa: N815 - a JavaScript member, not a Python one

    def flush(self) -> Awaitable[None]:
        """Resolve once the mounted filesystem has been written back to IndexedDB."""
        ...


class StorageKind(enum.StrEnum):
    """Which of the three situations an application is actually in."""

    NATIVE = "native"
    """A real filesystem. Writes are durable when they return; `flush` does nothing."""

    PERSISTENT = "persistent"
    """A browser with a mounted IDBFS. Writes are durable when `flush` resolves."""

    EPHEMERAL = "ephemeral"
    """A browser with no mount, so writes go to MEMFS and die with the tab.

    Its own state rather than an error, because it is the right answer for a build that
    never asked for storage - and reporting it as persistent is the failure this module
    exists to prevent. An application that cares can say so in its own UI.
    """


@dataclasses.dataclass(frozen=True, slots=True)
class Location:
    """Where an application's persistent files live on this runtime."""

    root: Path
    kind: StorageKind

    @property
    def durable(self) -> bool:
        """Whether anything written here survives the process."""
        return self.kind is not StorageKind.EPHEMERAL


def _host() -> StorageHost | None:
    """The page's storage object, or None if this is not a browser build with storage.

    An absent module is the ordinary case - every native run, and every browser build that
    did not ask for storage - so it is not logged as a problem.
    """
    try:
        module = importlib.import_module(STORAGE_MODULE)
    except ImportError:
        return None

    # `hasattr`, not `isinstance(module, StorageHost)`, and this is not a style choice.
    # Since CPython 3.12 a runtime-checkable Protocol's instance check uses
    # `inspect.getattr_static`, which deliberately does not invoke `__getattr__` - and a
    # `JsProxy` exposes every JavaScript property through exactly that. So the isinstance
    # form returns False for an object whose members are all present and readable, and the
    # symptom is a build with `--storage` reporting itself as having none. Measured: the
    # module imports, `hasattr(module, "mountPoint")` is True, `mountPoint` reads back
    # `/persist`, and `isinstance` is False.
    if not all(hasattr(module, member) for member in ("mountPoint", "flush")):
        # Registered, but not the shape this module needs. Worth a complaint: it means a
        # custom page tried to provide storage and got the contract wrong, and silence
        # would present that as "no storage was requested".
        _log.warning("%s is registered but does not satisfy StorageHost", STORAGE_MODULE)
        return None
    return cast("StorageHost", module)


def location(app_name: str) -> Location:
    """Decide where `app_name` keeps its files, and on what terms.

    Args:
        app_name: Used as the directory name. A slug, not a title - it becomes a path
            component on both runtimes.

    Returns:
        The directory, created if absent, and which durability rules apply to it.
    """
    host = _host()
    if host is not None:
        root = Path(host.mountPoint) / app_name
        root.mkdir(parents=True, exist_ok=True)
        return Location(root=root, kind=StorageKind.PERSISTENT)

    if _in_browser():
        # MEMFS. A temporary directory rather than refusing: an application that writes a
        # config should still run in a build that did not ask for persistence, and it finds
        # out by asking, not by catching an exception from `open`.
        root = Path(tempfile.gettempdir()) / app_name
        root.mkdir(parents=True, exist_ok=True)
        return Location(root=root, kind=StorageKind.EPHEMERAL)

    # platformdirs rather than `~/.app_name`: it is already a dependency, and it is the
    # difference between respecting XDG_CONFIG_HOME and ignoring it.
    from platformdirs import user_data_path  # noqa: PLC0415 - native-only import

    root = user_data_path(appname=app_name)
    root.mkdir(parents=True, exist_ok=True)
    return Location(root=root, kind=StorageKind.NATIVE)


def _in_browser() -> bool:
    """Whether this is Pyodide, by the presence of its own module rather than a platform
    string. `sys.platform` is `emscripten` for Node builds too, and those have a real
    filesystem."""
    try:
        importlib.import_module("pyodide")
    except ImportError:
        return False
    return True


@dataclasses.dataclass(frozen=True, slots=True)
class Store:
    """A directory whose contents survive, and the one call that makes that true.

    Not a key-value abstraction over two databases. The methods are the two or three file
    operations an application repeats often enough to be worth not rewriting - each one
    marking the filesystem dirty so `flush` has something to do - plus `path`, which is the
    escape hatch that keeps this class from needing to grow. `sqlite3.connect(store.path(
    "notes.db"))` is the intended way to store anything structured; there is no wrapper for
    it because there is nothing a wrapper would add.
    """

    location: Location

    @classmethod
    def open(cls, app_name: str) -> Store:
        """Prepare storage for `app_name` on whichever runtime this is."""
        return cls(location=location(app_name))

    @property
    def durable(self) -> bool:
        return self.location.durable

    def path(self, name: str) -> Path:
        """The full path for `name`, for code that wants a path rather than bytes.

        Args:
            name: A file name. A relative path with parents is allowed and its directories
                are created; an absolute one is refused rather than silently escaping the
                store.

        Raises:
            ValueError: If `name` is absolute or climbs out of the store.
        """
        candidate = self.location.root / name
        resolved = candidate.resolve()
        root = self.location.root.resolve()
        if Path(name).is_absolute() or not resolved.is_relative_to(root):
            raise ValueError(f"{name!r} is not inside the store")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def read_text(self, name: str, *, default: str | None = None) -> str | None:
        """Read `name`, or return `default` if it is not there yet.

        First-run absence is the common case, not an error: an application whose every load
        is wrapped in `try: ... except FileNotFoundError` is the repetition this removes.
        """
        try:
            return self.path(name).read_text(encoding="utf-8")
        except FileNotFoundError:
            return default

    def read_bytes(self, name: str, *, default: bytes | None = None) -> bytes | None:
        """Read `name` as bytes, or return `default` if it is not there yet."""
        try:
            return self.path(name).read_bytes()
        except FileNotFoundError:
            return default

    def write_text(self, name: str, content: str) -> None:
        """Write `name` atomically. Call `flush` to make it durable in a browser."""
        self._atomic_write(name, content.encode("utf-8"))

    def write_bytes(self, name: str, content: bytes) -> None:
        """Write `name` atomically. Call `flush` to make it durable in a browser."""
        self._atomic_write(name, content)

    def _atomic_write(self, name: str, payload: bytes) -> None:
        """Write via a sibling temporary file and one rename.

        Worth the extra call even under MEMFS: the failure it prevents is a half-written
        config that the next load cannot parse, and on this runtime "the next load" can be
        a page refresh in the middle of a write.
        """
        target = self.path(name)
        scratch = target.with_name(f"{target.name}.partial")
        scratch.write_bytes(payload)
        scratch.replace(target)

    async def flush(self) -> None:
        """Make everything written so far durable.

        Does nothing natively, where it already is. In a browser this is the call that
        actually writes the mounted filesystem back to IndexedDB - until it resolves, a
        closed tab loses the writes. Safe and cheap to call unconditionally, which is the
        point: application code has no runtime check in it.
        """
        host = _host()
        if host is None:
            return
        await host.flush()


def flush_on_exit(app: object, store: Store) -> None:
    """Flush `store` when `app` exits, for apps that do not want to remember to.

    Args:
        app: A Textual `App`. Typed as `object` so this module never imports textual - it is
            used by application code that already has one, and importing textual here would
            put a UI framework in the dependency path of a file-writing helper.
        store: The store to flush.

    The exit path is not the only one that matters in a browser - a closed tab never reaches
    it - which is why `boot.mjs` also flushes on `pagehide`. Both exist because neither is
    sufficient: the page hook cannot know when the application considers itself consistent,
    and the application cannot hear the tab close.
    """
    callback = getattr(app, "call_later", None)
    if callback is None:  # pragma: no cover - not a Textual App
        raise TypeError("flush_on_exit expects a Textual App")

    original = getattr(app, "_on_exit_app", None)
    if original is None:  # pragma: no cover - Textual changed its lifecycle
        raise TypeError("this Textual version has no _on_exit_app hook to wrap")

    async def _flush_then_exit() -> None:
        await store.flush()
        await cast("Awaitable[None]", original())

    setattr(app, "_on_exit_app", _flush_then_exit)  # noqa: B010 - the name is the hook
