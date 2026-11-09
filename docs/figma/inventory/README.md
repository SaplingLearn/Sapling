# Sapling → Figma: screen × state inventory

Goal: every screen and every visual state of Sapling in Figma as **editable layers** wired into a **clickable prototype**.

Generated 2026-11-04 from the code (conditional rendering, hooks, Playwright specs) — each row cites `file:line`, the trigger to reach it deterministically, and the testid to anchor on.

| File | Scope | Table rows* |
|---|---|---|
| [01-dashboard-learn-tree.md](01-dashboard-learn-tree.md) | KnowledgeGraph, /dashboard, /learn (tutor), /tree | 104 |
| [02-quiz-study-notes-library.md](02-quiz-study-notes-library.md) | /quiz, /study, /flashcards, /notetaker, /library + upload modal | 108 |
| [03-gradebook-calendar-social.md](03-gradebook-calendar-social.md) | /gradebook (+course, Gradescope), /calendar, /course-planner, /achievements, /social, /profile, ManageCourses | 70 |
| [04-settings-admin-preshell-chrome.md](04-settings-admin-preshell-chrome.md) | /settings, /admin (10 tabs), /admin/analytics, onboarding, pending, setting-up, auth, shell nav, global modals/toasts, **UI primitives** | 59 |
| [05-public-pages.md](05-public-pages.md) | Landing (scroll acts, feature lab, modals), about, careers, faq, gallery, news, legal, wiki | 33 |

\*Many rows bundle variants (`a / b / c`), so distinct frames ≈ **550–650** at desktop, before mobile.

## Figma file structure (proposed)
- `00 Foundations` — color/type/spacing variables (two scopes: warm app shell, cool landing + warm companion)
- `01 Components` — the primitives in 04 (Button, Chip, Badge, Toggle, Switch, SegmentedControl, AnswerOption, Pill, EmptyState, InlineBanner, Dialog, Sheet, Toast, Skeletons, CustomSelect, Avatar) + shell nav
- One page per area: `Dashboard`, `Tutor`, `Tree`, `Quiz`, `Study & Flashcards`, `Notes`, `Library & Upload`, `Grades`, `Calendar`, `Achievements`, `Social & Profile`, `Settings`, `Admin`, `Onboarding & Auth`, `Landing`, `Public pages`
- Frames named `Area / state-id / Desktop|Mobile`, one row per flow, left→right in transition order
- Prototype: hotspots from each file's **Transitions** list; nav links wired once on the shell component

## Capture pipeline (next step)
Extend `make gallery-shots` (showcase seed + showcase handlers, one flock'd up→capture→down cycle) into a full spec that walks the state ids: seed users for populated, `page.route` mocks for empty/error/loading (pattern `e2e/quiz-errors.spec.ts`), localStorage switches for layout/mode variants. Each reached state is pushed to Figma as editable layers (Figma `generate_figma_design` capture of the live page), then hotspots are wired.

## Decisions (2026-11-04)
1. **Desktop only** (1440×900). All `*-mobile*` / `*-phone*` / `*-tablet*` rows are out of scope.
2. **Show the app as-is.** States that don't exist in code are NOT designed; they're logged in the "Missing states" list below.
3. **Native browser dialogs are left out** (delete-account prompt, Gradescope/calendar/upload confirms, alert).
4. **Figma file lives in the LA-Hacks team** (Full seat) for now.
5. Hypothetical states (careers hiring/apply — `JOBS = []`) are out of scope, per (2).

## Missing states (exist in no code path — noted, not designed)
- Tree: no error state (load failure renders as empty).
- Settings: load failure = skeleton forever, no error UI.
- Library / Study / Flashcards / Notetaker: load failures render the empty state; notetaker create/link/unlink failures have no UI.
- Knowledge graph (dashboard, learn rail, tree): no empty-state copy — blank canvas.
- Dashboard: error banner only on first-load failure with no cached data.
- 404: Next.js default page, unbranded, no Sapling chrome.
- Public pages: no mobile menu.
- Admin users: empty table has no empty-state copy.
- /admin/analytics: no in-app entry point.
- Avatar menu / notifications: don't exist anywhere.

## Bugs / oddities surfaced (worth issues)
- Companion "Sign In" → `/?signin=1` doesn't open the sign-in modal; middleware `/?error=<code>` shows no error (05).
- Landing explore "Ask the tutor" opens the Notetaker lab, not the Tutor lab (`app/(public)/page.tsx:165`) (05).
- `AchievementUnlockWatcher` only mounts in the sidebar layout — top-nav/mobile users never get unlock toasts (04).
- Settings load failure = skeleton forever; Settings tab rail is a fixed 200px column on phones (04).
- Dashboard "Personal best" always equals the current streak (01).
- Showcase can't be filled from the UI (no "feature" action) (03).
- Possible double toast on upload failure (02).
- LetterScaleEditor "Reset to default" stays open (03).
- Social: `<RoomChat>` isn't keyed by room — a slow messages fetch for the auto-selected first room can overwrite the room you switched to (found while capturing).
- Floating "Report" button overlaps the tutor rail's "Add concept" button at 1440×900 (found while capturing).

## Status (2026-11-05)
- Figma file: https://www.figma.com/design/ToiUnUgkl5xMYvaLAqzXfr (LA-Hacks team), one page, 45 sections in a masonry grid; frame name == state id.
- **722 / 722** desktop states captured as editable layers (`scripts/figma-capture.sh`, recipes in `frontend/e2e/figma/recipes/`).
- Prototype: 12,690 click hotspots from `docs/figma/prototype-links.json` (sidebar nav on every app frame, public header/footer, in-flow transitions); 62 labels unmatched (mostly the control isn't visible in that particular state). Flow starting points: App — Dashboard, Public site — Landing, Onboarding, Admin.
- Re-run a subset: mint 1+ capture id (Figma MCP `generate_figma_design`), then `FIGMA_WORKERS=4 scripts/figma-capture.sh --pool <ids.json> <states.json> <promptId>` — submits chain on `nextCaptureId`; unused minted ids expire within hours.
