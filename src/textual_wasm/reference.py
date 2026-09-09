"""Run any Textual app on the platform driver, for :mod:`textual_wasm.terminal` to capture.

    python -m textual_wasm.reference myapp:App

The only entry point in this project that deliberately selects a driver this project did not
write. That is the point: the render reference has to be Textual behaving normally on a tty,
with nothing from the WASM work in the path, or it is not a reference.

Importing this package sets `TEXTUAL_DRIVER` to the capture driver, so the first thing here
is to remove it again and let `App.get_driver_class` choose for the platform - which is why
`bootstrap.apply_environment` uses `setdefault` rather than assignment. Removing rather than
naming `LinuxDriver` keeps the reference correct on any host Textual supports. The rest of
the environment (no animations, forced truecolor) is left in place: it is what makes two
captures of the same app comparable at all.

A module rather than a script under `scripts/`, so it is available wherever the package is
installed - a user checking their own app has no checkout to run a script from.
"""

from __future__ import annotations

import os
import sys

from textual_wasm.target import SPIKE_ENTRY, AppTarget

DRIVER_VARIABLE: str = "TEXTUAL_DRIVER"

PLATFORM_DRIVER_LABEL: str = "textual platform default (TEXTUAL_DRIVER unset)"
"""What a capture records about which driver produced it."""


def main(argv: list[str]) -> None:
    """Run the named app until it exits.

    Args:
        argv: The process argv; `argv[1]` is a `module:AppClass` reference, defaulting to
            the bundled demo.
    """
    os.environ.pop(DRIVER_VARIABLE, None)

    target = AppTarget(entry=argv[1] if len(argv) > 1 else SPIKE_ENTRY)
    target.load()().run()


if __name__ == "__main__":
    main(sys.argv)
