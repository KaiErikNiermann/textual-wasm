"""The share format: a program, compressed, in a URL fragment.

``#v1.<payload>`` where the payload is the UTF-8 source, raw-DEFLATE compressed (RFC 1951,
no zlib header) and base64url-encoded without padding. The same bytes the page produces with
``CompressionStream("deflate-raw")``, so either side can read what the other wrote.

A fragment rather than a query string because the browser never sends it to the server: a
shared program does not end up in anyone's access log, and a static host has no URL length
limit to hit. The version prefix is there so the format can change without old links
decoding into garbage.
"""

from __future__ import annotations

import base64
import zlib

PREFIX = "v1."
"""Marks the format. A fragment without it is not a program."""

MAX_SOURCE_BYTES = 1 << 20
"""Refuse to inflate past this. A link is someone else's input, and 1 KiB of DEFLATE can
expand to a gigabyte; no program anyone types into a playground is a megabyte long."""


class ShareError(ValueError):
    """The fragment is not a program this format can read."""


def encode(source: str) -> str:
    """The fragment (without ``#``) that carries ``source``."""
    compressor = zlib.compressobj(level=9, wbits=-15)
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
    if not body.startswith(PREFIX):
        raise ShareError(f"not a playground link: expected {PREFIX!r}, got {body[:8]!r}")
    payload = body.removeprefix(PREFIX)
    try:
        # Validated, because the permissive decoder skips characters it does not know and
        # a mangled link would then inflate into a different program instead of failing.
        packed = base64.b64decode(
            payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True
        )
        inflater = zlib.decompressobj(wbits=-15)
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
