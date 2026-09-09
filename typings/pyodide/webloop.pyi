"""Stub for `pyodide.webloop`.

Only the class, so a guard can patch the right `run_in_executor`. `WebLoop` does not inherit
`asyncio.BaseEventLoop`'s implementation - it copies one - so patching the base class alone
would silently miss the runtime the guard exists for.
"""

import asyncio

class WebLoop(asyncio.AbstractEventLoop): ...
