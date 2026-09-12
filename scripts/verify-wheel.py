#!/usr/bin/env python
"""Assert the built wheel carries the files that are not Python.

The page, its stylesheet, the browser entry script and the two JavaScript harnesses are
load-bearing: without them ``build`` writes an empty site and ``check`` has no wasm or
browser leg. Neither is importable, so nothing else notices when a packaging change drops
them - the wheel just gets quietly smaller.

Run after ``poetry build``; called by both the ``build-verify`` recipe and the release
workflow, so the list of required paths exists once.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

# Relative to the wheel root, which is the distribution's top-level package directory.
REQUIRED: tuple[str, ...] = (
    "textual_wasm/assets/index.html",
    "textual_wasm/assets/main.mjs",
    "textual_wasm/assets/entry.py",
    "textual_wasm/harness/pyodide-probe.mjs",
    "textual_wasm/harness/browser-check.mjs",
    "textual_wasm/harness/wasm_entry.py",
)


def main(argv: tuple[str, ...]) -> int:
    """Report whether the newest wheel under ``dist/`` (or ``argv[0]``) is complete."""
    if argv:
        wheel = Path(argv[0])
    else:
        wheels = sorted(Path("dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
        if not wheels:
            print("error: no wheel in dist/; run `poetry build` first", file=sys.stderr)
            return 1
        wheel = wheels[-1]

    with zipfile.ZipFile(wheel) as archive:
        names = frozenset(archive.namelist())

    if missing := [name for name in REQUIRED if name not in names]:
        print(f"error: {wheel.name} is missing:", file=sys.stderr)
        for name in missing:
            print(f"  {name}", file=sys.stderr)
        return 1

    print(f"{wheel.name}: {len(names)} files, all required assets present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))
