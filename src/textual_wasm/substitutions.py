"""What breaks under Pyodide, what it looks like when it does, and what to do instead.

The single source of truth for three things that would otherwise drift apart: the static
analyser's rules, the messages raised at runtime, and the porting table in the documentation.
Each is a rendering of this registry rather than a separately maintained list.

Every claim here was measured against Pyodide 314.0.6, not transcribed. That distinction is
load-bearing: Pyodide's own documentation lists `termios`, `fcntl`, `pty` and `tty` as removed
modules, and in 314.0.6 all four import successfully. A rule set copied from those docs is
wrong on arrival, so each entry carries the snippet used to observe it and is pinned by a
characterisation test that fails when the runtime changes underneath it.

The severity taxonomy is ordered by how hard the failure is to diagnose, not by how severe it
sounds. `SILENT_WRONG` is first because a wrong answer with no error is worse than a crash,
and it is the class Pyodide's documentation does not cover at all.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Final


class Severity(enum.StrEnum):
    """How a capability fails, from the point of view of someone debugging it."""

    SILENT_WRONG = "silent_wrong"
    """No exception, wrong behaviour. The dangerous class and the reason this module exists."""

    FATAL = "fatal"
    """Tears down the interpreter; nothing can catch it or report it afterwards."""

    LOUD_UNCLEAR = "loud_unclear"
    """Raises, but the message misdirects - names a symptom, a private module, or a generic
    errno rather than the actual constraint."""

    LOUD_CLEAR = "loud_clear"
    """Raises with a message that already says what is wrong and often how to fix it.

    Recorded so the runtime translator knows to leave it alone: replacing a good message with
    a generic one would be a regression, and several of Pyodide's are genuinely good.
    """

    UNSUPPORTED = "unsupported"
    """The module is absent, so the failure is an ordinary ImportError at the import site."""


class DetectionKind(enum.StrEnum):
    """How the static analyser recognises a use of the capability."""

    IMPORT = "import"
    """A module name, matched against the app's import graph."""

    CALL = "call"
    """A dotted call target, e.g. `os.system`. Catches the silent class, which import
    scanning cannot see because the module itself is fine."""


@dataclasses.dataclass(frozen=True, slots=True)
class DetectionRule:
    """One way a substitution can be spotted in source code."""

    kind: DetectionKind
    target: str


@dataclasses.dataclass(frozen=True, slots=True)
class Substitution:
    """One capability that behaves differently under Pyodide."""

    id: str
    severity: Severity
    detect: tuple[DetectionRule, ...]

    observed: str
    """What actually happens, measured. Present tense, specific."""

    guidance: str
    """What to do instead. The text a developer sees, so it names the replacement API."""

    native_message: str | None = None
    """Pyodide's own message, verbatim, or None when nothing is raised.

    Verbatim matters: the runtime translator matches on this text, so paraphrasing it here
    silently disables the translation.
    """

    probe: str | None = None
    """Python that provokes the behaviour, used by the characterisation tests.

    None where provoking it is destructive (it would kill the interpreter) or needs a browser.
    """

    env_divergent: bool = False
    """True when Node and a browser disagree.

    Orthogonal to severity rather than a value of it, because the interesting cases are both:
    `os.system` raises nothing in either, works in Node, and silently does nothing in a
    browser. Anything marked here must be verified in both runtimes - Node-only validation
    has already produced false confidence twice.
    """

    reference: str | None = None


_PYODIDE_DOCS: Final[str] = "https://pyodide.org/en/stable/usage/wasm-constraints.html"

