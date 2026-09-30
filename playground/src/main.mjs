/**
 * The playground page: an editor, a frame that runs what is in it, and a link that carries it.
 *
 * The page never runs Python itself. Each run encodes the editor's contents into the URL
 * fragment of a fresh `runner/` frame - an ordinary `textual-wasm build` whose app reads its
 * program from that fragment - so every run is a new interpreter with nothing left over from
 * the last, and the runtime is exactly the one every other build ships.
 *
 * The frame is sandboxed without `allow-same-origin`. A shared link is someone else's code,
 * and Python in Pyodide can reach JavaScript; on a `*.github.io` origin that other sites
 * share, an unsandboxed frame would hand that code their storage. The cost is that the frame
 * has an opaque origin and reads its own files cross-origin, which GitHub Pages permits with
 * `Access-Control-Allow-Origin: *`.
 */

import { indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { Compartment, Prec } from "@codemirror/state";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView, keymap } from "@codemirror/view";
import { basicSetup } from "codemirror";

import { decode, encode } from "./share.mjs";
import counter from "../starters/counter.py?raw";
import layout from "../starters/layout.py?raw";
import todo from "../starters/todo.py?raw";

/**
Shown in the picker in this order; the first is what an empty playground opens with.
*/
const STARTERS = new Map([
  ["Counter", counter],
  ["To-do list", todo],
  ["CSS grid", layout],
]);

const DRAFT_KEY = "textual-playground:draft";

/**
How long typing has to pause before the address bar and the draft catch up.
*/
const SETTLE_MS = 400;

/**
 * Chat clients and issue trackers start truncating or refusing links somewhere past this; the
 * page says so rather than handing over a link that arrives cut short.
 */
const LONG_LINK = 8000;

const statusElement = document.querySelector("#status");
const starterPicker = document.querySelector("#starter");
const runnerUrl = new URL("runner/", document.baseURI);

/**
 * @param {string} message
 * @param {"info" | "error"} [tone]
 */
function setStatus(message, tone = "info") {
  statusElement.dataset.tone = tone;
  statusElement.textContent = message;
}

/**
 * Storage is a convenience here, never a dependency: a private window or blocked site data
 * makes these throw, and the playground works the same without a draft.
 */
const draft = {
  read() {
    try {
      return localStorage.getItem(DRAFT_KEY);
    } catch {
      return null;
    }
  },
  write(source) {
    try {
      localStorage.setItem(DRAFT_KEY, source);
    } catch {
      // Nothing to do: the address bar still holds the program.
    }
  },
};

/**
 * The program this page opens with: a link's, else the last draft, else the first starter.
 *
 * @returns {Promise<{source: string, problem: string | null}>} `problem` says why a link
 *   that was present could not be used, so the page can say so instead of silently
 *   showing something else.
 */
async function initialProgram() {
  const fallback = draft.read() ?? STARTERS.values().next().value;
  if (location.hash.length <= 1) {
    return { source: fallback, problem: null };
  }
  try {
    return { source: await decode(location.hash), problem: null };
  } catch (error) {
    return { source: fallback, problem: `This link could not be opened: ${error.message}` };
  }
}

/**
Put `fragment` in the address bar without adding a history entry per keystroke.
*/
function showInAddressBar(fragment) {
  history.replaceState(null, "", `#${fragment}`);
}

/**
Run `source` in a fresh frame.
*/
async function run(source) {
  const fragment = await encode(source);
  showInAddressBar(fragment);
  const current = document.querySelector("#runner");
  const fresh = document.createElement("iframe");
  fresh.id = current.id;
  fresh.className = current.className;
  fresh.title = current.title;
  // See the module comment: no allow-same-origin, ever.
  fresh.sandbox.add("allow-scripts", "allow-popups", "allow-downloads");
  fresh.src = new URL(`#${fragment}`, runnerUrl).href;
  current.replaceWith(fresh);
  setStatus("Running in a fresh interpreter. Click the terminal to type into the app.");
}

