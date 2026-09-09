"""Make Pyodide's failures legible to someone writing a Textual app.

Three jobs, in descending order of value:

* :mod:`~textual_wasm.diagnostics.guards` manufactures a failure for operations that fail
  without raising anything. This is the part with no equivalent elsewhere.
* :mod:`~textual_wasm.diagnostics.translate` rewrites the messages that misdirect, and only
  those - several of Pyodide's are better than a wrapper would produce.
* :mod:`~textual_wasm.diagnostics.surface` moves the output off stderr, which under Pyodide
  is a browser console the developer is not watching.

Typical use from a host entry point::

    from textual_wasm import diagnostics

    diagnostics.install()
    app = MyApp()
    diagnostics.attach(app, driver)
"""

from textual_wasm.diagnostics.errors import UnsupportedInWasmError, WasmCompatibilityWarning
from textual_wasm.diagnostics.guards import (
    DEFAULT_POLICIES,
    GuardPolicy,
    install,
    recorded,
    uninstall,
)
from textual_wasm.diagnostics.surface import attach, describe_recorded
from textual_wasm.diagnostics.translate import translate

__all__ = [
    "DEFAULT_POLICIES",
    "GuardPolicy",
    "UnsupportedInWasmError",
    "WasmCompatibilityWarning",
    "attach",
    "describe_recorded",
    "install",
    "recorded",
    "translate",
    "uninstall",
]
