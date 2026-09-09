<script>
  /**
   * The page around the terminal: ordinary Svelte, with reactive state of its own.
   *
   * What it demonstrates is a boundary rather than a bridge. Svelte owns the layout and the
   * controls; Python owns everything inside the terminal; and the only thing that crosses is
   * a keystroke, which the application was already listening for.
   */
  import Terminal from "./lib/Terminal.svelte";

  const themes = [
    { key: "1", name: "textual-dark" },
    { key: "2", name: "nord" },
    { key: "3", name: "gruvbox" },
    { key: "4", name: "catppuccin-mocha" },
  ];

  /** @type {{ input: (data: string) => void } | undefined} */
  let terminal = $state();
  let sent = $state(0);
  let current = $state(themes[0].name);

  const ready = $derived(terminal !== undefined);

  /** @param {{ key: string, name: string }} theme */
  function choose(theme) {
    terminal?.input(theme.key);
    current = theme.name;
    sent += 1;
  }
</script>

<main>
  <header>
    <h1>Textual <span aria-hidden="true">+</span> Svelte</h1>
    <p>
      A Textual application running as WebAssembly inside a Svelte component. The buttons are
      Svelte; everything inside the frame is Python.
    </p>
  </header>

  <Terminal onready={(instance) => (terminal = instance)} />

  <section class="controls">
    <div class="buttons">
      {#each themes as theme (theme.key)}
        <button
          type="button"
          disabled={!ready}
          class:active={current === theme.name}
          onclick={() => choose(theme)}
        >
          {theme.name}
        </button>
      {/each}
    </div>
    <p class="note">
      {#if ready}
        {sent} keystroke{sent === 1 ? "" : "s"} sent · the app repainted itself each time
      {:else}
        booting CPython…
      {/if}
    </p>
  </section>

  <section class="explain">
    <h2>The whole integration</h2>
    <pre><code>{`await import("/terminal/main.mjs");        // boots the app into <div id="terminal">
globalThis.textualWasm.input("2");        // a keystroke, not an API call`}</code></pre>
    <p>
      Svelte never sees the Python and Vite never bundles it: <code>pnpm build</code> runs
      <code>textual-wasm build</code> into <code>public/terminal/</code> and copies it through
      untouched. The terminal's module resolves its own manifest relative to itself, which is
      what lets it be served from a subdirectory of a site it knows nothing about.
    </p>
  </section>
</main>
