"""Feasibility spike for running Textual fully client-side under WebAssembly.

The package core contains no runtime-specific branching: the same
:func:`textual_wasm.probe.run_probe` coroutine is executed by the native CLI and by the
Pyodide harness, and any divergence between the two reports is the finding.

Importing this package applies :data:`textual_wasm.bootstrap.REQUIRED_ENVIRONMENT` and any
runtime shim :mod:`textual_wasm.polyfills` finds necessary. That has
to happen before the first `import textual` anywhere in the process — see
:mod:`textual_wasm.bootstrap` for why — and a package `__init__` is the only place that can
be guaranteed to run before its own submodules.
"""

from textual_wasm.bootstrap import (
    DRIVER_IMPORT_PATH,
    REQUIRED_ENVIRONMENT,
    apply_environment,
    apply_tree_sitter_shim,
)
from textual_wasm.polyfills import IS_EMSCRIPTEN, apply_polyfills

apply_environment()
# Same ordering constraint, same reason: the module that looks for `QueryCursor` caches the
# answer at import time, so the name has to exist before Textual is first imported. The
# result is kept rather than discarded because `capabilities` reports it.
TREE_SITTER_SHIM = apply_tree_sitter_shim()
APPLIED_POLYFILLS = apply_polyfills()
"""Runtime shims this process needed; surfaced in the probe report."""

from textual_wasm.report import (  # noqa: E402 - must follow apply_environment()
    CheckId,
    CheckResult,
    CheckStatus,
    ProbeReport,
    RuntimeFacts,
)

__all__ = [
    "APPLIED_POLYFILLS",
    "DRIVER_IMPORT_PATH",
    "IS_EMSCRIPTEN",
    "REQUIRED_ENVIRONMENT",
    "TREE_SITTER_SHIM",
    "CheckId",
    "CheckResult",
    "CheckStatus",
    "ProbeReport",
    "RuntimeFacts",
    "apply_environment",
    "apply_polyfills",
    "apply_tree_sitter_shim",
]
