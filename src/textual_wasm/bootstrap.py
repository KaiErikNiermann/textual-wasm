"""Environment that must be in place *before* Textual is imported.

This module deliberately imports nothing from Textual, because the ordering constraint it
encodes is the first non-obvious thing a WASM host has to get right:

`textual.constants` reads every `TEXTUAL_*` variable into module-level `Final`s at import
time — `DRIVER` is `constants.py:113`. Setting `os.environ["TEXTUAL_DRIVER"]` after anything
has imported `textual` therefore has no effect at all, silently, and the app falls back to
the platform driver and dies on `termios`. Importing `textual_wasm` applies the environment
as a package import side effect so that ordering is structurally guaranteed rather than
remembered.
"""

from __future__ import annotations

import os
from types import MappingProxyType
from typing import Final

DRIVER_IMPORT_PATH: Final[str] = "textual_wasm.driver:CaptureDriver"
"""Value for `TEXTUAL_DRIVER`; Textual imports this `module:Symbol` and checks it subclasses
`Driver` (`textual/app.py:1585`). This is the whole extension mechanism — no patch needed."""

REQUIRED_ENVIRONMENT: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        "TEXTUAL_DRIVER": DRIVER_IMPORT_PATH,
        # Rich's auto-detection reads COLORTERM/TERM, neither of which a browser or a bare
        # Node process sets, so "auto" silently degrades to 8-bit and the probe's assertion
        # about truecolor SGR would differ between runtimes for reasons unrelated to WASM.
        # xterm.js renders truecolor, so pinning it is both honest and what a real host wants.
        "TEXTUAL_COLOR_SYSTEM": "truecolor",
        # Animations make the emitted byte stream depend on wall-clock scheduling, which is
        # exactly the thing that differs between a native loop and a setTimeout-backed one.
        "TEXTUAL_ANIMATIONS": "none",
    }
)
"""Settings a host must apply before importing Textual for the WASM driver to be usable."""


def apply_environment() -> None:
    """Set the required `TEXTUAL_*` variables, without overriding a deliberate choice."""
    for name, value in REQUIRED_ENVIRONMENT.items():
        os.environ.setdefault(name, value)
