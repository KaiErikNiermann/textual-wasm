"""The result file: every record a run produced, and the machine it ran on.

Written after every case, so an interrupted run loses at most the case in flight and a
rerun picks up where it stopped. Records are keyed by engine, mode and case, which makes a
rerun of one case replace that record and leave the rest alone.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

import psutil
from typing_extensions import TypeIs

from textual_wasm.bundler import PYODIDE_VERSION
from textual_wasm_bench import paths

SCHEMA: int = 1


class Record(TypedDict):
    """One case on one engine in one mode: its parameters and every repeat's data."""

    engine: str
    mode: str
    case: str
    scenario: str
    params: dict[str, Any]
    runs: list[dict[str, Any]]
    browser_version: NotRequired[str]
    commit: NotRequired[str]
    """The revision this record was measured at, which a resumed run can change."""
    finished_at: str


class ResultFile(TypedDict):
    schema: int
    profile: str
    environment: dict[str, Any]
    records: dict[str, Record]


def is_result_file(value: object) -> TypeIs[ResultFile]:
    """The shape check a file read back from disk has to pass before anything indexes it."""
    if not isinstance(value, dict):
        return False
    mapping = cast("dict[str, object]", value)
    return (
        mapping.get("schema") == SCHEMA
        and isinstance(mapping.get("records"), dict)
        and isinstance(mapping.get("environment"), dict)
        and isinstance(mapping.get("profile"), str)
    )


MEASURED_PATHS: tuple[str, ...] = (
    "src",
    "bench/bench_apps",
    "bench/harness",
    "bench/textual_wasm_bench",
    "pyproject.toml",
    "poetry.lock",
    "package.json",
    "pnpm-lock.yaml",
    # Rendering and arithmetic over finished results; they change how a number is shown,
    # never the number.
    ":(exclude)bench/textual_wasm_bench/report.py",
    ":(exclude)bench/textual_wasm_bench/summary.py",
)
"""What a measurement depends on, as git pathspecs. The recorded commit is the latest one
that touched these, and a result is dirty only when one of them differs from it - so an
edited docs stylesheet, or a commit that only changes how the tables are rendered, made
while a run is going, does not make its later records look re-measured."""


def _command_output(argv: list[str]) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 - argv is ours, no shell
            argv, capture_output=True, text=True, check=True, cwd=paths.REPOSITORY
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def _cpu_model() -> str:
    """The CPU's marketing name: what a reader compares their machine against."""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.partition(":")[2].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def revision() -> tuple[str | None, bool]:
    """The commit being measured, and whether anything a number depends on differs from it."""
    dirty = _command_output(["git", "status", "--porcelain", "--", *MEASURED_PATHS])
    commit = _command_output(["git", "log", "-1", "--format=%h", "--", *MEASURED_PATHS])
    return commit, bool(dirty)


def stamp() -> str:
    """The revision as one string, for a record: the commit, marked when it is dirty."""
    commit, dirty = revision()
    return f"{commit}{'+dirty' if dirty else ''}"


def environment() -> dict[str, Any]:
    """Everything about this machine and checkout a number depends on."""
    from textual import __version__ as textual_version  # noqa: PLC0415 - after bootstrap

    commit, dirty = revision()
    return {
        "date": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "dirty": dirty,
        "os": platform.platform(),
        "cpu": _cpu_model(),
        "cores": os.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
        "python": platform.python_version(),
        "node": _command_output(["node", "--version"]),
        "pyodide": PYODIDE_VERSION,
        "textual": textual_version,
    }


def load(path: Path, profile: str) -> ResultFile:
    """Read `path` to resume into, or start a new file if there is none.

    Raises:
        ValueError: If the file exists but is not a result file, or was run with another
            profile - mixing sizes in one file would put incomparable numbers side by side.
    """
    if not path.exists():
        return {"schema": SCHEMA, "profile": profile, "environment": environment(), "records": {}}
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    if not is_result_file(decoded):
        raise ValueError(f"{path} is not a benchmark result file (schema {SCHEMA})")
    if decoded["profile"] != profile:
        raise ValueError(f"{path} holds a {decoded['profile']!r} run, not {profile!r}")
    return decoded


def read(path: Path) -> ResultFile:
    """Read a finished result file for reporting.

    Raises:
        ValueError: If it is not one.
    """
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    if not is_result_file(decoded):
        raise ValueError(f"{path} is not a benchmark result file (schema {SCHEMA})")
    return decoded


def save(path: Path, results: ResultFile) -> None:
    """Write atomically, so an interrupt mid-write cannot leave a truncated file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    partial.replace(path)


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
