"""Selftest for the semgrep rulesets.

A pattern rule that matches nothing is indistinguishable from a clean codebase, so each rule
has to prove it still fires. This also enforces the rule from the global guidelines that any
harness shelling out to semgrep must inspect `errors`: a crashed scan returns an empty
`results` list, which would otherwise read as "every rule is clean" - or here, as "every rule
is dead", eleven confusing failures pointing at the wrong thing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
RULES_DIR: Final[Path] = PROJECT_ROOT / ".semgrep"
RULESETS: Final[tuple[Path, ...]] = (
    RULES_DIR / "conventions.yml",
    RULES_DIR / "core-utils.yml",
)
"""This project's own rules, named rather than globbed.

`.semgrep/vendor/` holds a ruleset copied from elsewhere, and it is deliberately outside this
selftest: its rules are about markup this repository barely has, so "every rule fires on the
positive fixture" would be false for reasons that say nothing about either rule set.
"""
FIXTURES: Final[Path] = Path(__file__).resolve().parent / "semgrep"

SEMGREP_ENV: Final[dict[str, str]] = {
    **os.environ,
    # Without this the scan fails intermittently on this machine with
    # `Unix_error: Cannot allocate memory io_uring_queue_init`, and the JSON that comes back
    # has an empty results list - so a crashed scan is indistinguishable from a clean one.
    # semgrep-core opens one io_uring ring per Eio domain, charged against RLIMIT_MEMLOCK,
    # which is shared across every process running as this user.
    "EIO_BACKEND": "posix",
}

SEMGREP: Final[str | None] = shutil.which("semgrep")

pytestmark = pytest.mark.skipif(SEMGREP is None, reason="semgrep is not installed")


def _scan(target: Path) -> dict[str, Any]:
    """Run every ruleset against `target` and return the parsed report."""
    assert SEMGREP is not None  # guarded by pytestmark
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths are ours
        [
            SEMGREP,
            *[argument for ruleset in RULESETS for argument in ("--config", str(ruleset))],
            "--metrics=off",
            "--json",
            "--quiet",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=SEMGREP_ENV,
        cwd=PROJECT_ROOT,
    )
    payload: dict[str, Any] = json.loads(completed.stdout)
    assert not payload["errors"], f"semgrep reported errors: {payload['errors']}"
    return payload


def _declared_rule_ids() -> set[str]:
    ids: set[str] = set()
    for ruleset in RULESETS:
        document: Any = yaml.safe_load(ruleset.read_text(encoding="utf-8"))
        ids.update(rule["id"] for rule in document["rules"])
    return ids


def _fired_rule_ids(payload: dict[str, Any]) -> set[str]:
    # semgrep namespaces a finding's id by the config path it came from.
    return {str(result["check_id"]).rsplit(".", 1)[-1] for result in payload["results"]}


def test_every_declared_rule_fires_on_the_positive_fixture() -> None:
    declared = _declared_rule_ids()
    assert declared, "no rules found in .semgrep/"
    fired = _fired_rule_ids(_scan(FIXTURES / "positive"))
    assert declared - fired == set(), "rules that matched nothing (dead or broken)"


def test_no_rule_fires_on_the_negative_fixture() -> None:
    payload = _scan(FIXTURES / "negative")
    findings = [
        f"{result['path']}:{result['start']['line']} {result['check_id']}"
        for result in payload["results"]
    ]
    assert findings == []


def test_project_source_is_clean() -> None:
    payload = _scan(PROJECT_ROOT / "src")
    findings = [
        f"{result['path']}:{result['start']['line']} {result['check_id']}"
        for result in payload["results"]
    ]
    assert findings == []
