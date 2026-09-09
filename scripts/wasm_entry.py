"""Entry point executed inside Pyodide by `scripts/run-pyodide-node.mjs`.

A real file rather than a string embedded in the harness: as a JavaScript template literal
this code could not be linted, type-checked or syntax-highlighted, and `f"{X}"` inside one
reads to ESLint as a botched `${X}` interpolation.
"""

from __future__ import annotations

import sys


async def run(mount_point: str) -> str:
    """Import the spike from `mount_point`, run the probe, and return a delimited report.

    Args:
        mount_point: Where the harness mounted the project's `src/` directory.

    Returns:
        The report's JSON, wrapped in the sentinel so stray runtime output on stdout cannot
        be mistaken for it.
    """
    if mount_point not in sys.path:
        sys.path.insert(0, mount_point)

    # The first import of `textual_wasm` applies the TEXTUAL_* environment, which has to
    # happen before anything imports textual. Deferred to here, rather than module scope,
    # so that this file can be imported natively for linting without that side effect.
    from textual_wasm.probe import run_probe  # noqa: PLC0415
    from textual_wasm.report import REPORT_SENTINEL  # noqa: PLC0415

    report = await run_probe()
    return f"{REPORT_SENTINEL}{report.to_json(indent=None)}{REPORT_SENTINEL}"
