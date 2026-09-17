/**
 * Wire this page's controls to the application's channels.
 *
 * The comparison worth making is with `examples/embedded-page`, whose whole integration is
 * `terminal.input("2")` - a keystroke, which is the right shape for a button and no shape at
 * all for a value. Here each control names a channel, the application binds that channel to a
 * reactive, and neither side is the owner of what it holds.
 *
 * Every channel name and payload below is checked against `channels.d.ts`, which
 * `textual-wasm channels` generates from `mixer_app/channels.py`. Rename a channel there and
 * `pnpm lint:ts` fails here; add a field to a payload and the handler that ignores it still
 * compiles, while one that misreads it does not. Without that, a generated file is a document
 * nobody is obliged to agree with.
 *
 * Nothing here knows whether the interpreter is on this thread or in a Web Worker.
 */

/**
 * Generated from `mixer_app/channels.py`. Imported as types rather than referenced, so a
 * bundler never has to resolve it at runtime - a `.d.ts` has nothing to load.
 *
 * @typedef {import("./channels.js").TextualWasm} TextualWasm
 * @typedef {import("./channels.js").ChannelName} ChannelName
 */

/**
 * `globalThis.textualWasm` appears only once the app is driving the terminal, which is
 * several seconds after this module runs. Polling for it keeps the controls inert until then
 * rather than throwing on the first drag.
 *
 * @returns {Promise<TextualWasm>}
 */
async function terminalReady() {
  while (globalThis.textualWasm === undefined) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return globalThis.textualWasm;
}

/**
 * Find one element, refusing to continue without it.
 *
 * A page whose markup lost a control should say so where the control is missing, not fifteen
 * lines later as "possibly null".
 *
 * @template {Element} T
 * @param {string} selector
 * @param {new () => T} kind
 * @returns {T}
 */
function need(selector, kind) {
  const found = document.querySelector(selector);
  if (!(found instanceof kind)) {
    throw new Error(`this page needs ${selector}`);
  }
  return found;
}

const { bridge } = await terminalReady();

/*
 * Levels: both directions on the same channel.
 *
 * The listener is registered before the first `send`, and messages the application published
 * on mount are held for it rather than dropped - so these sliders snap to the application's
 * values on load instead of sitting at whatever the markup declared.
 */
for (const slider of document.querySelectorAll("input[type=range][data-channel]")) {
  if (!(slider instanceof HTMLInputElement)) {
    continue;
  }
  // The cast is the one place a string from the DOM becomes a channel name. Narrow rather
  // than trusted: an attribute the generator has never heard of fails here, at the control
  // that carries it, instead of becoming a subscription nobody answers.
  const channel = /** @type {ChannelName} */ (slider.dataset.channel);
  const readout = need(`output[data-for="${CSS.escape(channel)}"]`, HTMLOutputElement);

  bridge.on(channel, (value) => {
    slider.value = String(value);
    readout.textContent = String(value);
  });

  // `input` rather than `change`, so the meter moves while the slider is being dragged. The
  // application does not echo a value back that this page just sent, so this does not fight
  // with the listener above.
  slider.addEventListener("input", () => {
    bridge.send(channel, Number(slider.value));
    readout.textContent = slider.value;
  });
}

/*
 * Clipping: application to page, with nothing on this page able to send it.
 *
 * `threshold` and `hot` are typed from the Python declaration, so this handler cannot read a
 * field the application does not send - and `hot` is a `LevelName[]`, not a `string[]`.
 *
 * The state lands on a `data-state` attribute rather than a class, because the stylesheet
 * reads state the DOM already holds (PC-6).
 */
const clipping = need("#clipping", HTMLParagraphElement);
bridge.on("clipping", ({ threshold, hot }) => {
  clipping.dataset.state = hot.length > 0 ? "hot" : "quiet";
  clipping.textContent =
    hot.length > 0
      ? `${hot.join(", ")} over ${threshold}`
      : `nothing is clipping (limit ${threshold})`;
});

/*
 * A note: page to application, as text rather than through the codec.
 *
 * `sendText` is the pipe with nothing built on it. A line of prose is already a string, and
 * JSON-encoding it so the other side can JSON-decode it back would be ceremony. The channel
 * is declared in Python all the same, so it appears in the generated file and is a name this
 * page can be checked against.
 */
const note = need("#note", HTMLInputElement);
note.addEventListener("input", () => {
  bridge.sendText("note", note.value);
});

/*
 * The form exists for the labelling; there is nothing to submit, because every control
 * publishes as it changes.
 */
need("#desk", HTMLFormElement).addEventListener("submit", (event) => {
  event.preventDefault();
});
