"""The playground runner: the share format, and turning a program into an app."""

from __future__ import annotations

import base64
import zlib
from pathlib import Path

import pytest
from textual.app import App

from playground_runner import share
from playground_runner.app import (
    NoAppError,
    load,
    program_frames,
)

STARTERS = Path(__file__).resolve().parent.parent / "playground" / "starters"

HELLO = """\
from textual.app import App
from textual.widgets import Static


class Hello(App[None]):
    def compose(self):
        yield Static("hello")
"""


def test_a_program_survives_the_round_trip() -> None:
    source = HELLO + "# ünïcode, emoji 🎉 and a # in a comment\n"
    assert share.decode("#" + share.encode(source)) == source


def test_the_payload_is_url_safe() -> None:
    fragment = share.encode(HELLO * 20)
    assert fragment.startswith(share.PREFIX)
    assert set(fragment.removeprefix(share.PREFIX)) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )


def test_what_the_page_writes_is_readable() -> None:
    """Raw DEFLATE, unpadded base64url: what `CompressionStream("deflate-raw")` emits."""
    compressor = zlib.compressobj(wbits=-15)
    packed = compressor.compress(b"print('hi')") + compressor.flush()
    fragment = "v1." + base64.urlsafe_b64encode(packed).decode().rstrip("=")
    assert share.decode(fragment) == "print('hi')"


@pytest.mark.parametrize("fragment", ["", "#", "#v2.abc", "#code=abc", "#v1.!!!!", "#v1.AAAA"])
def test_a_fragment_that_is_not_a_program_is_refused(fragment: str) -> None:
    with pytest.raises(share.ShareError):
        share.decode(fragment)


def test_a_decompression_bomb_is_refused() -> None:
    bomb = share.encode("#" * (share.MAX_SOURCE_BYTES + 1))
    assert len(bomb) < 4096
    with pytest.raises(share.ShareError, match="over"):
        share.decode(bomb)


def test_an_app_that_is_run_is_the_one_returned(tmp_path: Path) -> None:
    source = HELLO + 'if __name__ == "__main__":\n    Hello().run()\n'
    app = load(source, tmp_path)
    assert type(app).__name__ == "Hello"
    # Intercepted only while the program runs, not left patched for everyone after.
    assert vars(App)["run"].__qualname__ == "App.run"


def test_an_app_that_is_only_defined_is_found(tmp_path: Path) -> None:
    assert type(load(HELLO, tmp_path)).__name__ == "Hello"


def test_an_instance_wins_over_a_class(tmp_path: Path) -> None:
    source = HELLO + "class Other(Hello):\n    pass\n\napp = Hello()\n"
    assert type(load(source, tmp_path)).__name__ == "Hello"


def test_a_program_without_an_app_says_so(tmp_path: Path) -> None:
    with pytest.raises(NoAppError, match="defines no Textual app"):
        load("x = 1\n", tmp_path)


def test_an_imported_app_class_is_not_mistaken_for_the_program(tmp_path: Path) -> None:
    with pytest.raises(NoAppError):
        load("from textual.app import App\n", tmp_path)


def test_errors_in_the_program_propagate_with_its_line(tmp_path: Path) -> None:
    with pytest.raises(ZeroDivisionError) as caught:
        load("x = 1\ny = x / 0\n", tmp_path)
    assert caught.traceback[-1].path == tmp_path / "app.py"
    assert caught.traceback[-1].lineno == 1  # zero-based


def test_the_shown_traceback_starts_in_the_program(tmp_path: Path) -> None:
    with pytest.raises(ZeroDivisionError) as caught:
        load("def f():\n    return 1 / 0\n\nf()\n", tmp_path)
    trace = program_frames(caught.value.__traceback__, tmp_path / "app.py")
    assert trace is not None
    assert trace.tb_frame.f_code.co_filename == str(tmp_path / "app.py")


@pytest.mark.parametrize("starter", sorted(STARTERS.glob("*.py")), ids=lambda path: path.stem)
def test_every_starter_builds_an_app(starter: Path, tmp_path: Path) -> None:
    """The picker's programs are the first thing anyone runs; a broken one is the first
    impression."""
    assert isinstance(load(starter.read_text(encoding="utf-8"), tmp_path), App)
