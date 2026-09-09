"""Entry point executed inside Pyodide by `web/main.mjs`.

Sibling of `wasm_entry.py`: same reasons for being a real file rather than a string in a
template literal, and the same shape - define a coroutine, let the host call it.

The difference between the two is one line, the driver. That is the whole dual-target
claim: the page swaps the sink and the application source is untouched.
"""

from __future__ import annotations

import os
from typing import Any

BROWSER_DRIVER: str = "textual_wasm.browser:BrowserDriver"
"""Set before the first `import textual_wasm`, whose `__init__` applies the environment with
`setdefault` and so leaves a host's deliberate choice in place."""


async def start() -> Any:
    """Run the spike app against the page's terminal until it exits.

    Returns:
        Whatever the app returns; the page only reports that it finished.
    """
    os.environ["TEXTUAL_DRIVER"] = BROWSER_DRIVER

    from textual_wasm.app import SpikeApp  # noqa: PLC0415 - must follow the env write

    return await SpikeApp().run_async()
