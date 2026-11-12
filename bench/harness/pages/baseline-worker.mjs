/**
 * A baseline level brought up inside a Web Worker, to match a `--worker` build.
 *
 * The page sends `{ level, manifestUrl }`; this answers `{ ready: true }` once the level is
 * reached, or `{ error }`.
 */

import { bringUp } from "./baseline.mjs";

addEventListener("message", async ({ data }) => {
  try {
    await bringUp(data.level, data.manifestUrl);
    postMessage({ ready: true });
  } catch (error) {
    postMessage({ error: String(error) });
  }
});
