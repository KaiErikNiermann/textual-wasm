# Feasibility study

The architecture audit this project started from, and what the implementation measured against
it. It is kept in its original form — including the claims that turned out to be **wrong**,
corrected in place and marked, because a study that quietly edits its mistakes is not evidence
of anything.

Of particular note:

- **§5** — the SharedArrayBuffer correction. The most load-bearing error in the document: it
  made an unavailable feature look like a deployment-header problem.
- **§11** — what the spike measured, and four findings that contradicted the audit.
- **§12** — render equivalence, including the case where the *reference implementation* was
  the wrong one.
- **§13** — the WASM Component Model, assessed and closed with reasons.
- **§14** — Textual's own demo as the acceptance case, and the two bugs it found.

```{include} ../textual-wasm-feasability-study.md
:start-line: 1
```
