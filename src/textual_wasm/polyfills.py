"""Host-side shims for defects in the WASM runtime itself, applied before Textual is imported.

Nothing here compensates for anything Textual does. Each entry is a bug in the runtime that
would otherwise be misattributed to Textual, and each is recorded in the probe report so a
WASM run can never look accidentally identical to a native one.
"""

from __future__ import annotations

import asyncio.tasks
import sys
from typing import Any, Final

IS_EMSCRIPTEN: Final[bool] = sys.platform == "emscripten"
"""True inside Pyodide/pygbag. `sys.platform` is the runtime's own answer, not a guess."""

_SET_TASK_NAME: Final[str] = "_set_task_name"


def _set_task_name(task: Any, name: str | None) -> None:
    """Reinstate the private helper CPython 3.14 removed.

    Faithful to the 3.13 implementation for the only case that can occur here: `Task` always
    provides `set_name`, so the `AttributeError` warning branch of the original is dead code.
    """
    if name is not None:
        task.set_name(name)


def apply_polyfills() -> tuple[str, ...]:
    """Install runtime shims, returning the name of each one actually applied.

    Returns:
        Identifiers for the shims that were needed, empty on a healthy runtime.

    Every shim is gated on the runtime that actually needs it. Native CPython 3.14 has also
    dropped `_set_task_name`, but nothing native calls it, so installing it there would put a
    line in the report that does not correspond to a real defect.
    """
    applied: list[str] = []
    if IS_EMSCRIPTEN and not hasattr(asyncio.tasks, _SET_TASK_NAME):
        # Pyodide 314.0.6 ships CPython 3.14 but its `WebLoop.create_task` is a copy of
        # CPython 3.13's `BaseEventLoop.create_task`, whose task-factory branch calls
        # `asyncio.tasks._set_task_name` - removed in 3.14. The branch is taken only once a
        # factory is set, and `App.run_async` sets one unconditionally
        # (`asyncio.eager_task_factory`, textual/app.py:2283), so under Pyodide every
        # `loop.create_task` after the app starts raises AttributeError.
        #
        # Restoring the helper is the minimal correct fix: it is a private stdlib symbol the
        # runtime believes exists, so nothing else can be relying on its absence. The
        # alternative - clearing the task factory behind Textual's back - would silently
        # change task semantics for the thing under test.
        asyncio.tasks._set_task_name = _set_task_name  # type: ignore[attr-defined]
        applied.append("asyncio.tasks._set_task_name")
    return tuple(applied)
