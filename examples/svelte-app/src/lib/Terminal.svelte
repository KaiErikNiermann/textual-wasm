<script>
  /**
   * A Textual application as a Svelte component.
   *
   * The build is a directory of static files under `public/terminal/`, and this component
   * loads its entry module after the mount point exists. Nothing is bundled: Vite never sees
   * the Python, and the terminal's own module resolves its manifest relative to itself, which
   * is what lets it live at `/terminal/` while this page lives at `/`.
   */
  import { onMount } from "svelte";

  /** @type {{ onready?: (terminal: object) => void }} */
  const { onready } = $props();

  let status = $state("starting…");

  onMount(async () => {
    // A dynamic import with a URL Vite must not rewrite: the file is served from `public/`,
    // not built from source, so it has no module graph for the bundler to follow.
    await import(/* @vite-ignore */ new URL("terminal/main.mjs", document.baseURI).href);

    // The automation surface appears only once Python is driving the terminal. Polling for it
    // is the documented way in; there is no event to subscribe to.
    while (globalThis.textualWasm === undefined) {
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    status = "ready";
    onready?.(globalThis.textualWasm);
  });
</script>

<div class="frame" data-status={status}>
  <!-- No padding or border on this element: FitAddon sizes the grid from its parent box, so
       decoration here would be counted as room for text and the footer would be clipped. -->
  <div id="terminal"></div>
</div>

<style>
  .frame {
    display: grid;
    block-size: 26rem;
    padding: var(--space-3);
    border: 1px solid var(--edge);
    border-radius: var(--radius);
    background: var(--terminal-bg);
  }

  #terminal {
    min-block-size: 0;
  }
</style>
