/**
 * Host a Textual app inside a Web Worker, leaving the main thread free to render.
 *
 * The problem this solves is specific. Pyodide has no threads - `sys._emscripten_info.pthreads`
 * is `False` here as much as anywhere - so a Python call that takes a second is a second in
 * which nothing else in that thread runs. When that thread is the page's, the whole tab is
 * frozen: no scrolling, no animation, no other component on the page doing anything. Moving
 * the interpreter here does not make Python any faster, and does not make threads appear; it
 * moves the freeze somewhere the user cannot see it.
 *
 * Measured by `textual_wasm.responsiveness` against `tests/blocking_app.py`, which spends
 * about a second in a synchronous Python loop: the longest interval between two animation
 * frames on the main thread was 1333ms with the interpreter on that thread, and 16.8ms -
 * one frame - with it here. The freeze does not shrink, it moves.
 *
 * What this deliberately does *not* need is cross-origin isolation. `SharedArrayBuffer` and
 * therefore COOP/COEP would be required to block this thread waiting for main-thread input,
 * but Textual never needs that - its input path is a queue an async loop drains, so a
 * `postMessage` that arrives whenever it arrives is exactly the right shape. That is what
 * keeps a worker build deployable to GitHub Pages, which cannot set headers at all.
 *
 * The contract with `main.mjs` is this module's whole interface:
 *
 *   in:   {type:"start", manifest, cols, rows} | {type:"input", data} | {type:"resize", cols, rows}
 *         | {type:"flush"} | {type:"bridge", channel, text}
 *   out:  {type:"write", data} | {type:"status", state, message} | {type:"running"}
 *         | {type:"exited"} | {type:"crashed", error}
 *         | {type:"open-url", url, newTab} | {type:"deliver-file", href, filename}
 *         | {type:"bridge", channel, text}
 *
 * `bridge` is the one message type that travels in both directions with the same shape,
 * because it is the same channel seen from its two ends - `textual_wasm.bridge`. It carries
 * text rather than a structured clone so that a channel behaves identically here and on the
 * main thread, where the same call would hand Python a live proxy instead.
 */

import { boot, createRelay, flushQuietly, importPyodide } from "./boot.mjs";

/**
 * Batch terminal output into one message per macrotask turn.
 *
 * Textual repaints by writing many small escape sequences in a burst - a single frame is
 * routinely dozens of separate `write` calls. Each `postMessage` is a structured clone plus
 * a task on the receiving thread, so forwarding them one by one turns a cheap redraw into
 * scheduler pressure on the very thread this module exists to keep free.
 *
 * Coalescing is safe because a terminal stream is order-sensitive but not timing-sensitive:
 * concatenating consecutive writes yields the identical byte sequence, which is the thing
 * `check` compares cell by cell.
 */
class OutputBuffer {
  #pending = [];
  #scheduled = false;

  /**
  @param {string} data
  */
  push(data) {
    this.#pending.push(data);
    if (this.#scheduled) {
      return;
    }
    this.#scheduled = true;
    // A microtask, not a timer: it flushes at the end of the current turn, so a full
    // repaint leaves as one message without adding a frame of latency to a keystroke echo.
    queueMicrotask(() => this.flush());
  }

  flush() {
    this.#scheduled = false;
    if (this.#pending.length === 0) {
      return;
    }
    const data = this.#pending.join("");
    this.#pending = [];
    postMessage({ type: "write", data });
  }
}

/**
 * Build the object Python drives, satisfying `textual_wasm.browser.TerminalHost`.
 *
 * The four required members are the same ones an `xterm.js` terminal provides directly;
 * here each is backed by a message instead. `cols` and `rows` are mirrored rather than
 * asked for, because the authoritative grid lives on the other thread and cannot be read
 * synchronously - so the page sends it at start and again on every resize.
 *
 * `openUrl` and `deliverFile` are the optional half of the contract. They exist because
 * `window` and `document` do not exist here, and a driver that reached for them would raise
 * a `ReferenceError` inside whatever the user just clicked.
 *
 * @param {{cols: number, rows: number}} grid the page's initial terminal size
 * @returns {object} the host, plus the hooks the message loop drives it with
 */
