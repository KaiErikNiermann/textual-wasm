"""Deliberately non-compliant code: every rule in `.semgrep/` must flag something here.

Mirrors the real module path because several rules are scoped with `paths.include`.
Excluded from ruff, pyright and the project semgrep run - see `tests/semgrep/README.md`.
"""

import os
import sys
from datetime import datetime

from textual_wasm.polyfills import IS_EMSCRIPTEN


def bad() -> None:
    if sys.platform == "emscripten":
        pass
    if IS_EMSCRIPTEN:
        pass
    os.environ["TEXTUAL_DRIVER"] = "textual_wasm.driver:CaptureDriver"
    requirements = ["textual==8.2.8", "rich==15.0.0"]
    app = object()
    driver = app._driver
    driver._frames.append("x")
    print(datetime.now())
    out = []
    for item in requirements:
        out.append(item)
    try:
        bad()
    except ValueError:
        pass


def more_bad() -> dict:
    os.environ["TEXTUAL_COLOR_SYSTEM"] = "truecolor"
    os.environ.setdefault("TEXTUAL_FPS", "30")
    os.environ.pop("TEXTUAL_ANIMATIONS", None)
    del os.environ["TEXTUAL_DRIVER"]
    stamp = datetime.utcnow()
    collected = []
    for value in (1, 2, 3):
        collected.append(value)
    return {"stamp": stamp, "collected": collected}