SUBSTITUTIONS: Final[tuple[Substitution, ...]] = (
    # --- SILENT_WRONG: no exception, wrong behaviour -------------------------------------
    Substitution(
        id="asyncio.run_in_executor",
        severity=Severity.SILENT_WRONG,
        detect=(DetectionRule(DetectionKind.CALL, "run_in_executor"),),
        observed=(
            "Returns the correct result, but Pyodide's WebLoop ignores the executor and runs "
            "the callable inline on the only thread. Code written to keep a UI responsive "
            "freezes the page instead."
        ),
        guidance=(
            "There is no thread to offload to. Make the work a coroutine and await it, or "
            "break it into chunks that yield with `await asyncio.sleep(0)` between them."
        ),
        probe="import asyncio; asyncio.get_event_loop().run_in_executor(None, lambda: 1)",
    ),
    Substitution(
        id="time.sleep",
        severity=Severity.SILENT_WRONG,
        detect=(DetectionRule(DetectionKind.CALL, "time.sleep"),),
        observed=(
            "Blocks for the full duration on the only thread. In a browser the tab stops "
            "rendering, stops handling input and stops running timers for that period."
        ),
        guidance="Use `await asyncio.sleep(...)`, which yields to the event loop.",
        probe="import time; time.sleep(0.05)",
    ),
    Substitution(
        id="socket.connect",
        severity=Severity.SILENT_WRONG,
        detect=(DetectionRule(DetectionKind.CALL, "socket.socket"),),
        observed=(
            "`socket()` and `connect()` both succeed and return None. Emscripten backs "
            "sockets with WebSockets, so a send appears to work and the first recv hangs "
            "until the timeout - or forever, if none is set."
        ),
        guidance=(
            "Raw TCP does not exist in a browser. Use `pyodide.http.pyfetch` for async HTTP, "
            "or `requests`/`httpx`, which Pyodide patches to route through fetch."
        ),
        probe=None,
        env_divergent=True,
        reference="https://pyodide.org/en/stable/usage/socket.html",
    ),
    Substitution(
        id="os.kill.suspend",
        severity=Severity.SILENT_WRONG,
        detect=(DetectionRule(DetectionKind.CALL, "os.kill"),),
        observed="`os.kill(pid, SIGTSTP)` returns None and does nothing; the app is not suspended.",
        guidance=(
            "There is no job control. Textual gates this behind `Driver.can_suspend`, which "
            "the WASM driver reports as False."
        ),
        probe="import os, signal; os.kill(os.getpid(), signal.SIGTSTP)",
    ),
    # --- FATAL --------------------------------------------------------------------------
    Substitution(
        id="os.kill.terminate",
        severity=Severity.FATAL,
        detect=(DetectionRule(DetectionKind.CALL, "os.kill"),),
        observed=(
            "`os.kill(pid, SIGKILL)` tears the runtime down with a JS exit object carrying "
            "`pyodide_fatal_error: true`. It is not a Python exception, nothing can catch it, "
            "and the interpreter is unusable afterwards."
        ),
        guidance="Exit through `App.exit()` so Textual can shut down and restore the terminal.",
        probe=None,
    ),
    # --- LOUD_UNCLEAR: raises, but misdirects -------------------------------------------
    Substitution(
        id="threading.thread",
        severity=Severity.LOUD_UNCLEAR,
        detect=(
            DetectionRule(DetectionKind.IMPORT, "threading"),
            DetectionRule(DetectionKind.CALL, "threading.Thread"),
        ),
        observed=(
            "Constructing a Thread succeeds; `.start()` raises. The message reads as a "
            "transient resource limit, but this build has no pthreads at all - "
            "`sys._emscripten_info.pthreads` is False and cannot be turned on by any header "
            "or flag."
        ),
        guidance=(
            "Use asyncio. In Textual specifically, `@work` (async) works and "
            "`@work(thread=True)` cannot."
        ),
        native_message="can't start new thread",
        probe="import threading; threading.Thread(target=lambda: None).start()",
    ),
    Substitution(
        id="concurrent.thread_pool",
        severity=Severity.LOUD_UNCLEAR,
        detect=(DetectionRule(DetectionKind.CALL, "ThreadPoolExecutor"),),
        observed=(
            "The constructor succeeds and the failure is deferred to the first `submit()`, "
            "buried under `_adjust_thread_count`, so the traceback points away from the "
            "caller."
        ),
        guidance="Same as `threading.thread`: there are no threads. Use asyncio.",
        native_message="can't start new thread",
        probe=("import concurrent.futures as f; f.ThreadPoolExecutor().submit(lambda: 1).result()"),
    ),
    Substitution(
        id="multiprocessing.process",
        severity=Severity.LOUD_UNCLEAR,
        detect=(DetectionRule(DetectionKind.IMPORT, "multiprocessing"),),
        observed=(
            "`import multiprocessing` and `Process(...)` both succeed; `.start()` fails with "
            "a private C module name leaking through a six-frame import chain."
        ),
        guidance="There are no processes and no threads. The work has to happen inline.",
        native_message="No module named '_multiprocessing'",
        probe="import multiprocessing; multiprocessing.Process(target=lambda: None).start()",
    ),
    Substitution(
        id="os.fork",
        severity=Severity.LOUD_UNCLEAR,
        detect=(DetectionRule(DetectionKind.CALL, "os.fork"),),
        observed="A bare ENOSYS with no mention of fork, WebAssembly or Pyodide.",
        guidance="WebAssembly has no process model. There is nothing to substitute.",
        native_message="[Errno 52] Function not implemented",
        probe="import os; os.fork()",
    ),
    Substitution(
        id="urllib.tls",
        severity=Severity.LOUD_UNCLEAR,
        detect=(DetectionRule(DetectionKind.CALL, "urllib.request.urlopen"),),
        observed=(
            "Accurate but unhelpful, and buried under roughly forty traceback frames. "
            "Pyodide ships an `ssl` stub with no OpenSSL behind it."
        ),
        guidance=(
            "Use `pyodide.http.pyfetch` (async), or `requests`/`httpx` - Pyodide patches both "
            "to route through fetch, so they work unmodified in a browser."
        ),
        native_message="TLS not supported in this environment",
        probe="import urllib.request; urllib.request.urlopen('https://example.com')",
    ),
    Substitution(
        id="os.get_terminal_size",
        severity=Severity.LOUD_UNCLEAR,
        detect=(DetectionRule(DetectionKind.CALL, "os.get_terminal_size"),),
        observed=(
            "Raises, because stdin is not a tty. Note the errno: Emscripten uses its own "
            "table, so this is 59 rather than the familiar 25."
        ),
        guidance=(
            "Use `shutil.get_terminal_size()`, which falls back to COLUMNS/LINES and then to "
            "80x24. textual-wasm's host preset sets those from the terminal element."
        ),
        native_message="[Errno 59] Not a tty",
        probe="import os; os.get_terminal_size()",
    ),
    Substitution(
        id="stdin.read",
        severity=Severity.LOUD_UNCLEAR,
        detect=(
            DetectionRule(DetectionKind.CALL, "input"),
            DetectionRule(DetectionKind.CALL, "getpass.getpass"),
        ),
        observed=(
            "With no stdin handler installed, reads hit EOF immediately. In a browser the "
            "default handler is `window.prompt`, so `getpass` would echo the secret."
        ),
        guidance=(
            "A TUI should read keys through Textual, not stdin. If you genuinely need a "
            "prompt, install one with `pyodide.setStdin({stdin, isatty})`."
        ),
        native_message="EOF when reading a line",
        probe="input()",
        env_divergent=True,
    ),
    # --- ENV_DIVERGENT ------------------------------------------------------------------
    Substitution(
        id="os.system",
        severity=Severity.SILENT_WRONG,
        detect=(DetectionRule(DetectionKind.CALL, "os.system"),),
        observed=(
            "In Node it really shells out, via child_process.spawnSync, and returns the exit "
            "status. In a browser there is no such branch: it returns 0 and does nothing. "
            "The most dangerous entry in this registry - it passes every test run under Node "
            "and silently does nothing in production."
        ),
        guidance=(
            "There is no shell in a browser. Whatever the command did has to move into "
            "Python, or behind a network call to a server that still has one."
        ),
        probe=None,
        env_divergent=True,
    ),
    Substitution(
        id="webbrowser.open",
        severity=Severity.LOUD_UNCLEAR,
        detect=(DetectionRule(DetectionKind.CALL, "webbrowser.open"),),
        observed=(
            "Works in a browser - Pyodide's stub calls `window.open` - and fails in Node with "
            "an import error naming `js`, which says nothing about what went wrong."
        ),
        guidance=(
            "Use `App.open_url()`, which the WASM driver implements with `window.open`. "
            "Expect popup blocking unless it happens during a user gesture."
        ),
        native_message="cannot import name 'window' from 'js'",
        probe="import webbrowser; webbrowser.open('https://example.com')",
        env_divergent=True,
    ),
    # --- LOUD_CLEAR: leave these alone ---------------------------------------------------
    Substitution(
        id="subprocess.run",
        severity=Severity.LOUD_CLEAR,
        detect=(DetectionRule(DetectionKind.IMPORT, "subprocess"),),
        observed="Raises immediately with a message that names the constraint exactly.",
        guidance=(
            "Nothing to substitute; a browser has no processes. The message is already "
            "correct, so the runtime translator passes it through untouched."
        ),
        native_message="emscripten does not support processes.",
        probe="import subprocess; subprocess.run(['ls'], check=False)",
    ),
    Substitution(
        id="zoneinfo.tzdata",
        severity=Severity.LOUD_CLEAR,
        detect=(DetectionRule(DetectionKind.CALL, "zoneinfo.ZoneInfo"),),
        observed="Pyodide patches the error to name the exact fix. Left alone deliberately.",
        guidance="Load the tzdata package first, then `zoneinfo` resolves normally.",
        native_message="you must do pyodide.loadPackage('tzdata')",
        probe="import zoneinfo; zoneinfo.ZoneInfo('Europe/Berlin')",
    ),
    # --- UNSUPPORTED: absent modules ------------------------------------------------------
    Substitution(
        id="curses",
        severity=Severity.UNSUPPORTED,
        detect=(DetectionRule(DetectionKind.IMPORT, "curses"),),
        observed="Absent from the build; the import fails at the import site.",
        guidance=(
            "Textual does not use curses, so this usually means a dependency does. There is "
            "no replacement."
        ),
        native_message="No module named 'curses'",
        probe="import curses",
        reference=_PYODIDE_DOCS,
    ),
)
"""Every measured behavioural difference, ordered by severity class."""


