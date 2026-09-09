#!/usr/bin/env bash
# Run the probe on both runtimes and compare the two reports.
#
# The comparison is the experiment: "it runs under WASM" is a weaker claim than "it runs
# the same under WASM", and only the second one supports the dual-target story.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="${ROOT}/artifacts"
mkdir -p "${ARTIFACTS}"

echo "==> native (CPython)"
poetry run textual-wasm-spike probe --json >"${ARTIFACTS}/native-report.json"

echo "==> wasm (Pyodide)"
node "${ROOT}/scripts/run-pyodide-node.mjs" >"${ARTIFACTS}/wasm-report.json"

echo "==> comparison"
poetry run textual-wasm-spike compare \
  "${ARTIFACTS}/native-report.json" \
  "${ARTIFACTS}/wasm-report.json"