async function copyLink(source) {
  const fragment = await encode(source);
  showInAddressBar(fragment);
  const link = location.href;
  const size = `${(link.length / 1024).toFixed(1)} KB`;
  const warning = link.length > LONG_LINK ? " Long links can get cut off in chat apps." : "";
  try {
    await navigator.clipboard.writeText(link);
    setStatus(`Link copied (${size}).${warning}`);
  } catch {
    // The clipboard is refused to a frame whose embedder did not delegate it, and to pages
    // without focus. The address bar still has the link.
    setStatus(`Could not reach the clipboard; the address bar has the link (${size}).${warning}`);
  }
}

/**
Follow the reader's colour scheme, live, rather than fixing one at load.
*/
function colourScheme() {
  const theme = new Compartment();
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const pick = () => (dark.matches ? oneDark : []);
  return {
    extension: theme.of(pick()),
    follow(view) {
      dark.addEventListener("change", () => view.dispatch({ effects: theme.reconfigure(pick()) }));
    },
  };
}

function createEditor(initialSource) {
  const scheme = colourScheme();
  let settle;
  const view = new EditorView({
    doc: initialSource,
    parent: document.querySelector("#editor"),
    extensions: [
      basicSetup,
      python(),
      scheme.extension,
      // Tab indents here rather than moving focus, which is what anyone writing Python
      // expects. Escape then Tab still leaves the editor - CodeMirror's documented way out.
      keymap.of([indentWithTab]),
      // Highest precedence so Mod-Enter is not taken by basicSetup's "insert blank line".
      Prec.highest(
        keymap.of([
          { key: "Mod-Enter", run: (editor) => (void run(editor.state.doc.toString()), true) },
          { key: "Mod-s", run: (editor) => (void run(editor.state.doc.toString()), true) },
        ]),
      ),
      EditorView.updateListener.of((update) => {
        if (!update.docChanged) {
          return;
        }
        clearTimeout(settle);
        settle = setTimeout(() => {
          const source = update.state.doc.toString();
          draft.write(source);
          void encode(source).then(showInAddressBar);
        }, SETTLE_MS);
      }),
    ],
  });
  scheme.follow(view);
  return view;
}

function populateStarters(view) {
  starterPicker.append(new Option("—", ""));
  for (const name of STARTERS.keys()) {
    starterPicker.append(new Option(name, name));
  }
  starterPicker.addEventListener("change", () => {
    const source = STARTERS.get(starterPicker.value);
    if (source === undefined) {
      return;
    }
    // One transaction, so Ctrl+Z brings back what was there before.
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: source } });
    starterPicker.value = "";
    void run(source);
  });
}

async function main() {
  // Embedded in the documentation, the page offers a way out to a full window; standalone,
  // that link would point at itself.
  document.documentElement.dataset.embedded = String(globalThis !== top);

  const { source: opening, problem } = await initialProgram();
  const view = createEditor(opening);
  populateStarters(view);
  const source = () => view.state.doc.toString();
  document.querySelector("#run").addEventListener("click", () => void run(source()));
  document.querySelector("#share").addEventListener("click", () => void copyLink(source()));
  document.querySelector("#detach").addEventListener("click", (event) => {
    event.currentTarget.href = location.href;
  });
  // `replaceState` fires no event, so this hears only a link pasted into the address bar of an
  // open playground - which should open that program, not leave the old one on screen.
  addEventListener("hashchange", async () => {
    try {
      const incoming = await decode(location.hash);
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: incoming } });
      await run(incoming);
    } catch (error) {
      setStatus(`This link could not be opened: ${error.message}`, "error");
    }
  });
  await run(source());
  if (problem !== null) {
    setStatus(problem, "error");
  }
}

try {
  await main();
} catch (error) {
  setStatus(`The playground failed to start: ${error}`, "error");
  throw error;
}
