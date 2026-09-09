import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  // Relative asset URLs, so the built site works from any subdirectory - which is where it
  // ends up on a documentation site.
  base: "./",
  build: { outDir: "dist", emptyOutDir: true },
});
