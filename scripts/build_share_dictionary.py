"""Build the preset DEFLATE dictionary that playground links are compressed against.

The dictionary is part of the link format: a `v2.` link only decodes against the exact bytes
it was written with. It is therefore built once and committed, and this script records how.
Running it again and committing the result would break every `v2.` link already shared; a
new dictionary needs a new format prefix, with the old one kept for decoding.

It is trained with zstd's dictionary builder (COVER) on the example programs in Textual's
documentation, the `.py` and `.tcss` files under `docs/examples` of a Textual checkout, and
keeps the last 32 KiB of what that builder writes: the raw-content part, which DEFLATE can
use as a preset dictionary because DEFLATE's window is 32 KiB. The builder puts the most
useful content last, which is also where DEFLATE's back-references are cheapest.

The committed dictionary was built from Textual v8.2.8
(commit 1d99508b928a771b51e1a527319c6b87dcff9e05), whose code is MIT licensed, Copyright (c)
2021 Will McGugan.

    git clone --depth 1 --branch v8.2.8 https://github.com/Textualize/textual .scratch/textual
    poetry run python scripts/build_share_dictionary.py .scratch/textual/docs/examples
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import zstandard

OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "playground/runner/playground_runner/share_dictionary.txt"
)
DICTIONARY_BYTES = 32 * 1024
"""DEFLATE's window: a back-reference reaches at most this far."""
TRAINED_BYTES = 64 * 1024
"""What the builder is asked for. Measured on held-out programs, asking for twice the window
and keeping the tail compressed 1.5-4 KB programs about 1.5% better than asking for 32 KiB."""
MIN_SAMPLE_BYTES = 300
"""Shorter files are mostly fragments of a longer example and skew the training."""

log = logging.getLogger(__name__)


def build(examples: Path) -> bytes:
    """The dictionary trained on the `.py` and `.tcss` files under ``examples``."""
    samples = [
        path.read_bytes()
        for path in sorted(examples.rglob("*"))
        if path.suffix in {".py", ".tcss"} and path.stat().st_size >= MIN_SAMPLE_BYTES
    ]
    log.info("training on %d files", len(samples))
    # The stub types `samples` as an invariant `list[ByteString]`, which no `list[bytes]` is.
    trained = zstandard.train_dictionary(
        TRAINED_BYTES,
        samples,  # pyright: ignore[reportArgumentType]
        level=19,
    ).as_bytes()
    # ASCII only, so the file is text that the page can import as a string and turn back into
    # the same bytes. The builder cuts samples mid-character, and the few non-ASCII bytes
    # (emoji and box drawing in string literals) are not worth a binary file.
    content = bytes(byte for byte in trained if byte < 0x80)[-DICTIONARY_BYTES:]
    if b"\r" in content:
        raise ValueError("the dictionary has a carriage return, which git may rewrite")
    return content


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n", 1)[0])
    parser.add_argument("examples", type=Path, help="docs/examples of a Textual checkout")
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    content = build(args.examples)
    args.output.write_bytes(content)
    log.info("wrote %d bytes to %s", len(content), args.output)


if __name__ == "__main__":
    main()
