#!/usr/bin/env bash
# Build the documentation site, including the live demos it embeds.
#
# The demos are real builds of the example applications, served as static files from the same
# site as the prose. That is not a presentation choice: the claim this project makes is that a
# Textual app becomes static files, and a documentation page that demonstrated it with a video
# would be arguing for it rather than showing it.
#
# Everything runs from the root virtualenv. The examples have their own for people who copy
# them out, but `build` only reads a package directory - it never imports the app - so one
# environment can build all three.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${ROOT}/docs/_build/html}"
cd "${ROOT}"

step() { printf '\n==> %s\n' "$1"; }

step "sphinx"
# Doctrees outside the output tree: they are a 3 MB build cache, and publishing them puts
# build internals on the site for no reason.
# -W: a warning in the docs is a broken link or a mis-nested directive, and both
# render as silently wrong output rather than as a failure.
poetry run sphinx-build -W -b html -d "${ROOT}/docs/_build/doctrees" docs "${OUT}"

step "demo: simple"
poetry run textual-wasm build simple_app.app:TaskList examples/simple-app/simple_app \
  -o "${OUT}/demos/simple" --title "Tasks"

step "demo: embedded"
poetry run textual-wasm build dashboard_app.app:Dashboard examples/embedded-page/dashboard_app \
  -o "${OUT}/demos/embedded" --title "A terminal in a page" \
  --template examples/embedded-page/page

step "demo: svelte"
# Two builds that do not know about each other: the app becomes static files under `public/`,
# and Vite copies that directory through untouched.
poetry run textual-wasm build palette_app.app:Palette examples/svelte-app/palette_app \
  -o examples/svelte-app/public/terminal --title "Palette"
pnpm --dir examples/svelte-app install --frozen-lockfile
pnpm --dir examples/svelte-app exec vite build
rm -rf "${OUT}/demos/svelte"
mkdir -p "${OUT}/demos"
cp -r examples/svelte-app/dist "${OUT}/demos/svelte"

step "size"
du -sh "${OUT}" "${OUT}/demos"/*
