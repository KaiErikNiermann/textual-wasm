"""micropip's install failures, rewritten into something that names the actual cause.

The message that motivated this is actively misleading rather than merely terse. "Can't find
a pure Python 3 wheel for tree-sitter>=0.25.0" reads as "nobody has built this for
WebAssembly", when the truth in the case that produced it is the opposite: Pyodide *has*
built it, and bundles 0.23.2, which the pin excludes. The two causes have different fixes and
the message distinguishes neither.

The assertions live in a JavaScript harness because the function does, and running it under
Node is the only honest way to test it. Skipped, with its reason, where Node is absent - the
same treatment every other optional leg gets.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Final

import pytest

from textual_wasm import node

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
HARNESS: Final[Path] = PROJECT_ROOT / "src" / "textual_wasm" / "harness" / "install-errors.mjs"
NODE: Final[node.NodeAvailability] = node.availability([], start=PROJECT_ROOT)
"""No npm packages: the harness imports one relative module and needs nothing installed.

So the gate is `node.node`, not `node.available` - the latter is False whenever no packages
were asked for, since there is then no `node_modules` to resolve against.
"""


@pytest.mark.skipif(NODE.node is None, reason="node is not on PATH")
def test_every_micropip_failure_shape_is_rewritten() -> None:
    """Runs the harness; its own assertions are the test, and a non-zero exit is the failure."""
    assert NODE.node is not None  # guarded by the marker
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, path is ours
        [NODE.node, str(HARNESS)],
        capture_output=True,
        text=True,
        check=False,
        cwd=PROJECT_ROOT,
    )
    payload = json.loads(completed.stdout.strip().splitlines()[0])
    assert payload["failures"] == [], payload["failures"]
    assert payload["checked"] >= 4
    assert completed.returncode == 0, completed.stderr[-600:]


def test_the_harness_ships_with_the_package() -> None:
    """It is under `src/`, so a wheel that omitted it would take the check with it."""
    assert HARNESS.exists()
