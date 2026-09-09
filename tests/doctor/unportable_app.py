"""An application that cannot run under Pyodide, for the doctor to find problems in.

Deliberately broken, and excluded from ruff and pyright the same way
`tests/semgrep/positive` is. Every line here is a planted finding; `tests/test_doctor.py`
asserts each one is reported, because a checker that silently stops matching is
indistinguishable from a clean codebase.
"""

import curses
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def sync() -> None:
    os.system("rsync -a src/ dst/")
    time.sleep(2)
    threading.Thread(target=sync).start()
    ThreadPoolExecutor().submit(sync)
    curses.initscr()


def harmless() -> None:
    # The yield idiom. The runtime guard lets this through, so the scanner must too.
    time.sleep(0)
