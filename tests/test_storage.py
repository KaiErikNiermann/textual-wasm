"""The storage module, and the contract it shares with the page that mounts the filesystem.

Every test here runs natively, which is the interesting constraint: the browser half cannot
be exercised from pytest, so what is testable is the *native* behaviour plus the two things
that would silently disable the browser half - a drifted module name and a drifted mount
point. Both are strings duplicated across a language boundary, which is exactly the kind of
duplication that stays correct until someone renames one side.

The browser behaviour itself was verified by building `examples/persistent-notes` and
driving it through a real reload in Chromium and Firefox, on the main thread and in a Web
Worker. That is not a unit test and does not pretend to be one.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from pathlib import Path
from typing import Final

import pytest

from textual_wasm import storage
from textual_wasm.storage import DEFAULT_MOUNT, STORAGE_MODULE, StorageKind, Store

BOOT_ASSET: Final[Path] = Path(storage.__file__).parent / "assets" / "boot.mjs"


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """A store rooted in a temporary directory, standing in for platformdirs."""

    def fake_location(app_name: str) -> storage.Location:
        root = tmp_path / app_name
        root.mkdir(parents=True, exist_ok=True)
        return storage.Location(root, StorageKind.NATIVE)

    monkeypatch.setattr(storage, "location", fake_location)
    return Store.open("test-app")


def test_a_native_store_is_durable_without_flushing(store: Store) -> None:
    assert store.durable
    assert store.location.kind is StorageKind.NATIVE


def test_reading_a_file_that_does_not_exist_yet_returns_the_default(store: Store) -> None:
    """First-run absence is the common case, and wrapping every load in try/except is the
    repetition the module exists to remove."""
    assert store.read_text("settings.json") is None
    assert store.read_text("settings.json", default="{}") == "{}"
    assert store.read_bytes("blob.bin", default=b"") == b""


def test_text_and_bytes_round_trip(store: Store) -> None:
    store.write_text("settings.json", '{"theme": "nord"}')
    store.write_bytes("blob.bin", b"\x00\x01\x02")
    assert store.read_text("settings.json") == '{"theme": "nord"}'
    assert store.read_bytes("blob.bin") == b"\x00\x01\x02"


def test_a_write_leaves_no_partial_file_behind(store: Store) -> None:
    """The atomic write goes through a sibling and one rename; the sibling must not survive."""
    store.write_text("settings.json", "value")
    names = {path.name for path in store.location.root.iterdir()}
    assert names == {"settings.json"}, f"partial file left behind: {names}"


def test_nested_names_create_their_directories(store: Store) -> None:
    store.write_text("cache/today/notes.txt", "hello")
    assert store.read_text("cache/today/notes.txt") == "hello"


@pytest.mark.parametrize("name", ["/etc/passwd", "../../escape", "sub/../../escape"])
def test_a_name_cannot_escape_the_store(store: Store, name: str) -> None:
    """A store is a directory, and a path that leaves it is a bug rather than a feature."""
    with pytest.raises(ValueError, match="not inside the store"):
        store.path(name)


def test_sqlite_works_against_a_store_path(store: Store) -> None:
    """The documented usage, asserted rather than described: the module hands out a path and
    the standard library does the rest."""
    connection = sqlite3.connect(store.path("notes.db"))
    connection.execute("CREATE TABLE notes (body TEXT)")
    connection.execute("INSERT INTO notes VALUES ('hello')")
    connection.commit()
    assert connection.execute("SELECT body FROM notes").fetchone()[0] == "hello"
    connection.close()


def test_flushing_a_native_store_does_nothing_and_does_not_raise(store: Store) -> None:
    """The property that keeps a runtime branch out of application code: calling `flush`
    unconditionally is correct on a terminal, not merely tolerated."""
    store.write_text("settings.json", "value")
    asyncio.run(store.flush())
    assert store.read_text("settings.json") == "value"


def test_a_native_run_finds_a_real_directory_without_a_page(tmp_path: Path) -> None:
    """Asserted through the public surface rather than by poking at `_host`: what callers
    can observe is the `Location`, and a native run must resolve one with no page involved.

    Both the absent-module path and the platformdirs fallback are exercised by this, which is
    the whole native branch of `location()`.
    """
    location = storage.location("textual-wasm-test-native")
    assert location.kind is StorageKind.NATIVE
    assert location.durable
    assert location.root.is_dir()


def test_the_page_and_python_agree_on_the_module_name_and_mount() -> None:
    """Two strings, two languages, one contract.

    If these drift, nothing raises: `_host()` fails to import, `location()` falls through to
    the ephemeral branch, and a build made with `--storage` reports itself as having none.
    That is the exact symptom this test exists to turn into a failure.
    """
    source = BOOT_ASSET.read_text(encoding="utf-8")
    module = re.search(r'STORAGE_MODULE = "([^"]+)"', source)
    mount = re.search(r'STORAGE_MOUNT = "([^"]+)"', source)
    assert module is not None, "boot.mjs no longer declares STORAGE_MODULE"
    assert mount is not None, "boot.mjs no longer declares STORAGE_MOUNT"
    assert module.group(1) == STORAGE_MODULE
    assert mount.group(1) == DEFAULT_MOUNT


def test_the_page_mounts_before_it_installs_packages() -> None:
    """Ordering matters and is invisible: a package whose import reads a config file needs
    the filesystem to already be there."""
    source = BOOT_ASSET.read_text(encoding="utf-8")
    assert source.index("mountStorage(pyodide)") < source.index('pyimport("micropip").install')
