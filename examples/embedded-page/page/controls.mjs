/**
 * Wire the page's buttons to the embedded application.
 *
 * Deliberately tiny, and deliberately not an integration layer: a terminal application
 * already has an input protocol, so the correct way to drive one from a page is to send it
 * the keystroke it is already listening for.
 */

/**
 * `globalThis.textualWasm` appears only once the app is driving the terminal, which is
 * several seconds after this module runs. Polling for it keeps the buttons inert until then
 * rather than throwing on the first click.
 *
 * @returns {Promise<{ input: (data: string) => void }>}
 */
async function terminalReady() {
  while (globalThis.textualWasm === undefined) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return globalThis.textualWasm;
}

const terminal = await terminalReady();

for (const button of document.querySelectorAll("[data-key]")) {
  button.addEventListener("click", () => {
    terminal.input(button.dataset.key);
  });
}
