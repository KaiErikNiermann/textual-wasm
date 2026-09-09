"""Start any Textual app under a browser driver.

Shipped as an asset rather than imported, because it has to run before `textual` is imported
by anything: `textual.constants` reads every TEXTUAL_* variable into module-level constants at
import time, so a driver chosen afterwards is silently ignored.

The page fetches this, runs it, and calls `start("package.module:AppClass")`.
"""

from __future__ import annotations

import os
from typing import Any

BROWSER_DRIVER: str = "textual_wasm.browser:BrowserDriver"
"""Set before the first `import textual_wasm`, whose bootstrap uses `setdefault` and so
leaves a host's deliberate choice in place."""


def _load(entry: str) -> Any:
    """Resolve a `package.module:Attribute` reference.

    Raises:
        ValueError: If the reference has no colon, which is the mistake people make.
    """
    module_name, separator, attribute = entry.partition(":")
    if not separator:
        raise ValueError(f"expected 'module:AppClass', got {entry!r}")
    import importlib  # noqa: PLC0415 - must follow the environment write in start()

    return getattr(importlib.import_module(module_name), attribute)


async def start(entry: str) -> Any:
    """Run the named app against the page's terminal until it exits.

    Args:
        entry: A `module:AppClass` reference, from the build manifest.

    Returns:
        Whatever the app's `run_async` returns.
    """
    os.environ["TEXTUAL_DRIVER"] = BROWSER_DRIVER

    from textual_wasm import diagnostics  # noqa: PLC0415 - must follow the env write

    # Guards only. The driver attaches the error surface itself when it takes the terminal,
    # because routing crash output away from a browser console nobody reads is not something
    # a host should have to remember.
    diagnostics.install()
    return await _load(entry)().run_async()