def by_id(substitution_id: str) -> Substitution:
    """Look up one substitution.

    Raises:
        KeyError: If no substitution has that id.
    """
    for substitution in SUBSTITUTIONS:
        if substitution.id == substitution_id:
            return substitution
    raise KeyError(substitution_id)


def for_import(module: str) -> tuple[Substitution, ...]:
    """Substitutions triggered by importing `module` or any of its parents.

    `import xml.etree` should match a rule written against `xml`, so the lookup walks the
    dotted prefixes rather than comparing whole names.
    """
    prefixes = {module.rsplit(".", index)[0] for index in range(module.count(".") + 1)}
    return tuple(
        substitution
        for substitution in SUBSTITUTIONS
        for rule in substitution.detect
        if rule.kind is DetectionKind.IMPORT and rule.target in prefixes
    )


def for_call(dotted: str) -> tuple[Substitution, ...]:
    """Substitutions triggered by calling `dotted`.

    Matches on a trailing segment as well as the whole path, because `from os import system`
    then `system(...)` is the same call written differently, and the analyser sees only the
    name at the call site.
    """
    return tuple(
        substitution
        for substitution in SUBSTITUTIONS
        for rule in substitution.detect
        if rule.kind is DetectionKind.CALL
        and (rule.target == dotted or rule.target.endswith(f".{dotted}"))
    )


def with_severity(severity: Severity) -> tuple[Substitution, ...]:
    """Every substitution in one severity class."""
    return tuple(s for s in SUBSTITUTIONS if s.severity is severity)


HARMLESS_ZERO_CALLS: Final[frozenset[str]] = frozenset({"time.sleep"})
"""Calls whose zero-valued form is the "yield to the event loop" idiom and costs nothing.

Consulted by both halves of the toolchain so they cannot disagree: the guard checks the value
at runtime, the scanner checks the literal. A static analyser that flags what the runtime
deliberately ignores is one people learn to skim, and `time.sleep(0)` is common enough to
poison a report on its own.
"""

PROBEABLE: Final[tuple[Substitution, ...]] = tuple(s for s in SUBSTITUTIONS if s.probe)
"""Substitutions whose claim can be re-checked automatically.

The rest are excluded because provoking them would kill the interpreter, or because they only
misbehave in a browser and the characterisation harness runs under Node.
"""
