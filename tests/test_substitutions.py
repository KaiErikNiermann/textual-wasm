"""Tests for the substitution registry.

Two halves. The pure-Python half checks the lookups and the registry's internal consistency
and runs in milliseconds. The characterisation half re-executes every claim inside Pyodide
and is marked `slow`, because it costs a runtime boot and a package install.

The slow half is the point of the registry. Pyodide's own documentation lists modules as
removed that import fine in 314.0.6 - that is what happens to a claim nobody re-runs, and
this module's whole value proposition is being right about this runtime.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from textual_wasm import node
from textual_wasm.substitutions import (
    PROBEABLE,
    SUBSTITUTIONS,
    DetectionKind,
    Severity,
    Substitution,
    by_id,
    for_call,
    for_import,
    with_severity,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
HARNESS: Final[Path] = PROJECT_ROOT / "scripts" / "run-substitution-check.mjs"

PYODIDE: Final[node.NodeAvailability] = node.availability(
    [node.PYODIDE_PACKAGE], start=PROJECT_ROOT
)
"""Whether a Pyodide runtime can be booted here.

Through the same lookup the `check` command uses, rather than a `which node`: the harness
needs the *package*, and a machine with node but no `node_modules` was reported as ready and
then failed - which is how these tests broke on their first CI run.
"""


# --- the fast half ---------------------------------------------------------------------


def test_every_substitution_has_a_unique_id() -> None:
    ids = [substitution.id for substitution in SUBSTITUTIONS]
    assert len(ids) == len(set(ids))


def test_every_substitution_is_detectable() -> None:
    """A substitution with no detection rule can never be reported by the doctor."""
    for substitution in SUBSTITUTIONS:
        assert substitution.detect, f"{substitution.id} has no detection rule"


def test_silent_substitutions_record_no_message() -> None:
    """`SILENT_WRONG` means nothing is raised, so there is no message to translate.

    Recording one would make the runtime translator match text that never appears.
    """
    for substitution in with_severity(Severity.SILENT_WRONG):
        assert substitution.native_message is None, substitution.id


def test_loud_substitutions_record_their_message() -> None:
    """Anything the translator is meant to rewrite must carry the text it matches on."""
    loud = (*with_severity(Severity.LOUD_UNCLEAR), *with_severity(Severity.LOUD_CLEAR))
    for substitution in loud:
        assert substitution.native_message, substitution.id


def test_import_lookup_matches_dotted_prefixes() -> None:
    """`import multiprocessing.pool` must match a rule written against `multiprocessing`."""
    assert by_id("multiprocessing.process") in for_import("multiprocessing.pool")


def test_import_lookup_does_not_match_unrelated_modules() -> None:
    assert for_import("threading_utils") == ()


def test_call_lookup_matches_a_bare_name() -> None:
    """`from os import system` then `system(...)` is the same call, seen without its module."""
    assert by_id("os.system") in for_call("system")
    assert by_id("os.system") in for_call("os.system")


def test_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        by_id("no.such.substitution")


# --- the slow half ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def observed() -> dict[str, dict[str, Any]]:
    """Re-measure every probeable claim inside Pyodide. One runtime boot for the module."""
    assert PYODIDE.node is not None  # guarded by the marker below
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, paths are ours
        [PYODIDE.node, str(HARNESS)],
        capture_output=True,
        text=True,
        check=True,
        cwd=PROJECT_ROOT,
        env={**os.environ},
    )
    payload: dict[str, dict[str, Any]] = json.loads(completed.stdout)
    return payload


@pytest.mark.slow
@pytest.mark.skipif(not PYODIDE.available, reason=PYODIDE.reason)
@pytest.mark.parametrize("substitution", PROBEABLE, ids=lambda s: s.id)
def test_severity_still_matches_reality(
    substitution: Substitution, observed: dict[str, dict[str, Any]]
) -> None:
    """The severity class is a claim about whether anything is raised at all.

    This is the assertion that catches a Pyodide release turning a silent failure loud, or
    the reverse - which would invalidate the guards in `diagnostics` without touching them.
    """
    outcome = observed[substitution.id]
    expected_raise = substitution.severity is not Severity.SILENT_WRONG
    assert outcome["raised"] is expected_raise, (
        f"{substitution.id} is classified {substitution.severity.value} but "
        f"{'raised' if outcome['raised'] else 'raised nothing'}: {outcome['message']!r}"
    )


@pytest.mark.slow
@pytest.mark.skipif(not PYODIDE.available, reason=PYODIDE.reason)
@pytest.mark.parametrize(
    "substitution",
    [s for s in PROBEABLE if s.native_message],
    ids=lambda s: s.id,
)
def test_recorded_message_still_matches_reality(
    substitution: Substitution, observed: dict[str, dict[str, Any]]
) -> None:
    """The translator matches on this text, so a drifted message silently disables it."""
    assert substitution.native_message is not None
    actual = observed[substitution.id]["message"] or ""
    assert substitution.native_message in actual, (
        f"{substitution.id} records {substitution.native_message!r} but Pyodide now says {actual!r}"
    )


@pytest.mark.slow
@pytest.mark.skipif(not PYODIDE.available, reason=PYODIDE.reason)
def test_every_probeable_substitution_was_measured(
    observed: dict[str, dict[str, Any]],
) -> None:
    assert set(observed) == {s.id for s in PROBEABLE}


def test_unprobeable_substitutions_say_why() -> None:
    """Anything without a probe is exempt from measurement, so the exemption must be earned.

    Only two reasons are acceptable: running it would kill the interpreter, or it only
    misbehaves in a browser and this harness runs under Node.
    """
    exempt = {s.id for s in SUBSTITUTIONS} - {s.id for s in PROBEABLE}
    assert exempt == {"socket.connect", "os.kill.terminate", "os.system"}
    for substitution in SUBSTITUTIONS:
        if substitution.probe is None:
            assert substitution.env_divergent or substitution.severity is Severity.FATAL, (
                f"{substitution.id} has no probe and no reason to lack one"
            )


def test_detection_kinds_are_exhaustive() -> None:
    """Guards against a rule kind being added without the doctor learning to match it."""
    kinds = {rule.kind for substitution in SUBSTITUTIONS for rule in substitution.detect}
    assert kinds == set(DetectionKind)
