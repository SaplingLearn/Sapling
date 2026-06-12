import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// Next 16 removed `next lint`, so linting now runs through the ESLint CLI
// (eslint 9 flat config) against this file. eslint-config-next 16 ships native
// flat-config arrays, so we spread them directly (this replaces the old
// `extends: ["next/core-web-vitals", "next/typescript"]`). Run with `npx eslint .`.
const eslintConfig = [
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      ".open-next/**",
      "out/**",
      "dist/**",
      "next-env.d.ts",
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    // Existing-debt ratchet: these rules currently have many violations across
    // the pre-CI codebase (notably eslint-config-next 16's newly-strict
    // react-hooks rules and pre-existing `any` usage). They are demoted to
    // WARN so the gate is green today and blocks *new* error-level violations,
    // rather than blocking every PR on legacy debt. Re-promote to "error" file
    // by file as the design/a11y waves clean these up. Tracked under #162.
    rules: {
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/immutability": "warn",
      "@typescript-eslint/no-explicit-any": "warn",
      "react/no-unescaped-entities": "warn",
      "@next/next/no-html-link-for-pages": "warn",
      "prefer-const": "warn",
    },
  },
];

export default eslintConfig;
