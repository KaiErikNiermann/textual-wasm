/**
 * The share format: a program, compressed, in a URL fragment.
 *
 * `#v2.<payload>`, where the payload is the UTF-8 source, raw-DEFLATE compressed against the
 * preset dictionary in `share_dictionary.txt` and base64url-encoded without padding.
 * `#v1.<payload>` is the same without the dictionary; old links are read, nothing writes it.
 * `playground_runner/share.py` reads and writes the same bytes, and the runner frame decodes
 * the fragment it is given with it - so a link the page writes is exactly the program the
 * runner executes.
 *
 * A fragment, not a query string: the browser never sends it to the server, so a shared
 * program stays out of access logs and no host-side URL limit applies.
 */

import { deflateSync } from "fflate";

import dictionaryText from "../runner/playground_runner/share_dictionary.txt?raw";

export const PREFIX = "v2.";

/**
The format without a dictionary, read so that older links keep working.
*/
const PLAIN_PREFIX = "v1.";

/**
 * The preset dictionary of `v2.` links: Textual code that programs tend to repeat. Part of the
 * format, so it never changes; `share.py` reads the same file. It is ASCII, so the text Vite
 * inlines encodes back to the same bytes.
 */
const DICTIONARY = new TextEncoder().encode(dictionaryText);

/**
 * A non-final stored DEFLATE block (RFC 1951, 3.2.4) that outputs the dictionary. A stream
 * written against a preset dictionary inflates, after this block, to the dictionary and then
 * the program: the block fills the window just as a preset dictionary does. That lets the
 * browser's own `DecompressionStream` read `v2.` links, which has no dictionary option.
 */
const DICTIONARY_BLOCK = new Uint8Array([
  0b000, // BFINAL 0, BTYPE 00 (stored), then padding to the byte boundary
  DICTIONARY.length & 0xFF,
  DICTIONARY.length >> 8,
  ~DICTIONARY.length & 0xFF,
  (~DICTIONARY.length >> 8) & 0xFF,
  ...DICTIONARY,
]);

/**
 * Refuse to inflate past this. A link is someone else's input, and a kilobyte of DEFLATE can
 * expand to a gigabyte. Mirrors `MAX_SOURCE_BYTES` in `share.py`.
 */
export const MAX_SOURCE_BYTES = 1 << 20;

/**
 * With fflate, because `CompressionStream` cannot take a dictionary. Synchronous, and quick
 * for anything a person types: it took under a millisecond for programs up to 14 KB in Node.
 *
 * @param {string} source
 * @returns {Promise<string>} the fragment, without its `#`
 */
export async function encode(source) {
  const bytes = deflateSync(new TextEncoder().encode(source), { level: 9, dictionary: DICTIONARY });
  return PREFIX + bytes.toBase64({ alphabet: "base64url", omitPadding: true });
}

/**
 * @param {string} fragment `location.hash`, with or without its `#`
 * @returns {Promise<string>} the program
 * @throws {Error} when the fragment is not in this format, is corrupt, or is too large
 */
export async function decode(fragment) {
  const body = fragment.startsWith("#") ? fragment.slice(1) : fragment;
  const isPlain = body.startsWith(PLAIN_PREFIX);
  if (!isPlain && !body.startsWith(PREFIX)) {
    throw new Error(`not a playground link (expected it to start with "${PREFIX}")`);
  }
  const packed = Uint8Array.fromBase64(body.slice(body.indexOf(".") + 1), {
    alphabet: "base64url",
  });
  // What inflates ahead of the program and is dropped: the dictionary, for a `v2.` link.
  const skip = isPlain ? 0 : DICTIONARY.length;
  const reader = new Blob(isPlain ? [packed] : [DICTIONARY_BLOCK, packed])
    .stream()
    .pipeThrough(new DecompressionStream("deflate-raw"))
    .getReader();

  // Read chunk by chunk rather than through `Response.arrayBuffer()`, so a bomb is stopped
  // at the limit instead of after it has been inflated in full.
  const chunks = [];
  let size = 0;
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
    size += chunk.value.byteLength;
    if (size > skip + MAX_SOURCE_BYTES) {
      await reader.cancel();
      throw new Error(`the program is over ${MAX_SOURCE_BYTES} bytes`);
    }
    chunks.push(chunk.value);
  }
  const program = await new Blob(chunks).slice(skip).arrayBuffer();
  return new TextDecoder("utf-8", { fatal: true }).decode(program);
}
