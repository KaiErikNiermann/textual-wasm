"""The `textual-wasm` command line.

Grouped by intent rather than by implementation: `experiment` runs and compares runtimes,
`port` tells you what will break, `build` produces something you can serve.
"""

from textual_wasm.cli import experiment, port
from textual_wasm.cli._app import app

# Importing a command module is what registers its commands on the app; nothing reads the
# module objects afterwards, so they are named here to make that dependency explicit rather
# than leaving it to an import with no apparent purpose.
COMMAND_MODULES = (experiment, port)

__all__ = ["COMMAND_MODULES", "app"]
