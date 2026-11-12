import fs from "node:fs";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// Files that still hold a function over the complexity limit, read from the
// ratchet's baseline (complexity-baseline.json, keys `<file>::<function>`).
const complexityBaselinedFiles = [
  ...new Set(
    Object.keys(
      JSON.parse(fs.readFileSync(new URL("./complexity-baseline.json", import.meta.url), "utf8"))
        .complexity,
    ).map((key) => key.split("::", 1)[0]),
  ),
].sort();

// The file-size limit, and the files already over it with the line count each
// may not pass (max-lines-baseline.json, see scripts/max_lines_ratchet.mjs).
const MAX_LINES = { max: 800, skipBlankLines: true, skipComments: true };
const maxLinesBaseline = JSON.parse(
  fs.readFileSync(new URL("./max-lines-baseline.json", import.meta.url), "utf8"),
)["max-lines"];

// Bulk suppressions can only baseline a rule that is an ERROR, and CI runs
// with --max-warnings=0, so a rule left at "warn" has no baseline: the day a
// dependency bump adds one (eslint-config-next does, in minor releases), its
// hits in files already on main turn CI red with no way to hold them. Every
// "warn" is therefore promoted to "error" below, where the whole config is
// exported. To take on such a rule: `npx eslint . --suppress-rule <rule>`.
const isWarn = (severity) => severity === "warn" || severity === 1;
function promoteWarnings(block) {
  if (!block.rules) return block;
  const rules = Object.entries(block.rules).map(([id, setting]) => {
    if (Array.isArray(setting)) return [id, isWarn(setting[0]) ? ["error", ...setting.slice(1)] : setting];
    return [id, isWarn(setting) ? "error" : setting];
  });
  return { ...block, rules: Object.fromEntries(rules) };
}

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
      // exhaustive-deps is warn-by-default in eslint-config-next; an error
      // here so a NEW missing dependency fails CI (the existing ones are
      // baselined). It's the rule most likely to fire on an intentional
      // pattern: if that starts forcing eslint-disable comments on legitimate
      // cases, turn THIS single rule off (a "warn" would be promoted back to
      // an error, see promoteWarnings).
      "react-hooks/exhaustive-deps": "error",
      // Architecture-hardening Phase 4 (Trov #118): no function above
      // cyclomatic complexity 25. Today's offenders are held per function by
      // the ratchet (scripts/complexity_ratchet.mjs, two blocks down), not by
      // eslint-suppressions.json.
      complexity: ["error", 25],
      // File size: the big screens (Learn, notetaker, Social, ...) passed 1,500
      // to 2,700 lines with nothing stopping them. A NEW file over the limit
      // fails here. The files already over it are held to their own line
      // count by the generated blocks below (max-lines/ratchet-baselined), not
      // by eslint-suppressions.json: the rule reports once per file, so a
      // suppressed file could keep growing. Tests are exempt (below): long
      // table-driven suites are fine.
      "max-lines": ["error", MAX_LINES],
      // The codebase's convention for an intentionally unused binding is a
      // leading underscore (`predictedPercent: _predictedPercent`).
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
        },
      ],
      // Every <img> here is a user upload, a blob: preview or a markdown image
      // with an unknown size, and the Workers deploy (OpenNext) has no image
      // optimizer configured, so next/image would not help and could break
      // them. Off rather than left as permanent warning noise.
      "@next/next/no-img-element": "off",
    },
  },
  {
    name: "max-lines/tests-exempt",
    files: ["**/*.test.ts", "**/*.test.tsx", "e2e/**", "scripts/**"],
    rules: { "max-lines": "off" },
  },
  // Generated from max-lines-baseline.json at load: each file already over the
  // limit gets its own ceiling, its line count when it was baselined, so it
  // cannot grow. `npm run max-lines:shrink` lowers a ceiling after a split and
  // deletes the entry once the file is back under the limit; the ratchet
  // (scripts/max_lines_ratchet.test.ts in `npm test`) checks the same numbers
  // with inline eslint-disable comments ignored. Do not edit this list; edit
  // the baseline.
  ...Object.entries(maxLinesBaseline).map(([file, ceiling]) => ({
    name: `max-lines/ratchet-baselined/${file}`,
    files: [file],
    rules: { "max-lines": ["error", { ...MAX_LINES, max: ceiling }] },
  })),
  // The landing-page animation engine is exempt from the complexity limit by
  // decision of its owner (Trov #118 phase 4): it is frame-loop and physics
  // code for the marketing hero, where one long tick function is clearer than
  // a split. The ratchet skips the same glob (EXEMPT_GLOB).
  {
    name: "complexity/landing-engine-exempt",
    files: ["src/lib/landing/engine/**"],
    rules: { complexity: "off" },
  },
  // Generated from complexity-baseline.json at load: `complexity` is off for
  // every file that still holds a baselined function, because ESLint can only
  // switch a rule off per file. The ratchet (`npm run complexity`, enforced by
  // scripts/complexity_ratchet.test.ts in `npm test`) holds each of those
  // functions to its own ceiling instead, and any NEW function over 25 in
  // them. This block shrinks to nothing as entries are deleted: once a file's
  // last entry goes (`npm run complexity:shrink`), plain `eslint .` enforces
  // the limit on it again. Do not edit this list; edit the baseline.
  ...(complexityBaselinedFiles.length
    ? [
        {
          name: "complexity/ratchet-baselined",
          files: complexityBaselinedFiles,
          rules: { complexity: "off" },
        },
      ]
    : []),
  // ── data-testid convention on the core E2E surfaces (#382) ───────────────
  //
  // The browser suite (#385) drives six surfaces: sign-in, the approval gate,
  // the upload modal, the tutor composer, the quiz answer flow, and the graph
  // container. Those tests must anchor on `data-testid`, never on CSS classes
  // or copy — both churn on every design pass.
  //
  // This block enforces the convention where it matters: any NEW `<button>`,
  // `<input>` or `<textarea>` added to one of the files that owns those
  // surfaces must carry a `data-testid`. It is deliberately NOT global — the
  // rest of the app is out of scope, and a repo-wide version would be noise.
  //
  // Naming rules live in `docs/frontend-testids.md`. When a new surface joins
  // the browser suite, add its owning file to `files` below.
  {
    files: [
      "src/components/marketing/SignInModal.tsx",
      "src/app/pending/page.tsx",
      "src/app/setting-up/page.tsx",
      "src/components/screens/Onboarding.tsx",
      "src/components/DocumentUploadModal.tsx",
      "src/components/TopicChecklistPanel.tsx",
      "src/components/chat/ChatPanel.tsx",
      // Quiz redesign (#537). The three screens carry every answer/submit/exit
      // control the Playwright journeys drive; the three `ui/` primitives are
      // listed because those controls render INSIDE them, so a testid-less
      // <button> there would silently un-anchor the whole surface.
      "src/components/quiz/QuizScreen.tsx",
      "src/components/quiz/home/QuizHome.tsx",
      "src/components/quiz/home/TopicsColumn.tsx",
      "src/components/quiz/home/AdjustDialog.tsx",
      "src/components/quiz/home/TopicList.tsx",
      "src/components/quiz/home/QuizSettings.tsx",
      "src/components/quiz/question/QuizQuestion.tsx",
      "src/components/quiz/question/WrittenAnswer.tsx",
      "src/components/quiz/question/AskPanel.tsx",
      "src/components/quiz/question/LeaveDialog.tsx",
      "src/components/quiz/results/QuizResults.tsx",
      "src/components/quiz/results/MissedList.tsx",
      "src/components/ui/AnswerOption.tsx",
      "src/components/ui/SegmentedControl.tsx",
      "src/components/ui/Sheet.tsx",
      "src/components/graph/KnowledgeGraph.tsx",
      "src/components/graph/KnowledgeGraph2D.tsx",
      "src/components/graph/KnowledgeGraph3D.tsx",
      "src/components/ShellFrame.tsx",
      "src/components/screens/Social.tsx",
      "src/components/screens/Dashboard.tsx",
      "src/components/screens/Learn.tsx",
      "src/components/screens/Library.tsx",
      "src/components/screens/Calendar.tsx",
      "src/components/screens/Gradebook/Landing.tsx",
      "src/components/screens/Gradebook/Course.tsx",
      "src/components/Gradebook/TranscriptModal.tsx",
      "src/components/Gradebook/CourseCard.tsx",
      "src/components/Gradebook/AssignmentList.tsx",
      "src/components/Gradebook/AssignmentModal.tsx",
      "src/components/screens/AdminAnalytics.tsx",
      "src/components/screens/Tree.tsx",
      "src/components/marketing/graph/KnowledgeGraphDemo.tsx",
      "src/components/marketing/FeatureBand.tsx",
      "src/components/marketing/SurfaceBento.tsx",
      "src/components/marketing/surfaces/GradebookSurface.tsx",
      "src/components/marketing/surfaces/NotesSurface.tsx",
      "src/components/marketing/surfaces/QuizSurface.tsx",
      "src/components/marketing/surfaces/ReviewSurface.tsx",
      "src/components/marketing/surfaces/RoomsSurface.tsx",
      "src/components/marketing/surfaces/Surface.tsx",
      "src/components/marketing/surfaces/TutorSurface.tsx",
      "src/components/marketing/surfaces/UploadSurface.tsx",
      "src/components/ProfileView.tsx",
      "src/components/screens/Achievements.tsx",
      "src/components/screens/achievements/HeroCard.tsx",
      "src/components/screens/achievements/LeaderboardTab.tsx",
      "src/components/screens/achievements/ActivityTab.tsx",
      // Admin "Feature flags" tab (#620). New file, no baselined backlog.
      "src/components/screens/admin/FeatureFlags.tsx",
      "src/components/screens/admin/FlagPanel.tsx",
      // Admin "Allowlist" + "Email" tabs (waitlist bulk approve, Resend broadcasts).
      // New files, no baselined backlog.
      "src/components/screens/admin/AllowlistTab.tsx",
      "src/components/screens/admin/EmailBroadcasts.tsx",
      // Admin "Account tools" dialog (seed / wipe / copy an account). New file,
      // no baselined backlog.
      "src/components/screens/admin/AccountToolsDialog.tsx",
      // Settings (#675 Data tab): NOT a no-backlog file — its pre-existing
      // controls are baselined in eslint-suppressions.json, so the rule
      // covers new elements only. Shrink that baseline as testids are added.
      "src/components/screens/Settings.tsx",
    ],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector:
            'JSXOpeningElement[name.name=/^(button|input|textarea)$/]:not(:has(JSXAttribute[name.name="data-testid"]))',
          message:
            "E2E surface (#382): every <button>/<input>/<textarea> in this file needs a data-testid. See docs/frontend-testids.md for the naming convention.",
        },
      ],
    },
  },
];

export default eslintConfig.map(promoteWarnings);
