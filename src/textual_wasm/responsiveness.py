"""Measure what running the interpreter in a Web Worker actually buys.

Separate from :mod:`textual_wasm.check` because it answers a different question. `check` asks
whether a build renders correctly - the same cells as a real terminal, on every runtime. This
asks whether the page is still alive while the application is thinking, which is the only
reason to prefer a worker build and is invisible to a cell-by-cell comparison.

The metric is the longest interval between two animation frames on the main thread while the
application is busy. A frame *count* is the tempting measure and the wrong one: sampling for
longer than the blocking call dilutes the freeze into an average that looks fine, which is
how a real 350ms stall first read here as "340 frames rendered, responsive". The longest gap
has no such window sensitivity - it is the length of the freeze, whatever else happened.
"""

from __future__ import annotations

import dataclasses
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

from textual_wasm import node
from textual_wasm.bundler import BuildSpec, background_server
from textual_wasm.bundler import build as build_site
from textual_wasm.driver import DEFAULT_SIZE

if TYPE_CHECKING:
    from textual_wasm.target import AppTarget

_log: Final = logging.getLogger(__name__)

HARNESS: Final[str] = "responsiveness.mjs"

FROZEN_THRESHOLD_MS: Final[float] = 100.0
"""Above this, a gap between frames is a visible stall rather than a slow frame.

Six frames at 60Hz. The exact number matters little because the two modes are not close -
measured on the same app, a worker build's worst gap is one frame and a main-thread build's
is the entire length of the blocking call.
"""


@dataclasses.dataclass(frozen=True, slots=True)
class Responsiveness:
    """What the main thread managed to do while the application blocked."""

    worker: bool
    """Whether the build under measurement ran Python off the main thread."""

    longest_gap_ms: float | None
    """The longest interval between two animation frames, or None if none were rendered.

    This is the length of the worst freeze, and the number the claim rests on. None is the
    extreme case rather than a missing measurement: the thread never ran at all."""

    frames: int
    """Animation frames rendered during the window. Context for the gap, not a verdict -
    a long window mostly spent idle produces a healthy-looking count around a real stall."""

    blocked_ms: float
    """Wall-clock length of the sampling window."""

    @property
    def responsive(self) -> bool:
        """Whether the page kept up while Python was busy."""
        return self.longest_gap_ms is not None and self.longest_gap_ms < FROZEN_THRESHOLD_MS


def measure(
    target: AppTarget,
    *,
    worker: bool,
    keys: str,
    size: tuple[int, int] = DEFAULT_SIZE,
) -> Responsiveness:
    """Build `target`, drive it in a browser, and count frames while it blocks.

    Args:
        target: An application with a key binding that blocks the interpreter.
        worker: Whether to build the page that runs Python in a Web Worker.
        keys: The keystrokes that trigger the blocking call.
        size: The grid the page is forced to.

    Returns:
        The frame count and the window it was measured over.

    Raises:
        RuntimeError: If Node or Playwright is missing, since an unmeasured claim is the
            thing this module exists to prevent and a silent skip would be one.
    """
    available = node.availability([node.PLAYWRIGHT_PACKAGE])
    if not available.available or available.node is None or available.resolve_from is None:
        raise RuntimeError(f"{available.reason} {node.BROWSER_HINT}")

    with tempfile.TemporaryDirectory(prefix="textual-wasm-responsiveness-") as directory:
        built = build_site(
            BuildSpec(
                entry=target.entry,
                package=target.package_directory(),
                output=Path(directory),
                worker=worker,
            )
        )
        _log.debug("built %s for the responsiveness measurement", built.summary)
        with background_server(Path(directory)) as url:
            result = node.run_harness(
                HARNESS,
                {
                    "resolveFrom": str(available.resolve_from),
                    "url": url,
                    "columns": size[0],
                    "rows": size[1],
                    "keys": keys,
                    "worker": worker,
                    "target": {
                        "entry": target.entry,
                        "ready_marker": target.ready_marker,
                    },
                },
                node=available.node,
            )

    return _from_payload(result.payload, worker=worker)


def _number(payload: dict[str, object], key: str) -> float:
    """Read a numeric field, naming the harness rather than the type system if it is absent.

    Raises:
        HarnessError: If the field is missing or is not a number. A harness that changed
            shape should say so here, not produce a `TypeError` three frames deeper.
    """
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise node.HarnessError(f"harness payload has no numeric {key!r}: {value!r}")
    return float(value)


def _from_payload(payload: dict[str, object], *, worker: bool) -> Responsiveness:
    """Build a result from a harness payload."""
    gap = payload.get("longestGapMs")
    return Responsiveness(
        worker=worker,
        frames=int(_number(payload, "frames")),
        longest_gap_ms=None if gap is None else _number(payload, "longestGapMs"),
        blocked_ms=_number(payload, "blockedMs"),
    )
