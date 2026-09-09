"""Tests for locating the optional JavaScript runtime the two web legs need."""

from __future__ import annotations

from pathlib import Path

import pytest

from textual_wasm import node


def test_a_package_is_found_by_walking_up_like_node_does(tmp_path: Path) -> None:
    (tmp_path / "node_modules" / "pyodide").mkdir(parents=True)
    (tmp_path / "node_modules" / "pyodide" / "package.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    found = node.availability(["pyodide"], start=nested)

    assert found.resolve_from == tmp_path
    assert found.missing == ()


def test_a_missing_package_reports_the_command_that_would_fix_it(tmp_path: Path) -> None:
    """A skipped leg is only acceptable if it says how to stop being skipped."""
    missing = node.availability(["puppeteer-core"], start=tmp_path)

    assert missing.missing == ("puppeteer-core",)
    assert "pnpm add -D puppeteer-core" in missing.reason


def test_no_node_is_reported_before_missing_packages(tmp_path: Path) -> None:
    """Installing packages is not the fix when there is nothing to run them with."""
    availability = node.NodeAvailability(node=None, resolve_from=None, missing=("pyodide",))
    assert "node is not on PATH" in availability.reason


def test_the_harnesses_ship_with_the_package() -> None:
    """They are invoked from an installed package, where `scripts/` does not exist."""
    shipped = {path.name for path in node.HARNESS_DIR.iterdir()}
    assert {"pyodide-probe.mjs", "browser-check.mjs", "wasm_entry.py"} <= shipped


def test_a_harness_that_writes_no_json_names_what_it_said(tmp_path: Path) -> None:
    """Otherwise the failure is a JSONDecodeError naming column 1 of nothing."""
    with pytest.raises(node.HarnessError, match="produced no JSON"):
        node.run_harness("browser-check.mjs", {}, node="false", timeout=30.0)
