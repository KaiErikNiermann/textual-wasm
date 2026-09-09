"""Run the spike app on a real terminal, for `textual_wasm.terminal` to capture.

Sibling of `wasm_entry.py` and `browser_entry.py`, and the only one that selects a driver
this project did not write. That is the point: the reference has to be Textual behaving
normally on a tty, with nothing from the WASM work in the path, or it is not a reference.
"""

from __future__ import annotations

import os

PLATFORM_DRIVER: str = "textual.drivers.linux_driver:LinuxDriver"
"""Textual's own Linux driver, named explicitly.

`get_driver_class` would pick it anyway, but only if `TEXTUAL_DRIVER` is unset - and
importing this project sets it. Naming the platform driver is how the reference run opts
back out; `bootstrap.apply_environment` uses `setdefault` precisely so a host can.
"""


def main() -> None:
    """Run the app until the user quits it."""
    os.environ["TEXTUAL_DRIVER"] = PLATFORM_DRIVER

    from textual_wasm.app import SpikeApp  # noqa: PLC0415 - must follow the env write

    SpikeApp().run()


if __name__ == "__main__":
    main()
