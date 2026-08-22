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
      "src/components/screens/Onboarding.tsx",
      "src/components/DocumentUploadModal.tsx",
      "src/components/chat/ChatPanel.tsx",
      "src/components/QuizPanel.tsx",
      // Quiz redesign (#537). The three screens carry every answer/submit/exit
      // control the Playwright journeys drive; the three `ui/` primitives are
      // listed because those controls render INSIDE them, so a testid-less
      // <button> there would silently un-anchor the whole surface.
      "src/components/quiz/QuizScreen.tsx",
      "src/components/quiz/home/QuizHome.tsx",
      "src/components/quiz/question/QuizQuestion.tsx",
      "src/components/quiz/results/QuizResults.tsx",
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

export default eslintConfig;
