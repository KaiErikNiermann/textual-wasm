import { defineConfig } from "vite";

// The runner frame is sandboxed into an opaque origin, so every file it loads - its page,
// its scripts, its manifest - is a cross-origin request. GitHub Pages answers those with
// `Access-Control-Allow-Origin: *`; these make the local servers do the same.
const cors = { origin: "*" };

export default defineConfig({
  // Relative asset URLs, so the built site works from any subdirectory - which is where it
  // ends up on the documentation site.
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
  server: { cors },
  preview: { cors },
});
