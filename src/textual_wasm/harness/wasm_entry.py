"""Entry point executed inside Pyodide by `pyodide-probe.mjs`.

A real file rather than a string embedded in the harness: as a JavaScript template literal
this code could not be linted, type-checked or syntax-highlighted, and `f"{X}"` inside one
reads to ESLint as a botched `${X}` interpolation.

It receives the harness's whole configuration as JSON and validates it here, at the boundary
where it arrives, rather than trusting positional arguments marshalled through the FFI.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any, cast


def _search_path(config: Mapping[str, Any]) -> list[str]:
    """Directories to put on `sys.path`, in order.

    Separate from the mount list because the two are not the same thing: each package is
    mounted at its own point, and what goes on the path is the directory those points sit
    in. Mounting a whole `site-packages` instead would shadow the wheels Pyodide installed.

    Raises:
        TypeError: If the harness sent something other than a list. This crosses an FFI
            boundary, so its shape is checked rather than assumed.
    """
    entries: object = config.get("sys_path", [])
    if not isinstance(entries, list):
        raise TypeError(f"'sys_path' must be an array, got {type(entries).__name__}")
    return [str(entry) for entry in cast("list[object]", entries)]


async def run(config_json: str) -> str:
    """Import the app from the mounted sources, probe it, and return a delimited report.

    Args:
        config_json: The harness configuration, as written by `textual_wasm.node`.

    Returns:
        The report's JSON, wrapped in the sentinel so stray runtime output on stdout cannot
        be mistaken for it.
    """
    config: dict[str, Any] = json.loads(config_json)
    for entry in reversed(_search_path(config)):
        if entry not in sys.path:
            sys.path.insert(0, entry)

    # The first import of `textual_wasm` applies the TEXTUAL_* environment, which has to
    # happen before anything imports textual. Deferred to here, rather than module scope,
    # so that this file can be imported natively for linting without that side effect.
    from textual_wasm.probe import run_probe  # noqa: PLC0415
    from textual_wasm.report import REPORT_SENTINEL  # noqa: PLC0415
    from textual_wasm.target import AppTarget  # noqa: PLC0415

    report = await run_probe(
        target=AppTarget.from_mapping(config["target"]),
        size=(int(config["columns"]), int(config["rows"])),
    )
    return f"{REPORT_SENTINEL}{report.to_json(indent=None)}{REPORT_SENTINEL}"
