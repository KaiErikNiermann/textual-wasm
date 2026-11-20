"""The share format: a program, compressed, in a URL fragment.

``#v2.<payload>`` where the payload is the UTF-8 source, raw-DEFLATE compressed (RFC 1951,
no zlib header) against the preset dictionary in ``share_dictionary.txt``, and
base64url-encoded without padding. The dictionary holds code that Textual programs tend to
repeat (imports, ``compose``, ``CSS``, ``on_mount``), so a program can refer back to it
instead of spelling it out. On 25 programs it was not trained on, that made links a median
48% shorter than compressing alone for programs under 1.5 KB, 25% for 1.5-5 KB, and 11-16%
past 5 KB.

``#v1.<payload>`` is the earlier format, the same without the dictionary. Links in it are
still read, and nothing writes it any more.

A fragment rather than a query string because the browser never sends it to the server: a
shared program does not end up in anyone's access log, and a static host has no URL length
limit to hit. The version prefix is there so the format can change without old links
decoding into garbage.
"""

from __future__ import annotations

import base64
import zlib
from pathlib import Path

PREFIX = "v2."
"""What `encode` writes."""

PLAIN_PREFIX = "v1."
"""The format without a dictionary, still read so that older links keep working."""

DICTIONARY = (Path(__file__).parent / "share_dictionary.txt").read_bytes()
"""The preset DEFLATE dictionary of ``v2.`` links. Part of the format: changing a byte of it
breaks every link written with it. ``scripts/build_share_dictionary.py`` says how it was
built."""

MAX_SOURCE_BYTES = 1 << 20
"""Refuse to inflate past this. A link is someone else's input, and 1 KiB of DEFLATE can
expand to a gigabyte; no program anyone types into a playground is a megabyte long."""


class ShareError(ValueError):
    """The fragment is not a program this format can read."""


def encode(source: str) -> str:
    """The fragment (without ``#``) that carries ``source``."""
    compressor = zlib.compressobj(level=9, wbits=-15, zdict=DICTIONARY)
    packed = compressor.compress(source.encode()) + compressor.flush()
    return PREFIX + base64.urlsafe_b64encode(packed).decode().rstrip("=")


def decode(fragment: str) -> str:
    """The program a fragment carries.

    Args:
        fragment: ``location.hash``, with or without its leading ``#``.

    Raises:
        ShareError: If the fragment is not in this format, is corrupt, or inflates past
            `MAX_SOURCE_BYTES`.
    """
    body = fragment.removeprefix("#")
    if body.startswith(PREFIX):
        inflater = zlib.decompressobj(wbits=-15, zdict=DICTIONARY)
    elif body.startswith(PLAIN_PREFIX):
        inflater = zlib.decompressobj(wbits=-15)
    else:
        raise ShareError(f"not a playground link: expected {PREFIX!r}, got {body[:8]!r}")
    payload = body.partition(".")[2]
    try:
        # Validated, because the permissive decoder skips characters it does not know and
        # a mangled link would then inflate into a different program instead of failing.
        packed = base64.b64decode(
            payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True
        )
        raw = inflater.decompress(packed, MAX_SOURCE_BYTES + 1)
    except (ValueError, zlib.error) as error:
        raise ShareError(f"the link is corrupt: {error}") from error
    if len(raw) > MAX_SOURCE_BYTES or inflater.unconsumed_tail:
        raise ShareError(f"the program is over {MAX_SOURCE_BYTES} bytes")
    if not inflater.eof:
        # A link cut short by a chat client that wrapped or truncated it.
        raise ShareError("the link is incomplete: the compressed program ends early")
    try:
        return raw.decode()
    except UnicodeDecodeError as error:
        raise ShareError(f"the program is not UTF-8: {error}") from error
