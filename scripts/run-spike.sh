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

echo "==> comparison: pyte replay vs xterm.js render"
poetry run textual-wasm-spike compare-screens \
  "${ARTIFACTS}/wasm-report.json" \
  "${ARTIFACTS}/browser-report.json"
