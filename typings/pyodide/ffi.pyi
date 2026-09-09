"""Stub for `pyodide.ffi`.

`create_proxy`, which a driver cannot do without: a Python callable passed to JavaScript
is wrapped in a *borrowed* proxy that is destroyed when the call it was passed into returns.
Anything JavaScript stores and invokes later - every event listener - must own a proxy whose
lifetime the caller manages.

Typed to preserve the wrapped signature, so a proxied callback still satisfies the same
protocol the bare method did and passing the wrong one is a type error.

Plus `can_run_sync`, the feature test for JavaScript Promise Integration. It is a function
rather than a constant because the answer depends on how the caller was entered - False under
a plain `runPython`, True under `runPythonAsync`.
"""

from collections.abc import Callable
from typing import ParamSpec, Protocol, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R", covariant=True)

class JsCallable(Protocol[_P, _R]):
    def __call__(self, *args: _P.args, **kwargs: _P.kwargs) -> _R: ...
    def destroy(self) -> None: ...

def create_proxy(obj: Callable[_P, _R]) -> JsCallable[_P, _R]: ...
def can_run_sync() -> bool: ...
