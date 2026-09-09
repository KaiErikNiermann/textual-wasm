"""Tests for the diagnostics layer.

The guards are installed with `force=True` so they can be exercised on CPython. That is
sound because a guard's job is to report, not to reproduce Pyodide's behaviour: what is under
test is that the right substitution is reported with the right policy, and that the real
callable still runs when the policy is `WARN`.
"""

from __future__ import annotations

import asyncio
import os
import time
import warnings
from collections.abc import Iterator

import pytest

from textual_wasm import diagnostics
from textual_wasm.app import SpikeApp
from textual_wasm.diagnostics import GuardPolicy, UnsupportedInWasmError
from textual_wasm.diagnostics.errors import WasmCompatibilityWarning
from textual_wasm.driver import active_capture
from textual_wasm.substitutions import Severity, by_id, with_severity


@pytest.fixture
def guards() -> Iterator[None]:
    """Install the guards on CPython and take them back off afterwards."""
    diagnostics.install(force=True)
    try:
        yield
    finally:
        diagnostics.uninstall()


def test_install_is_a_no_op_off_emscripten_by_default() -> None:
    """None of these operations misbehave natively, so guarding them would be noise."""
    diagnostics.install()
    try:
        assert time.sleep.__module__ != __name__
        assert diagnostics.recorded() == ()
    finally:
        diagnostics.uninstall()


def test_uninstall_restores_every_patch() -> None:
    original_sleep = time.sleep
    diagnostics.install(force=True)
    assert time.sleep is not original_sleep
    diagnostics.uninstall()
    assert time.sleep is original_sleep


def test_os_system_raises_because_a_browser_silently_ignores_it(guards: None) -> None:
    """The most dangerous entry: it works under Node and does nothing in a browser."""
    with pytest.raises(UnsupportedInWasmError) as caught:
        os.system("true")  # noqa: S605, S607 - the call under test  # pyright: ignore[reportDeprecated]
    assert caught.value.substitution.id == "os.system"


def test_a_warning_guard_still_runs_the_real_call(guards: None) -> None:
    """`WARN` exists for operations that return the right answer at an unexpected cost.

    Suppressing the call would break correct code, which is the whole reason the policy is
    split rather than uniform.
    """
    started = time.monotonic()
    with pytest.warns(WasmCompatibilityWarning):
        time.sleep(0.01)
    assert time.monotonic() - started >= 0.01


def test_a_zero_sleep_is_not_reported(guards: None) -> None:
    """`time.sleep(0)` is the yield idiom and costs nothing; reporting it buries real cases."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        time.sleep(0)


async def test_run_in_executor_is_reported(guards: None) -> None:
    """Pyodide's loop ignores the executor and runs inline, freezing the page."""
    with pytest.warns(WasmCompatibilityWarning) as caught:
        result = await asyncio.get_running_loop().run_in_executor(None, lambda: 41 + 1)
    assert result == 42
    assert caught[0].message.substitution.id == "asyncio.run_in_executor"  # type: ignore[union-attr]


def test_warnings_are_recorded_as_well_as_warned(guards: None) -> None:
    """`warnings.warn` writes to stderr, which under Pyodide nobody is reading."""
    with pytest.warns(WasmCompatibilityWarning):
        time.sleep(0.001)
    assert [w.substitution.id for w in diagnostics.recorded()] == ["time.sleep"]
    assert "time.sleep" in diagnostics.describe_recorded()


def test_policies_can_be_tightened(guards: None) -> None:
    """A project that wants a strict run should be able to make every guard fatal."""
    diagnostics.uninstall()
    diagnostics.install(force=True, policies={"time.sleep": GuardPolicy.RAISE})
    with pytest.raises(UnsupportedInWasmError):
        time.sleep(0.001)


def test_every_guarded_substitution_has_a_policy() -> None:
    """A guard with no policy silently defaults to warning, which may not be intended."""
    for substitution_id in diagnostics.DEFAULT_POLICIES:
        assert by_id(substitution_id)


def test_silent_substitutions_are_all_guarded() -> None:
    """`SILENT_WRONG` is the class that needs a guard by definition - nothing else reports it.

    `socket.connect` is guarded under the id of the substitution it belongs to; the fatal
    `os.kill` variant is guarded too, since it destroys the runtime rather than merely
    misbehaving.
    """
    guarded = set(diagnostics.DEFAULT_POLICIES)
    silent = {s.id for s in with_severity(Severity.SILENT_WRONG)}
    assert silent <= guarded, f"unguarded silent failures: {silent - guarded}"


# --- translation ------------------------------------------------------------------------


def test_a_misleading_message_is_translated() -> None:
    translated = diagnostics.translate(RuntimeError("can't start new thread"))
    assert translated is not None
    assert translated.substitution.id in {"threading.thread", "concurrent.thread_pool"}
    assert "asyncio" in translated.substitution.guidance


def test_a_good_message_is_left_alone() -> None:
    """Pyodide's own message here names the constraint exactly; replacing it is a regression."""
    assert diagnostics.translate(OSError("emscripten does not support processes.")) is None


def test_an_unrelated_error_is_left_alone() -> None:
    assert diagnostics.translate(ValueError("something else entirely")) is None


def test_translation_is_idempotent() -> None:
    """An already-translated error must not be wrapped a second time."""
    translated = diagnostics.translate(RuntimeError("can't start new thread"))
    assert translated is not None
    assert diagnostics.translate(translated) is None


def test_diagnostics_render_as_rich_so_textual_shows_them() -> None:
    """`App._handle_exception` routes an exception with `__rich__` through `panic()`.

    Without this the app dumps a raw traceback to a browser console instead.
    """
    error = UnsupportedInWasmError(by_id("os.system"), detail="os.system('ls')")
    assert hasattr(error, "__rich__")
    from rich.console import Console  # noqa: PLC0415 - only needed for this assertion

    rendered = Console(width=100, file=None, record=True)
    rendered.print(error.__rich__())
    text = rendered.export_text()
    assert "os.system" in text
    assert "What to do instead" in text


# --- surfacing --------------------------------------------------------------------------


class _CrashingApp(SpikeApp):
    """An app that dies during mount, to prove the traceback goes somewhere visible."""

    def on_mount(self) -> None:
        raise RuntimeError("deliberate crash")


async def test_crash_output_reaches_the_terminal_rather_than_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole reason `surface` exists.

    Textual prints crash output through `error_console`, which is stderr - and under Pyodide
    stderr is a browser console the user cannot see and the developer has no reason to open.
    The app simply vanishes. The driver redirects it, so the traceback lands in the terminal
    that is already on screen.
    """
    await _CrashingApp().run_async(size=(80, 24))
    driver = active_capture()

    assert "deliberate crash" in driver.output, "traceback did not reach the terminal"
    assert "deliberate crash" not in capsys.readouterr().err, "traceback also went to stderr"