function createHost(grid) {
  const output = new OutputBuffer();
  const listeners = { data: [], resize: [] };
  let { cols, rows } = grid;

  return {
    host: {
      write: (data) => output.push(data),
      onData: (callback) => {
        listeners.data.push(callback);
      },
      onResize: (callback) => {
        listeners.resize.push(callback);
      },
      get cols() {
        return cols;
      },
      get rows() {
        return rows;
      },
      openUrl: (url, newTab) => {
        output.flush();
        postMessage({ type: "open-url", url, newTab });
      },
      deliverFile: (href, filename) => {
        output.flush();
        postMessage({ type: "deliver-file", href, filename });
      },
    },
    /**
    @param {string} data
    */
    feedInput(data) {
      for (const callback of listeners.data) {
        callback(data);
      }
    },
    /**
    @param {number} nextCols @param {number} nextRows
    */
    resize(nextCols, nextRows) {
      cols = nextCols;
      rows = nextRows;
      for (const callback of listeners.resize) {
        callback(nextCols, nextRows);
      }
    },
  };
}

/**
 * Build the worker's end of the data channel.
 *
 * The same two members `textual_wasm.bridge.BridgeHost` requires, satisfied by a message
 * instead of a call. Inbound payloads go through a relay for the reason the main thread's do:
 * the page's terminal is live from the first frame and can send long before this thread has
 * an interpreter, let alone an application that has called `Bridge.connect`.
 *
 * @returns {{host: object, deliver: (channel: string, text: string) => void}}
 */
function createBridge() {
  const relay = createRelay();
  return {
    host: {
      send: (channel, text) => postMessage({ type: "bridge", channel, text }),
      subscribe: (callback) => relay.attach(callback),
    },
    deliver(channel, text) {
      relay.push(channel, text);
    },
  };
}

/**
@param {string} state @param {string} message
*/
function report(state, message) {
  postMessage({ type: "status", state, message });
}

/**
 * Everything after the `start` message. Kept as a function so the message listener can be
 * installed synchronously at module scope - a listener added after an `await` misses
 * messages the page sent in the meantime.
 *
 * @param {object} message the `start` message
 * @param {object} host
 * @param {object} bridge the object satisfying `textual_wasm.bridge.BridgeHost`
 */
async function run(message, host, bridge) {
  // One try around the whole sequence, so a failure to boot is reported the same way as a
  // failure to run. A worker that throws without posting anything leaves the page waiting
  // on a message that will never come, with the reason visible only in a console nobody
  // has open.
  try {
    const loadPyodide = await importPyodide(message.manifest);
    const { pyodide, finished } = await boot({
      manifest: message.manifest,
      host,
      bridge,
      loadPyodide,
      onStatus: report,
    });
    // Kept so a `flush` message arriving later has an interpreter to flush. The page sends
    // one when the tab is hidden or closed, which it can hear and this thread cannot.
    state.pyodide = pyodide;
    postMessage({ type: "running" });
    await finished;
    postMessage({ type: "exited" });
  } catch (error) {
    postMessage({ type: "crashed", error: String(error) });
  }
}

/**
 * The worker's mutable state, held in an object because it is assigned from inside the
 * message listener - and because "the terminal is not built yet" is a real state that input
 * arriving early has to be able to see.
 *
 * The channel is built before the terminal rather than with it, so that a page message
 * arriving in the seconds before `start` has somewhere to queue. Its relay holds those until
 * the application subscribes.
 */
const state = { terminal: null, channel: createBridge(), pyodide: null };

addEventListener("message", ({ data }) => {
  switch (data.type) {
    case "start": {
      state.terminal = createHost({ cols: data.cols, rows: data.rows });
      void run(data, state.terminal.host, state.channel.host);
      break;
    }
    // Input and resize can arrive before the interpreter exists - the page's terminal is
    // live from the first frame. Dropping them is correct: there is no application yet to
    // deliver them to, and the size is read from the `start` message anyway.
    case "input": {
      state.terminal?.feedInput(data.data);
      break;
    }
    case "resize": {
      state.terminal?.resize(data.cols, data.rows);
      break;
    }
    // Unlike input, a channel message is *not* dropped when it arrives early: it carries
    // state the page is entitled to assume the application received, and the relay is what
    // makes that true across the seconds Pyodide spends downloading.
    case "bridge": {
      state.channel.deliver(data.channel, data.text);
      break;
    }
    // Best-effort, and unawaited by construction: the page is already going away, so there
    // is nobody left to report to. A flush before the interpreter exists has nothing to
    // write and is correctly a no-op.
    case "flush": {
      if (state.pyodide !== null) {
        void flushQuietly(state.pyodide);
      }
      break;
    }
    default: {
      postMessage({ type: "crashed", error: `unknown message ${data.type}` });
    }
  }
});
