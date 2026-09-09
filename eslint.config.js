// Flat config covering both halves of this project's JavaScript surface.
//
// CSS block: PC-4 (no !important), PC-5 (layers, selector depth), PC-8 (logical
// properties), PC-9 (nothing single-engine load-bearing).
// JS block: the standing plugin set - sonarjs, unicorn, security.
import { defineConfig } from "eslint/config";
import css from "@eslint/css";
import js from "@eslint/js";
import globals from "globals";
import security from "eslint-plugin-security";
import sonarjs from "eslint-plugin-sonarjs";
import unicorn from "eslint-plugin-unicorn";
import { tailwind4 } from "tailwind-csstree";

export default defineConfig([
  {
    files: ["**/*.mjs", "**/*.js"],
    ignores: ["node_modules/**"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.node, ...globals.browser },
    },
    // The shared configs below register their own plugins; redeclaring them is an error.
    extends: [
      js.configs.recommended,
      sonarjs.configs.recommended,
      unicorn.configs.recommended,
      security.configs.recommended,
    ],
    rules: {
      // The harness and the page are scripts with a single entry point; a top-level
      // `main()` plus module-scope constants is the clearest shape for them.
      "unicorn/prefer-top-level-await": "off",
      "unicorn/no-null": "off",
    },
  },
  {
    files: ["**/*.css"],
    language: "css/css",
    plugins: { css },
    extends: ["css/recommended"],
    languageOptions: { customSyntax: tailwind4 },
    rules: {
      // "widely" for public sites with a long tail of old installs.
      "css/use-baseline": ["error", {
        available: "newly",
        // Deliberate Tier-3 enhancements. Each must degrade gracefully;
        // every addition to this list is a decision, not a convenience.
        allowProperties: ["text-box", "text-box-trim", "text-box-edge"],
        allowPropertyValues: { "text-wrap-style": ["pretty"] },
      }],
      "css/no-important": "error",
      "css/prefer-logical-properties": "error",
      "css/use-layers": "error",
      "css/selector-complexity": ["error", { maxCompounds: 2, maxTypes: 1 }],
      // Tokens live in their own file, and the rule resolves custom properties per-file,
      // so every var() reference across a split stylesheet reads as an unknown variable.
      // The property-name and value checks are the part worth keeping.
      "css/no-invalid-properties": ["error", { allowUnknownVariables: true }],
      "css/no-duplicate-imports": "error",
      "css/relative-font-units": ["error", { allowUnits: ["rem"] }],
      "css/font-family-fallbacks": "error",
    },
  },
]);
