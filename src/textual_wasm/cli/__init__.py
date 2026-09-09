"""The `textual-wasm` command line.

Grouped by intent rather than by implementation: `check` runs one app on every runtime and
compares them, `experiment` exposes the individual legs that make that up, `port` tells you
what will break, and `build` produces something you can serve.
"""

from textual_wasm.cli import build, check, experiment, port
from textual_wasm.cli._app import app

# Importing a command module is what registers its commands on the app; nothing reads the
# module objects afterwards, so they are named here to make that dependency explicit rather
# than leaving it to an import with no apparent purpose.
COMMAND_MODULES = (build, check, experiment, port)

__all__ = ["COMMAND_MODULES", "app"]
