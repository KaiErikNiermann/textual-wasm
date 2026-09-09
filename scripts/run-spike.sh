#!/usr/bin/env bash
# Run the whole experiment: the probe on both Python runtimes, then the app in a real
# browser, then the two comparisons.
#
# The comparisons are the experiment. "It runs under WASM" is a weaker claim than "it runs
# the same under WASM", and that in turn is weaker than "a browser renders it the same" -
# identical bytes are only a rendering instruction, and the emulator that executes them in
# a page does not share a character-width table with the one that produced them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="${ROOT}/artifacts"
mkdir -p "${ARTIFACTS}"

echo "==> native (CPython)"
poetry run textual-wasm-spike probe --json >"${ARTIFACTS}/native-report.json"

echo "==> wasm (Pyodide)"
node "${ROOT}/scripts/run-pyodide-node.mjs" >"${ARTIFACTS}/wasm-report.json"

echo "==> browser (Chrome + xterm.js)"
node "${ROOT}/scripts/run-browser-check.mjs" >"${ARTIFACTS}/browser-report.json"

echo "==> comparison: native vs wasm"
poetry run textual-wasm-spike compare \
  "${ARTIFACTS}/native-report.json" \
  "${ARTIFACTS}/wasm-report.json"

# The render reference is a real terminal, not the pyte replay. pyte still gives the two
# Python runtimes a comparable grid - they share its blind spots, so equality between them
# is still meaningful - but it discards the rest of a line after a zero-width joiner or a
# variation selector, which is exactly where the interesting question was.
if command -v tmux >/dev/null 2>&1; then
  echo "==> terminal (tmux + Textual's own driver on a real pty)"
  poetry run textual-wasm-spike capture-terminal >"${ARTIFACTS}/terminal-report.json"

  echo "==> comparison: real terminal vs xterm.js render"
  poetry run textual-wasm-spike compare-screens \
    "${ARTIFACTS}/terminal-report.json" \
    "${ARTIFACTS}/browser-report.json"
else
  echo "==> terminal: SKIPPED (tmux not installed; the render reference is unavailable)"
fi
