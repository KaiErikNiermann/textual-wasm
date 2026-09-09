"""Import this project before anything imports Textual.

`textual.constants` reads every TEXTUAL_* variable into module-level constants at import
time, and importing `textual_wasm` is what sets them. A test module that imports `textual`
first - which isort will arrange, since `textual` sorts before `textual_wasm` - therefore
gets the platform driver and no amount of later configuration changes it.

conftest is imported before any test module, so doing it here makes the ordering hold for
every file regardless of its own import block. Without it, the suite passes as a whole and
fails when a single file is run on its own, which is the worst possible way for a constraint
like this to be enforced.
"""

import textual_wasm

# Named so the side effect is a stated dependency rather than an import that looks unused and
# invites deletion. Deleting it makes the whole suite pass and every single file fail alone.
BOOTSTRAPPED = textual_wasm.DRIVER_IMPORT_PATH
