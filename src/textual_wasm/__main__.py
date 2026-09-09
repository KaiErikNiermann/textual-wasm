"""Entry point for `python -m textual_wasm`.

The commands live in :mod:`textual_wasm.cli`; this module only starts them.
"""

from textual_wasm.cli import app

if __name__ == "__main__":
    app()
