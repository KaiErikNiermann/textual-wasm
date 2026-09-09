#!/usr/bin/env bash
# Run the whole experiment, then re-measure the claims the registry makes about Pyodide.
#
# The first half is now one command: `textual-wasm check` runs the app on every runtime this
# machine offers and compares them. `--strict` is what makes this a CI gate rather than a
# demonstration - without it a machine missing Node or tmux would still print a verdict, and
# the verdict would be about fewer runtimes than anyone reading it assumes.
#
# The substitution check is separate on purpose: `check` answers "does this app work the
# same over there", and this answers "is what we tell people about that runtime still true".
# They fail for different reasons and should be readable apart.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACTS="${ROOT}/artifacts"
mkdir -p "${ARTIFACTS}"

STRICT="${STRICT:---strict}"

echo "==> check: every runtime, one app"
poetry run textual-wasm check ${STRICT} "$@"

echo "==> substitutions: the registry's claims, re-measured under Pyodide"
node "${ROOT}/scripts/run-substitution-check.mjs" >"${ARTIFACTS}/substitutions.json"
echo "wrote ${ARTIFACTS}/substitutions.json"
