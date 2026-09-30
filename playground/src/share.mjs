/**
 * The share format: a program, compressed, in a URL fragment.
 *
 * `#v1.<payload>`, where the payload is the UTF-8 source, raw-DEFLATE compressed and
 * base64url-encoded without padding. `playground_runner/share.py` reads and writes the same
 * bytes, and the runner frame decodes the fragment it is given with it - so a link the page
 * writes is exactly the program the runner executes.
 *
 * A fragment, not a query string: the browser never sends it to the server, so a shared
 * program stays out of access logs and no host-side URL limit applies. Compression is what
 * makes it practical - a 60-line app is around 1 KB of link rather than 3.
 */

export const PREFIX = "v1.";

/**
 * Refuse to inflate past this. A link is someone else's input, and a kilobyte of DEFLATE can
 * expand to a gigabyte. Mirrors `MAX_SOURCE_BYTES` in `share.py`.
 */
export const MAX_SOURCE_BYTES = 1 << 20;

/**
 * @param {string} source
 * @returns {Promise<string>} the fragment, without its `#`
 */
export async function encode(source) {
  const stream = new Blob([source]).stream().pipeThrough(new CompressionStream("deflate-raw"));
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  return PREFIX + bytes.toBase64({ alphabet: "base64url", omitPadding: true });
}

/**
 * @param {string} fragment `location.hash`, with or without its `#`
 * @returns {Promise<string>} the program
 * @throws {Error} when the fragment is not in this format, is corrupt, or is too large
 */
export async function decode(fragment) {
  const body = fragment.startsWith("#") ? fragment.slice(1) : fragment;
  if (!body.startsWith(PREFIX)) {
    throw new Error(`not a playground link (expected it to start with "${PREFIX}")`);
  }
  const packed = Uint8Array.fromBase64(body.slice(PREFIX.length), { alphabet: "base64url" });
  const reader = new Blob([packed])
    .stream()
    .pipeThrough(new DecompressionStream("deflate-raw"))
    .getReader();

  // Read chunk by chunk rather than through `Response.arrayBuffer()`, so a bomb is stopped
  // at the limit instead of after it has been inflated in full.
  const chunks = [];
  let size = 0;
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
    size += chunk.value.byteLength;
    if (size > MAX_SOURCE_BYTES) {
      await reader.cancel();
      throw new Error(`the program is over ${MAX_SOURCE_BYTES} bytes`);
    }
    chunks.push(chunk.value);
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(await new Blob(chunks).arrayBuffer());
}
