/**
 * Check that `explainInstallFailure` rewrites the shapes micropip actually produces.
 *
 * A separate harness rather than an assertion inside the page, because the thing under test
 * is a pure function and running the whole boot sequence to exercise it would make a fast
 * check slow and a clear failure ambiguous.
 *
 * The inputs are verbatim micropip messages, captured from real failed installs: a pin that
 * excludes Pyodide's bundled tree-sitter, a distribution that is not on PyPI at all, and a
 * requirement that contradicts one already in the closure.
 */

import { explainInstallFailure } from "../assets/boot.mjs";

const CASES = [
  {
    name: "a pin excluding a bundled native wheel",
    input:
      "ValueError: Can't find a pure Python 3 wheel for 'tree-sitter>=0.25.0'.\n" +
      "See: https://pyodide.org/en/stable/usage/faq.html\n" +
      "You can use `await micropip.install(..., keep_going=True)` to get a list of all packages with missing wheels.",
    expect: ["tree-sitter>=0.25.0", "native wheel", "textual-wasm doctor"],
  },
  {
    name: "a distribution that is not on PyPI",
    input:
      "ValueError: Can't fetch metadata for 'textual-effects'. Please make sure you have " +
      "entered a correct package name and correctly specified index_urls (if you changed them).",
    expect: ["textual-effects", "git repository", "vendored"],
  },
  {
    name: "a requirement that contradicts the closure",
    input:
      "ValueError: Requested 'markdown-it-py[linkify,plugins]<3.0.0,>=2.1.0', but " +
      "markdown-it-py==4.2.0 is already installed.",
    expect: ["markdown-it-py", "closure", "textual-wasm doctor"],
  },
  {
    name: "anything else is passed through rather than swallowed",
    input: "ValueError: something nobody anticipated",
    expect: ["something nobody anticipated"],
  },
];

const failures = [];
for (const testCase of CASES) {
  const actual = explainInstallFailure(new Error(testCase.input));
  for (const fragment of testCase.expect) {
    if (!actual.includes(fragment)) {
      failures.push(`${testCase.name}: expected ${JSON.stringify(fragment)} in ${JSON.stringify(actual)}`);
    }
  }
}

// The misleading phrase is the whole reason this function exists; it must not survive.
const rewritten = explainInstallFailure(new Error("Can't find a pure Python 3 wheel for 'x>=1'"));
if (rewritten.includes("pure Python 3 wheel")) {
  failures.push("the misleading phrase was passed through unchanged");
}

console.log(JSON.stringify({ checked: CASES.length, failures }));
if (failures.length > 0) {
  // Thrown rather than `process.exit`: a non-zero status is what the caller checks, and an
  // uncaught throw supplies one without pretending this is a CLI.
  throw new Error(`${failures.length} case(s) failed`);
}
