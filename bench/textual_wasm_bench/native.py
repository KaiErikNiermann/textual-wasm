"""The controls: the same apps and workloads on CPython, with no browser and no Pyodide.

Every browser number has a native counterpart measured the same way, so the ratio between
them can be read as the cost of the browser runtime and nothing else.

- Idle runs the app on Textual's own platform driver in a real pseudo-terminal, through
  `textual_wasm.reference` - the module the render check already uses as its reference, which
  removes this project's driver and keeps the rest of the environment identical.
- The workloads run in-process under `App.run_test`, calling the very methods the browser run
  triggers over the data channel.
- The channel itself is fed by a host that calls the bridge directly. That is the bridge and
  Textual's message pump with the page, the transport and the interpreter all taken out.
"""

from __future__ import annotations

import asyncio
import dataclasses
import fcntl
import os
import pty
import struct
import subprocess
import sys
import termios
import threading
import time
from collections.abc import Callable
from typing import Any, Final

import psutil

from bench_apps.probe import FLOOD, FLOOD_END, FLOOD_REPLY, BenchProbe
from bench_apps.runtime import interpreter_memory
from textual_wasm_bench import paths
from textual_wasm_bench.plan import PAGES, SITE_ENTRIES, Layer, Sizes

GRID: Final[tuple[int, int]] = (80, 24)

READY_TIMEOUT_SECONDS: Final[float] = 30.0


class _PtyReader:
    """Drain a pseudo-terminal on a thread, counting what the app wrote.

    Draining is not optional: a pty has a small buffer, and an app whose output nobody reads
    blocks on its next write - which would read as an app that is perfectly idle.
    """

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._lock = threading.Lock()
        self._received = bytearray()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                chunk = os.read(self._descriptor, 65536)
            except OSError:
                return
            if not chunk:
                return
            with self._lock:
                self._received.extend(chunk)

    @property
    def total(self) -> int:
        with self._lock:
            return len(self._received)

    def contains(self, text: str) -> bool:
        with self._lock:
            return text.encode() in self._received


def _cpu_ms(process: psutil.Process) -> float:
    """User plus system time of `process` and everything under it, in milliseconds."""
    total = 0.0
    for member in (process, *process.children(recursive=True)):
        try:
            times = member.cpu_times()
        except psutil.NoSuchProcess:
            continue
        total += times.user + times.system
    return total * 1000


def _wait_for(predicate: Callable[[], bool], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("the native app never drew its ready text")
        time.sleep(0.05)


def idle(layer: Layer, *, window_ms: int, settle_ms: int) -> dict[str, Any]:
    """CPU and output of an idle app on a real terminal, over the same window as a browser."""
    page = PAGES[layer]
    if page.site is None or page.ready_text is None:
        raise ValueError(f"{layer} is not an app layer")
    site, ready = page.site, page.ready_text
    leader, follower = pty.openpty()
    columns, rows = GRID
    fcntl.ioctl(follower, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    environment = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "PYTHONPATH": os.pathsep.join((str(paths.BENCH), os.environ.get("PYTHONPATH", ""))),
    }
    child = subprocess.Popen(  # noqa: S603 - argv is ours, no shell
        [sys.executable, "-m", "textual_wasm.reference", SITE_ENTRIES[site]],
        stdin=follower,
        stdout=follower,
        stderr=follower,
        env=environment,
        start_new_session=True,
    )
    os.close(follower)
    reader = _PtyReader(leader)
    try:
        _wait_for(lambda: reader.contains(ready), READY_TIMEOUT_SECONDS)
        time.sleep(settle_ms / 1000)
        process = psutil.Process(child.pid)
        started, cpu_before, bytes_before = time.monotonic(), _cpu_ms(process), reader.total
        time.sleep(window_ms / 1000)
        return {
            "windowMs": (time.monotonic() - started) * 1000,
            "cpuMs": _cpu_ms(process) - cpu_before,
            "characters": reader.total - bytes_before,
            "writes": None,
            "processes": 1 + len(process.children(recursive=True)),
            "mainThread": None,
        }
    finally:
        child.kill()
        child.wait()
        os.close(leader)


class _DirectHost:
    """A `BridgeHost` that is a function call: the channel with the page removed."""

    def __init__(self) -> None:
        self.deliver: Callable[[str, str], None] | None = None
        self.replies: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    def send(self, channel: str, text: str) -> None:
        self.replies.put_nowait((channel, text))

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        self.deliver = callback

    async def flood(self, count: int) -> tuple[float, int]:
        """Deliver `count` messages and the end marker; return milliseconds and the count."""
        if self.deliver is None:
            raise RuntimeError("the app has not subscribed to the host yet")
        started = time.perf_counter()
        for _ in range(count):
            self.deliver(FLOOD, "1")
        self.deliver(FLOOD_END, "")
        while True:
            channel, text = await self.replies.get()
            if channel == FLOOD_REPLY:
                return (time.perf_counter() - started) * 1000, int(text)


async def _controls(sizes: Sizes) -> dict[str, Any]:
    host = _DirectHost()
    app = BenchProbe(host=host)
    async with app.run_test(size=GRID):
        repeats = range(sizes.repeats)
        self_flood = [await app.self_flood(sizes.self_flood) for _ in repeats]
        spin = [app.spin(sizes.spin) for _ in repeats]
        churn = [await app.churn(sizes.churn) for _ in repeats]
        drains = [await host.flood(sizes.drain_messages) for _ in repeats]
        leak_churn = [dataclasses.asdict(interpreter_memory())]
        for _ in range(sizes.native_leak_rounds):
            await app.churn(sizes.leak_widgets)
            leak_churn.append(dataclasses.asdict(interpreter_memory()))
        leak_bridge = [dataclasses.asdict(interpreter_memory())]
        for _ in range(sizes.native_leak_rounds):
            await host.flood(sizes.leak_messages)
            leak_bridge.append(dataclasses.asdict(interpreter_memory()))
    return {
        "selfFlood": {"n": sizes.self_flood, "samples": self_flood},
        "spin": {"n": sizes.spin, "samples": spin},
        "churn": {"n": sizes.churn, "samples": churn},
        "drain": {
            "count": sizes.drain_messages,
            "runs": [{"totalMs": ms, "received": received} for ms, received in drains],
        },
        "leakChurn": {"perRound": sizes.leak_widgets, "interpreter": leak_churn},
        "leakBridge": {"perRound": sizes.leak_messages, "interpreter": leak_bridge},
    }


def controls(sizes: Sizes) -> dict[str, Any]:
    """Run every workload natively, in a fresh event loop."""
    return asyncio.run(_controls(sizes))
