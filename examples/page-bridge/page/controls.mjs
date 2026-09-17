/**
 * Wire this page's controls to the application's channels.
 *
 * The comparison worth making is with `examples/embedded-page`, whose whole integration is
 * `terminal.input("2")` - a keystroke, which is the right shape for a button and no shape at
 * all for a value. Here each control names a channel, the application binds that channel to a
 * reactive, and neither side is the owner of what it holds.
 *
 * Nothing here knows whether the interpreter is on this thread or in a Web Worker.
 */

/**
 * `globalThis.textualWasm` appears only once the app is driving the terminal, which is
 * several seconds after this module runs. Polling for it keeps the controls inert until then
 * rather than throwing on the first drag.
 *
 * @returns {Promise<object>} the automation surface, including `bridge`
 */
async function terminalReady() {
  while (globalThis.textualWasm === undefined) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return globalThis.textualWasm;
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
  const channel = slider.dataset.channel;
  const readout = document.querySelector(`output[data-for="${CSS.escape(channel)}"]`);

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
 * The state lands on a `data-state` attribute rather than a class, because the stylesheet
 * reads state the DOM already holds (PC-6).
 */
const clipping = document.querySelector("#clipping");
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
 * JSON-encoding it so the other side can JSON-decode it back would be ceremony.
 */
document.querySelector("#note").addEventListener("input", (event) => {
  bridge.sendText("note", event.target.value);
});

/*
 * The form exists for the labelling; there is nothing to submit, because every control
 * publishes as it changes.
 */
document.querySelector("#desk").addEventListener("submit", (event) => {
  event.preventDefault();
});
