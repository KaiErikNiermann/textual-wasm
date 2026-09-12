"""An application that cannot run under Pyodide, for the doctor to find problems in.

Deliberately broken, and excluded from ruff and pyright the same way
`tests/semgrep/positive` is. Every line here is a planted finding; `tests/test_doctor.py`
asserts each one is reported, because a checker that silently stops matching is
indistinguishable from a clean codebase.
"""

import array
import curses
import fcntl
import http.server
import os
import pty
import socketserver
import sys
import termios
import threading
import time
import tty
from concurrent.futures import ThreadPoolExecutor


def sync() -> None:
    os.system("rsync -a src/ dst/")
    time.sleep(2)
    threading.Thread(target=sync).start()
    ThreadPoolExecutor().submit(sync)
    curses.initscr()


def ask_the_terminal() -> None:
    """The shape that hangs rather than fails: set cbreak, query, wait for a reply."""
    tty.setcbreak(sys.stdin)
    tty.setraw(sys.stdin)
    termios.tcsetattr(sys.stdin, termios.TCSANOW, termios.tcgetattr(sys.stdin))
    fcntl.ioctl(sys.stdout, termios.TIOCGWINSZ, array.array("H", [0, 0, 0, 0]))


def drive_a_child() -> None:
    pty.openpty()
    pty.spawn(["vim"])


def serve() -> None:
    """Silently fine under Node, refused in a browser - the divergence that misleads."""
    socketserver.TCPServer(("127.0.0.1", 8000), socketserver.BaseRequestHandler)
    http.server.HTTPServer(("127.0.0.1", 8001), http.server.BaseHTTPRequestHandler)


def harmless() -> None:
    # The yield idiom. The runtime guard lets this through, so the scanner must too.
    time.sleep(0)
