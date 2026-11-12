"""A whole run: every case, every engine, every mode, then the native controls.

Strictly sequential. The idle and memory numbers are readings of the whole machine's view
of one browser, and two browsers running at once would each read the other's work as their
own - so a faster run here would be a wrong one.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from rich.progress import Progress

from textual_wasm_bench import browser, native, results
from textual_wasm_bench.plan import PROFILES, Case, Engine, Layer, Mode, cases, record_key

_log: Final = logging.getLogger(__name__)

NATIVE_IDLE_LAYERS: Final[tuple[Layer, ...]] = (Layer.APP, Layer.INPUT)


@dataclasses.dataclass(frozen=True, slots=True)
class Selection:
    """Which part of the plan to run, and whether to redo what a result file already has."""

    engines: tuple[Engine, ...]
    modes: tuple[Mode, ...]
    only: tuple[str, ...] = ()
    """Run only cases whose name contains one of these; everything when empty."""
    force: bool = False
    include_native: bool = True
    include_browser: bool = True

    def wants(self, name: str) -> bool:
        return not self.only or any(fragment in name for fragment in self.only)

    def jobs(self, all_cases: Iterable[Case]) -> list[tuple[Case, Engine, Mode]]:
        """Every (case, engine, mode) to run, a case with no interpreter once per engine."""
        return [
            (case, engine, mode if case.per_mode else Mode.NONE)
            for engine in self.engines
            for case in all_cases
            if self.wants(case.name)
            for mode in (self.modes if case.per_mode else self.modes[:1])
        ]


def run(profile: str, out: Path, selection: Selection) -> results.ResultFile:
    """Run everything selected, saving after each case, skipping what `out` already has."""
    sizes = PROFILES[profile]
    available = browser.require_node()
    data = results.load(out, profile)
    pending = (
        []
        if not selection.include_browser
        else [
            (case, engine, mode)
            for case, engine, mode in selection.jobs(cases(sizes))
            if selection.force or record_key(engine, mode, case.name) not in data["records"]
        ]
    )

    from textual_wasm_bench.sites import serve  # noqa: PLC0415 - imports the bundler

    modes = selection.modes
    with serve(modes if pending else ()) as urls, Progress() as progress:
        task = progress.add_task("benchmarks", total=len(pending))
        failed: list[str] = []
        for case, engine, mode in pending:
            key = record_key(engine, mode, case.name)
            progress.update(task, description=key)
            site = browser.PAGES[case.layer].site
            base = "" if site is None else urls[site, mode if mode is not Mode.NONE else modes[0]]
            try:
                outcomes = [
                    browser.run_case(
                        case, engine=engine, mode=mode, base_url=base, available=available
                    )
                    for _ in range(case.repeats)
                ]
            except browser.BenchmarkError as error:
                # One case that dies - a wheel fetch lost on the network, a browser crash -
                # must not cost the rest of an hour-long run. It is left out of the file, so
                # rerunning the same command fills in exactly the gaps.
                _log.error("%s failed: %s", key, error)
                failed.append(key)
                progress.advance(task)
                continue
            data["records"][key] = {
                "engine": str(engine),
                "mode": str(mode),
                "case": case.name,
                "scenario": case.scenario,
                "params": dict(case.params),
                "runs": [outcome.data for outcome in outcomes],
                "browser_version": outcomes[0].browser_version,
                "commit": results.stamp(),
                "finished_at": results.now(),
            }
            results.save(out, data)
            progress.advance(task)

    if selection.include_native:
        _run_native(data, out, profile=profile, selection=selection)
    if failed:
        raise browser.BenchmarkError(
            f"{len(failed)} case(s) failed and were left out: {', '.join(failed)}. "
            "Run the same command again to fill them in."
        )
    return data


def _run_native(data: results.ResultFile, out: Path, *, profile: str, selection: Selection) -> None:
    """The CPython controls, stored beside the browser records under engine `native`."""
    sizes = PROFILES[profile]
    for layer in NATIVE_IDLE_LAYERS:
        name = f"idle/{layer}"
        key = record_key("native", Mode.NONE, name)
        if not selection.wants(name) or (key in data["records"] and not selection.force):
            continue
        _log.info("native %s", name)
        runs = [
            native.idle(layer, window_ms=sizes.idle_window_ms, settle_ms=sizes.idle_settle_ms)
            for _ in range(sizes.idle_repeats)
        ]
        data["records"][key] = _native_record(name, "idle", runs)
        results.save(out, data)
    key = record_key("native", Mode.NONE, "control")
    if selection.wants("control") and (selection.force or key not in data["records"]):
        data["records"][key] = _native_record("control", "control", [native.controls(sizes)])
        results.save(out, data)


def _native_record(name: str, scenario: str, runs: list[dict[str, object]]) -> results.Record:
    return {
        "engine": "native",
        "mode": str(Mode.NONE),
        "case": name,
        "scenario": scenario,
        "params": {},
        "runs": runs,
        "commit": results.stamp(),
        "finished_at": results.now(),
    }
