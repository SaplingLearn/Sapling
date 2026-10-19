# Pen onboarding and desktop navigation

The old five-screen onboarding did not implement the approved redesign. This change implements the six screens under **NEW REDESIGN / 05 / Onboarding** and keeps the shared desktop sidebar. Learn and Tutor continue to use the same learning controller and session.

The onboarding work originally reviewed in [#731](https://github.com/SaplingLearn/Sapling/pull/731) is now integrated directly into [#728](https://github.com/SaplingLearn/Sapling/pull/728), on `feat/redesign-integration`. Review and merge the combined redesign through #728, which targets `main`; onboarding no longer needs a separate stacked PR. The existing #673/#727 dependencies documented in #728 still apply.

## Design source

The source is the active `Sapling-Complete-Wireframes.pen` file, [shared in Pen](https://app.pen.dev/s/sxEA2n5Ikk7KWUOanWPghMWYFFS0SbPgbkwkIm9dLYA). These source images were freshly exported through the native Pen MCP on October 19, 2026, without reading or modifying the encrypted document. [The export manifest](onboarding-source/manifest.json) records native frame IDs, dimensions and image hashes.

| Screen | Native Pen node | Desktop source | Production browser |
| --- | --- | --- | --- |
| 1. Profile | `km1LR` | [1440 × 960](onboarding-source/km1LR.png) | [Profile](onboarding-review/01-profile-desktop.png) |
| 2. Academic context | `n3xUk` | [1440 × 960](onboarding-source/n3xUk.png) | [Academic context](onboarding-review/02-academics-desktop.png) |
| 3. Courses | `X0pxMA` | [1440 × 960](onboarding-source/X0pxMA.png) | [Courses](onboarding-review/03-courses-desktop.png) |
| 4. Materials | `F4WT9A` | [1440 × 960](onboarding-source/F4WT9A.png) | [Materials](onboarding-review/04-materials-desktop.png) |
| 5. Goal | `R388oC` | [1440 × 960](onboarding-source/R388oC.png) | [Goal](onboarding-review/05-goal-desktop.png) |
| 6. Check-in review | `rbWgL` | [1440 × 960](onboarding-source/rbWgL.png) | [Check-in review](onboarding-review/06-review-desktop.png) |

Additional production captures show the [320px phone review](onboarding-review/06-review-phone-320.png), the [shared desktop sidebar after onboarding](onboarding-review/07-check-in-sidebar-desktop.png), and [recovery into the selected non-default course](onboarding-review/08-recovered-math-check-in-desktop.png). They come from the isolated browser journeys, not a production deployment.

The six onboarding frames are standalone cream canvases: they do **not** contain a sidebar. The post-onboarding application retains #728's latest sidebar iteration: sage background, smaller authored wordmark and icons, Home / Learn / Knowledge / Library / Tutor / Calendar, a collapse control, and Settings/profile at the bottom. Existing additional tools remain in its More disclosure, with their feature flags intact. Learn and Tutor links preserve the current course while changing the view. The standalone onboarding geometry remains the approved Pen geometry.

At 1440 × 960 the onboarding progress track begins at `(440, 110)`, is 560px wide, and the Aleo 40px/600 heading begins at y=202. The main action is 560 × 52px at `(440, 832)`. The form uses the native cream/sage/olive palette, Aleo and SUSE fonts, and existing approved SVG assets. Larger content and editing/error states scroll rather than hiding controls. The phone layout remains usable; this PR's fidelity target is desktop.

After integration, #728 applies its shared `--sapling-text-*` roles to onboarding as well as Home, Learn, Tutor and Library. The desktop page title remains 40px at 1440px; other text follows the shared roles. The source exports remain unchanged for comparison, while browser captures reflect the combined branch.

## Behavior and honest state

- Profile and course enrollment use the existing APIs. Completion requires a successful profile response and enrollment/account readback; partial saves retain choices and explain missing enrollments.
- Drafts belong to the confirmed cookie-backed user. Back and refresh preserve required and optional setup separately. Old unscoped drafts are not adopted by another account.
- Materials use the existing streaming upload pipeline, validation, per-file course assignment, cancel/retry and progress states. Saved rows use real document IDs and confirmed deletion. Course assignment occurs before upload; the saved row shows the confirmed course read-only because the existing API does not reassign saved documents. File size is shown only when actually known from the upload.
- Major/minor controls retain the existing free-text list contract. Suggestions are examples, not a fabricated complete university catalog.
- Goal scope is the whole course or 1–12 explicitly selected real concepts. Whole-course exploration has no focused objective; selected concepts carry the learner's exact objective, capped at 500 characters. Text does not infer target IDs.
- The final Start check-in click creates a user-scoped pending learning intent. The learning controller revalidates enrollment and concept ownership before starting with that scope, and discovers existing sessions before offering resume or confirmed wrap-up/new. It never silently overwrites a teaching goal.
- A start response can represent a lazy opener that is not yet in the database. Its accepted session ID stays with the pending intent until the first successful probe persists it. Refresh and retry recover that same opener rather than starting a second or default-course session.
- After the pending intent is consumed, the canonical `/learn?course=<id>` URL retains the course across repeated refreshes and Tutor view changes. Transient resume/topic/mode instructions are consumed separately.
- Merely viewing or refreshing the onboarding review does not probe, grade, plan or create a learning session. Plans still require explicit approval after diagnosis.

The handoff's copy corrections are retained: local draft persistence is distinguished from account saves, and the goal action says **Confirm goal & continue**, rather than implying a draft has already been saved as an active learning goal. Source example names, course codes, file names and goal text are replaced by actual user/API data.

## Verification

The existing frontend lint, TypeScript, unit and production-build checks are required. The unchanged backend is checked with the repository's CI pytest selection. New focused tests cover draft validation, catalog request races, partial save/readback, account switching, storage failure, goal ownership, duplicate starts, lazy-opener recovery and the new navigation.

`frontend/e2e/onboarding.spec.ts` uses the repository's isolated seeded database and deterministic model seam. It walks all six desktop screens through a real upload and goal-bearing learning session; exercises refresh, Back and duplicate-start protection; and checks catalog/profile failures at 320px. The browser test also compares the desktop geometry and authored typography to the Pen source. The additional cross-surface regression set covers feature flags, Library uploads, studio/tutor continuity and course context.

The combined branch passes the standard production build, full frontend suite (1,764 passed; 2 existing skips), and 15 browser journeys across onboarding, dashboard, feature flags, upload and Learn/Tutor continuity. Dashboard Escape tests wait for the overlay's initial focus before sending the key; their close and focus-return assertions remain intact. Sidebar checks cover the current 112px wordmark, compact rows and collapse/expand behavior.

Actual run results and GitHub checks are recorded in #728. Integration checks use a separate local test stack; the existing onboarding preview and pilot remain available. No production database is used, no CI gate is weakened, and merging #728 to main is a separate action. Deterministic browser tests verify the application wiring; they do not establish real-model teaching quality or learning outcomes.
