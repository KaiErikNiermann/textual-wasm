"""Map Pyodide's own error messages onto the registry's guidance.

Deliberately narrow. Several of Pyodide's messages are better than anything a wrapper would
produce - micropip names the package, links the FAQ and suggests a flag; the `zoneinfo` one
embeds the exact fix - so only `LOUD_UNCLEAR` entries are translated. Replacing a good
message with a generic one is a regression, which is why the registry records that class at
all.
"""

from __future__ import annotations

from textual_wasm.diagnostics.errors import UnsupportedInWasmError
from textual_wasm.substitutions import Severity, with_severity


def translate(error: BaseException) -> UnsupportedInWasmError | None:
    """Return a clearer exception for `error`, or None to leave it alone.

    Matching is on message text rather than exception type because the same constraint
    surfaces as several types - a `RuntimeError` for threads, a `ModuleNotFoundError` for
    multiprocessing, an `OSError` for fork - and the message is the part that identifies it.
    """
    if isinstance(error, UnsupportedInWasmError):
        return None
    message = str(error)
    for substitution in with_severity(Severity.LOUD_UNCLEAR):
        if substitution.native_message and substitution.native_message in message:
            return UnsupportedInWasmError(substitution, detail=message)
    return None
