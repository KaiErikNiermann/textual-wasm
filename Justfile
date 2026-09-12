set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# List recipes
default:
  @just --list

# --- Environment ------------------------------------------------------------

# Install the Python and JavaScript dependencies
install:
  poetry install
  pnpm install --frozen-lockfile

# Install the browser engines the `check` and browser-marked tests need
install-browsers *engines="chromium firefox webkit":
  pnpm exec playwright install --with-deps {{engines}}

# --- Lint -------------------------------------------------------------------

# Every gate a push has to satisfy, in the order the pre-push hook runs them
gates: lint fmt-check types complexity policy lint-web test matrix-check libraries-check

# Ruff
lint *paths="src tests":
  poetry run ruff check {{paths}}

# Ruff, fixing what it can
lint-fix *paths="src tests":
  poetry run ruff check --fix {{paths}}

# Format
fmt *paths="src tests":
  poetry run ruff format {{paths}}

# Formatting is already applied
fmt-check *paths="src tests":
  poetry run ruff format --check {{paths}}

# Pyright, strict
types:
  poetry run pyright

# Nothing above grade B
complexity:
  @offenders="$(poetry run radon cc -n C src)"; \
    if [[ -n "${offenders}" ]]; then \
      echo "${offenders}"; \
      echo "error: blocks above grade B; simplify or split them" >&2; \
      exit 1; \
    fi
  poetry run radon cc -a src | tail -2

# EIO_BACKEND=posix is load-bearing: without it semgrep-core fails intermittently with
# `Unix_error: Cannot allocate memory io_uring_queue_init` and returns an empty results
# list, so a crashed scan is indistinguishable from a clean one.

# Semgrep: the project conventions and the core-utils rules
policy:
  EIO_BACKEND=posix poetry run semgrep --config .semgrep/conventions.yml \
    --config .semgrep/core-utils.yml --metrics=off --error --quiet src

# eslint + stylelint + the principled-css rules, over the CSS and the examples
lint-web:
  pnpm lint:all

# --- Test -------------------------------------------------------------------

# The suite, minus the tests that need a browser binary
test *args:
  poetry run pytest -m "not browser" {{args}}

# The whole suite, browser-driving tests included
test-all *args:
  poetry run pytest {{args}}

# Only the tests that drive a real browser engine
test-browser *args:
  poetry run pytest -m browser {{args}}

# Skip everything that boots a real Pyodide - the offline path
test-fast *args:
  poetry run pytest -m "not slow and not browser" {{args}}

# The app on CPython, on Pyodide, in a browser and on a real pty, compared
check browser="chromium" *args:
  poetry run textual-wasm check --strict --browser {{browser}} {{args}}

# The same comparison with the interpreter in a Web Worker
check-worker browser="chromium" *args:
  poetry run textual-wasm check --strict --worker --browser {{browser}} {{args}}

# The whole experiment, plus the registry's claims re-measured under Pyodide
spike:
  ./scripts/run-spike.sh

# The porting matrix is still a faithful rendering of the substitution registry
matrix-check:
  poetry run textual-wasm matrix --check -o docs/porting-matrix.md

# Regenerate the porting matrix from the registry
matrix:
  poetry run textual-wasm matrix -o docs/porting-matrix.md

# The add-on support table is still a faithful rendering of the ecosystem registry
libraries-check:
  poetry run textual-wasm libraries --check -o docs/library-table.md

# Regenerate the add-on support table from the registry
libraries:
  poetry run textual-wasm libraries -o docs/library-table.md

# --- Build ------------------------------------------------------------------

# The sdist and the wheel
build:
  poetry build

# They are not Python, so a packaging change that drops them is otherwise silent: `build`
# then writes an empty site and `check` has no wasm or browser leg.

# Build, then assert the wheel carries the page, the harnesses and the assets
build-verify: build
  poetry run python scripts/verify-wheel.py

# The documentation site, including the live demos it embeds
docs out="":
  ./scripts/build-docs.sh {{out}}

# Serve the built documentation site
docs-serve port="8000":
  poetry run python -m http.server {{port}} --directory docs/_build/html

# Regenerate the WASM requirements file from the installed native environment
pins:
  poetry run textual-wasm pins

# Remove build outputs and tool caches
clean:
  rm -rf dist docs/_build artifacts .pytest_cache .ruff_cache
  find . -name __pycache__ -type d -prune -not -path './.venv/*' -exec rm -rf {} +

# --- Release ----------------------------------------------------------------

# Bump version, commit, tag, push, and create GitHub release
release bump="patch":
  @bump="{{bump}}"; \
    if [[ "$bump" == bump=* ]]; then bump="${bump#bump=}"; fi; \
    poetry version "$bump"
  @version=$(poetry version --short); \
    just _release "$version"

# Use an explicit version
release-version version:
  @version="{{version}}"; \
    if [[ "$version" == version=* ]]; then version="${version#version=}"; fi; \
    poetry version "$version"; \
    just _release "$version"

# Re-trigger publish for an existing version by re-tagging HEAD
rerun version:
  @version="{{version}}"; \
    if [[ "$version" == version=* ]]; then version="${version#version=}"; fi; \
    git push; \
    git tag -d v"$version" || true; \
    git push --delete origin v"$version" || true; \
    git tag v"$version"; \
    git push origin v"$version"

# Delete and recreate the GitHub release + retag HEAD at the same version
rerelease version:
  @version="{{version}}"; \
    if [[ "$version" == version=* ]]; then version="${version#version=}"; fi; \
    gh release delete v"$version" -y || true; \
    just rerun "$version"; \
    gh release create v"$version" --title "v$version" --generate-notes

# Internal helper
_release version:
  @version="{{version}}"; \
    if [[ "$version" == version=* ]]; then version="${version#version=}"; fi; \
    git add pyproject.toml; \
    git add -f poetry.lock; \
    git commit -m "chore(release): v$version"; \
    git push; \
    git tag v"$version"; \
    git push origin v"$version"; \
    gh release create v"$version" --title "v$version" --generate-notes
