"""Re-measure every claim in the substitution registry, inside Pyodide.

The registry asserts what Pyodide does. Pyodide changes. Without this the registry decays
into folklore, and the failure mode is the one that motivated the module in the first place:
documentation that is confidently wrong. Pyodide's own removed-modules list is stale for
314.0.6, which is exactly what happens when nobody re-runs the claims.

Emits `{id: {raised, type, message}}` so a test can compare reality against the registry's
`severity` and `native_message` rather than trusting either.
"""

from __future__ import annotations

import json
from typing import Any


async def run() -> str:
    """Execute every probeable substitution and report what actually happened.

    Returns:
        JSON mapping substitution id to the observed outcome.
    """
    from textual_wasm.substitutions import PROBEABLE  # noqa: PLC0415 - after env bootstrap

    observations: dict[str, dict[str, Any]] = {}
    for substitution in PROBEABLE:
        assert substitution.probe is not None  # PROBEABLE is filtered on it  # noqa: S101
        try:
            # The probes are literals from this project's own registry, not user input, and
            # running them is the entire point: a claim nobody re-executes is a claim nobody
            # can trust.
            exec(substitution.probe, {})  # noqa: S102
        except BaseException as error:
            observations[substitution.id] = {
                "raised": True,
                "type": type(error).__name__,
                "message": str(error),
            }
        else:
            observations[substitution.id] = {"raised": False, "type": None, "message": None}
    return json.dumps(observations)
