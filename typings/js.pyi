"""Minimal stubs for the Pyodide `js` module.

Only the DOM surface this project actually touches. Declaring it is better than suppressing
pyright: the stub *is* the statement of which browser APIs the driver depends on, and it
fails loudly if one is used that was never considered.
"""

from typing import Literal, Protocol

class HTMLAnchorElement(Protocol):
    href: str
    download: str
    def click(self) -> None: ...

class Document(Protocol):
    def createElement(self, tag: Literal["a"]) -> HTMLAnchorElement: ...

class Window(Protocol):
    def open(self, url: str, target: str) -> None: ...

document: Document
window: Window
