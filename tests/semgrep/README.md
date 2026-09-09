# Semgrep rule fixtures

A pattern rule that matches nothing is indistinguishable from a clean codebase, so every rule
in `.semgrep/` must demonstrate that it still fires. `tests/test_semgrep_rules.py` scans both
directories here and asserts that:

* every rule id defined in `.semgrep/` fires at least once against `positive/`; and
* nothing fires against `negative/`, which holds the legitimate shapes each rule is most
  likely to be over-eager about.

`positive/` mirrors the real `src/textual_wasm/` layout because several rules are scoped with
`paths.include`, and a fixture outside those paths would be silently skipped - which is the
exact failure this suite exists to prevent.

The code in `positive/` is deliberately wrong and is excluded from ruff, pyright and the
project semgrep run.
