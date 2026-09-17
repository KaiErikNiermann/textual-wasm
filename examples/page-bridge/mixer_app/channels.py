"""What this application's channels carry, declared once for both sides.

`textual-wasm channels mixer_app.channels -o page/channels.d.ts` turns this file into the
TypeScript the page is checked against, so `page/controls.mjs` cannot subscribe to a channel
that does not exist, send the wrong shape, or read a field that was renamed here. A `--check`
run fails when the two drift, which is the only thing that keeps a generated file honest.

The payloads are `TypedDict`s because they have to survive `json.dumps` and `json.loads`
unchanged: a TypedDict *is* the decoded object, so nothing has to be structured back into a
class on arrival, and the generator has a shape it can render one-for-one.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from textual_wasm.channels import Channel

type LevelName = Literal["gain", "bass", "treble"]
"""The three bound levels. A `Literal` rather than `str`, so a page asking for a level this
application does not have is a type error rather than a channel nobody answers."""


class Clipping(TypedDict):
    """Which levels are too hot, and what "too hot" currently means.

    The threshold travels with the report rather than being a constant the page repeats: the
    application decides it, and a page that hard-coded 85 would be wrong the moment it moved.
    """

    threshold: int
    hot: list[LevelName]


GAIN: Channel[int] = Channel("gain")
BASS: Channel[int] = Channel("bass")
TREBLE: Channel[int] = Channel("treble")
"""One channel per bound reactive. Separate rather than one `levels` object, because `bind`
keeps a single attribute in step and a combined payload would make every slider redraw every
meter."""

CLIPPING: Channel[Clipping] = Channel("clipping")
"""Application to page only. Nothing on the page sends on it."""

NOTE: Channel[str] = Channel("note")
"""Page to application only. Declared here so it appears in the generated declarations, and
read with `message.text` rather than through the codec - a line of prose is already a string.

Which is worth being precise about: `Channel[str]` says a *JSON string* crosses, and that is
what `bridge.send` would put on the wire. The page uses `sendText` instead, so what arrives
is the bare text. Both are correct and they are not the same bytes; the declaration exists
for the name, and the handler reads `text`.
"""

LEVELS: tuple[Channel[int], ...] = (GAIN, BASS, TREBLE)
"""Iterated when binding, so adding a level is one declaration and one tuple entry."""
