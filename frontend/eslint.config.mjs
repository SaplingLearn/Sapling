import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// Next 16 removed `next lint`, so linting runs through the ESLint CLI (eslint 9
// flat config). eslint-config-next 16 ships native flat-config arrays, spread
// directly here (this replaces the old
// `extends: ["next/core-web-vitals", "next/typescript"]`). Run with `npx eslint .`.
//
// Legacy debt is handled by an ESLint *bulk-suppressions* baseline
// (eslint-suppressions.json), NOT by downgrading rules. Every rule keeps its
// configured severity, the pre-CI violations are baselined once, and any NEW
// violation fails CI (eslint reads the suppressions file automatically). When
// the violation count legitimately changes, regenerate it with
// `npm run lint:baseline` (see package.json) so a shifted count isn't a spurious
// CI failure.
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
    rules: {
      // exhaustive-deps is warn-by-default in eslint-config-next; promote it to
      // error so a NEW missing dependency fails CI (the existing ones are
      // baselined). It's the rule most likely to fire on an intentional pattern
      // — if that starts forcing eslint-disable comments on legitimate cases,
      // downgrade THIS single rule back to "warn" (don't relax the others).
      "react-hooks/exhaustive-deps": "error",
    },
  },
];

export default eslintConfig;
