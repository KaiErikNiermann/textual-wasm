"""Compare a native probe report against a WASM one.

The spike's actual claim is not "it runs in the browser" but "it runs *the same*". That is
only checkable mechanically, because the interesting failure mode is a check that passes on
both sides for different reasons. Everything here is therefore about agreement, not success.
"""

from __future__ import annotations

import dataclasses
from typing import Final

from textual_wasm.report import CheckId, CheckStatus, ProbeReport, RuntimeFacts

EXPECTED_RUNTIME_DIVERGENCE: Final[frozenset[str]] = frozenset(
    {
        "platform",
        "python_version",
        "event_loop",
        "threads_available",
        "polyfills_applied",
    }
)
"""Runtime fields that *should* differ between the two hosts.

Listing them makes the remainder meaningful: `textual_version` and
`eager_task_factory_accepted` differing would mean the two runs were not comparable, and
would otherwise be lost among the differences that are simply true.
"""


@dataclasses.dataclass(frozen=True, slots=True)
class CheckAgreement:
    """One check's verdict on both runtimes."""

    check: CheckId
    native: CheckStatus
    wasm: CheckStatus

    @property
    def agrees(self) -> bool:
        return self.native is self.wasm

    @property
    def passes_both(self) -> bool:
        return self.native is CheckStatus.PASS and self.wasm is CheckStatus.PASS


@dataclasses.dataclass(frozen=True, slots=True)
class RuntimeDifference:
    """A `RuntimeFacts` field whose value differs between hosts."""

    field: str
    native: str
    wasm: str

    @property
    def expected(self) -> bool:
        """Whether this field is one the two hosts are supposed to disagree on."""
        return self.field in EXPECTED_RUNTIME_DIVERGENCE


@dataclasses.dataclass(frozen=True, slots=True)
class Comparison:
    """The verdict of the whole experiment."""

    agreements: tuple[CheckAgreement, ...]
    runtime_differences: tuple[RuntimeDifference, ...]

    @property
    def disagreements(self) -> tuple[CheckAgreement, ...]:
        return tuple(a for a in self.agreements if not a.agrees)

    @property
    def unexpected_differences(self) -> tuple[RuntimeDifference, ...]:
        """Runtime differences that are not accounted for by the host change alone."""
        return tuple(d for d in self.runtime_differences if not d.expected)

    @property
    def equivalent(self) -> bool:
        """True when every check passed on both hosts and nothing unexplained differs."""
        return (
            bool(self.agreements)
            and all(a.passes_both for a in self.agreements)
            and not self.unexpected_differences
        )


def _runtime_differences(native: RuntimeFacts, wasm: RuntimeFacts) -> tuple[RuntimeDifference, ...]:
    return tuple(
        RuntimeDifference(field.name, str(native_value), str(wasm_value))
        for field in dataclasses.fields(RuntimeFacts)
        if (native_value := getattr(native, field.name))
        != (wasm_value := getattr(wasm, field.name))
    )


def compare(native: ProbeReport, wasm: ProbeReport) -> Comparison:
    """Pair the two reports check by check.

    Raises:
        ValueError: If the reports do not cover the same checks, which means one of the runs
            used a different build and the comparison would be meaningless.
    """
    native_by_id = {result.check: result for result in native.checks}
    wasm_by_id = {result.check: result for result in wasm.checks}
    if native_by_id.keys() != wasm_by_id.keys():
        raise ValueError(
            f"reports cover different checks: native={sorted(c.value for c in native_by_id)}, "
            f"wasm={sorted(c.value for c in wasm_by_id)}"
        )
    return Comparison(
        agreements=tuple(
            CheckAgreement(check, native_by_id[check].status, wasm_by_id[check].status)
            for check in CheckId
            if check in native_by_id
        ),
        runtime_differences=_runtime_differences(native.runtime, wasm.runtime),
    )
