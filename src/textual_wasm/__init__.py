"""Feasibility spike for running Textual fully client-side under WebAssembly.

The package core contains no runtime-specific branching: the same
:func:`textual_wasm.probe.run_probe` coroutine is executed by the native CLI and by the
Pyodide harness, and any divergence between the two reports is the finding.

Importing this package applies :data:`textual_wasm.bootstrap.REQUIRED_ENVIRONMENT`. That has
to happen before the first `import textual` anywhere in the process — see
:mod:`textual_wasm.bootstrap` for why — and a package `__init__` is the only place that can
be guaranteed to run before its own submodules.
"""

from textual_wasm.bootstrap import DRIVER_IMPORT_PATH, REQUIRED_ENVIRONMENT, apply_environment

apply_environment()

from textual_wasm.report import (  # noqa: E402 - must follow apply_environment()
    CheckId,
    CheckResult,
    CheckStatus,
    ProbeReport,
    RuntimeFacts,
)

__all__ = [
    "DRIVER_IMPORT_PATH",
    "REQUIRED_ENVIRONMENT",
    "CheckId",
    "CheckResult",
    "CheckStatus",
    "ProbeReport",
    "RuntimeFacts",
    "apply_environment",
]
