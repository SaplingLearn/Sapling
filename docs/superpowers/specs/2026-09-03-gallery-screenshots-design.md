# Product screenshots for /gallery

**Status:** design, not yet implemented
**Date:** 2026-09-03

## The problem

`/gallery` promises "Every screen in Sapling, as it actually looks." It shows
twelve empty tinted panels with a route badge in the corner. There has never
been a screenshot behind any of them, and no process for producing one.

The same class of bug as #601: a surface whose content was assumed and never
supplied, where nothing fails when it is missing.

Twelve slots, in `GALLERY_SHOTS` (`frontend/src/lib/landing/companionContent.ts`):

| slot | route | slot | route |
|---|---|---|---|
| `shot-tree` | `/tree` | `shot-library` | `/library` |
| `shot-learn` | `/learn` | `shot-social` | `/social` |
| `shot-quiz` | `/quiz` | `shot-achievements` | `/achievements` |
| `shot-study` | `/study` | `shot-calendar` | `/calendar` |
| `shot-guide` | `/study` | `shot-gradebook` | `/gradebook` |
| `shot-notetaker` | `/notetaker` | `shot-planner` | `/course-planner` |

Every route exists under `src/app/(shell)/`. Note `shot-study` and `shot-guide`
share a route — a screenshot target is a *state*, not a URL, and the design has
to carry that.

## What already exists

Almost all of the hard part. This design adds a capture step to machinery that
is already deterministic, and deliberately does not rebuild any of it.

- **A booted, seeded, deterministic stack.** `make e2e-up` owns the contract:
  Supabase → migrate → seed → uvicorn on :5000 → test-profile Next build on
  :3000. `scripts/e2e-up.sh` already honours `SEED_RICH=0` to skip the rich
  seed, which is the hook a showcase seed substitutes into.
- **A frozen world.** The test-profile build bakes `NEXT_PUBLIC_TEST_MODE=1`:
  seeded PRNG and a clock frozen at 2026-03-11T12:00:00Z, with `timezoneId`
  pinned to America/New_York in `playwright.config.ts`. Re-running the capture
  produces the same pixels — the greeting says "Good morning", the calendar
  agrees with itself, and nothing is dated "today".
- **An LLM seam with a module-level selector.** `SAPLING_FUNCTION_HANDLERS`
  names a module whose import registers per-task handlers
  (`backend/agents/_providers.py`). `agents.function_handlers_e2e` is the
  existing one. A second module is a supported use of this seam, not a new one.
- **Harness sign-in.** `frontend/e2e/support/session.ts` mints a session via
  `POST /api/auth/test-login` (local/test only; 404s elsewhere).
- **A screenshot precedent.** `e2e/quiz-integration.spec.ts` has a
  `QUIZ_SHOTS`-gated test that sets a 1440×900 viewport, drives the app into
  specific states, waits for content to settle, and writes PNGs. This design
  generalises that test; it does not invent a pattern.

1440×900 is 16:10, which is exactly the `aspectRatio: '16 / 10'` the gallery
cards render at. Captures need no cropping.

## Design

### Showcase mode

The E2E stack is deterministic but *visibly synthetic*. Function-mode output
renders literal `[e2e-function-model]` strings and every summary is about
gradient descent — fine for assertions, unusable in a marketing gallery. Two
pieces fix it, and both are needed: the seed covers what the database holds,
the handlers cover what the model would have written.

**`backend/db/seed_showcase.py`** — a sibling of `seed_local_rich.py`.
Local-only, idempotent, `show-*` ids. Owns the text that reaches a screenshot
through the database: course and concept names, documents, notes, room
messages, assignments, scores, streaks. Fixes `/library`, `/gradebook`,
`/calendar`, `/social`, `/achievements`, `/tree`.

**It must also create the user the capture signs in as.** `SEED_RICH=0` skips
the rich seed, and the comment at `scripts/e2e-up.sh:228` says why that
matters: `/api/auth/test-login` needs seeded users to sign in as. Skipping the
rich seed removes the `rich-*` users the harness normally uses, so
`seed_showcase` owns a `show-user-*` with a display name worth photographing —
the dashboard greeting and every avatar render it. `mintStorageState` already
takes an arbitrary user id, so no harness change is needed.

**`backend/agents/function_handlers_showcase.py`** — selected with
`SAPLING_FUNCTION_HANDLERS=agents.function_handlers_showcase`. Owns the text
that reaches a screenshot through an agent: tutor turns, quiz stems and
options, note summaries, study-guide bodies. Fixes `/learn`, `/quiz`,
`/notetaker`, and the guide half of `/study`.

Neither alone produces a clean shot. `/quiz` reads its stems from a handler and
its concept name from the seed; a showcase seed with E2E handlers still
photographs `[e2e-function-model]`.

Both are local-only by the same rule as their siblings, and neither is
registered for the E2E lane — `function_handlers_e2e.py` stays the lane's
handler module, and its constants stay byte-matched to the spec assertions that
depend on them. **Showcase copy must never be written into
`function_handlers_e2e.py`**: those constants are load-bearing for
`tests/test_e2e_function_handlers.py` and the Chapter 1 journeys.

### Capture

**`frontend/e2e/gallery-shots.spec.ts`**, gated on `GALLERY_SHOTS_DIR` exactly
as the quiz shots test is gated on `QUIZ_SHOTS`. Unset, the normal lane
collects it and skips it for nothing.

It imports `base` from `@playwright/test` directly, **not** `test` from
`support/fixtures.ts`. That fixture's autouse `dbReset` truncates and re-seeds
the rich data before each test; inheriting it would wipe the showcase seed out
from under the run. This is the one place the capture spec deliberately steps
outside the lane's conventions, and the reason belongs in a comment on the
import.

Per shot, before capturing:

- `page.setViewportSize({ width: 1440, height: 900 })`
- `page.emulateMedia({ reducedMotion: 'reduce' })` — the app animates on mount
  (`fadeUp`, the graph's motion), and a shot taken mid-animation is a shot of a
  half-faded screen.
- `await page.evaluate(() => document.fonts.ready)` — Playfair and Spectral
  swap in late; capturing before they land photographs the fallback stack.
- The recipe's own settle assertion (below).

Capture is `fullPage: false` — a viewport shot, not a tall scroll. The gallery
card is a 16:10 window on a screen, not a page thumbnail.

### Recipes, and the contract with the content table

Recipes live in the spec, keyed by slot. They do **not** live in
`GALLERY_SHOTS`: that table is imported by a client component, and Playwright
steps in it would drag test code into the browser bundle.

```ts
type Recipe = (page: Page) => Promise<void>;
const RECIPES: Record<string, Recipe> = { /* one per slot */ };
```

The spec imports `GALLERY_SHOTS` and asserts the two agree — every slot has a
recipe, and every recipe names a real slot. This is the #601 discipline
applied again: two lists that must correspond, with one of them saying so, so
that adding a thirteenth card fails loudly instead of producing eleven
screenshots and no complaint.

A recipe's last act is an assertion that the screen is *ready*, not merely
loaded — `await expect(page.getByTestId('tree-canvas')).toBeVisible()` rather
than a bare `goto`. A settle assertion per recipe is what keeps this from
becoming a flaky screenshot generator. Testids come from
`docs/frontend-testids.md`.

`shot-study` and `shot-guide` are the worked example: same `goto('/study')`,
different tab clicked, different settle assertion.

### Output

`frontend/public/gallery/<slot>.png`, committed to the repo.

Twelve PNGs at 1440×900 is roughly 3–4MB against a `public/` that is 1.6MB
today. That is the real cost of this design and it is being named up front
rather than discovered in review. It is accepted because the alternative —
generating at build time — is not available: capture needs the whole stack
(Supabase, backend, seeded database) and CI image builds do not have one.

Source format is PNG because text stays crisp; the delivered format is
`next/image`'s business.

### Render

The gallery card already has the panel, radius, shadow and route badge. It
needs `next/image` under the badge:

```tsx
<Image src={`/gallery/${s.slot}.png`} alt="" fill sizes="(max-width: 900px) 100vw, 33vw"
       style={{ objectFit: 'cover' }} />
```

`alt=""` — the `<figcaption>` already names and describes the screen, so alt
text would be a duplicate announcement, not an addition.

### Guard

A vitest test beside `journalArticles.test.ts` that reads `public/gallery/` off
disk and asserts every `GALLERY_SHOTS` slot has a file. Node environment, no
browser.

This is the check that would have caught today's bug. Staleness — a shot that
exists but no longer looks like the product — stays a human call; a CI job that
re-captures and diffs would need the full stack on every run and would fail
every intentional redesign.

### Safety

The spec asserts its target is localhost before capturing anything. Capture
drives a signed-in session through real product surfaces, and the one thing
this must never do is photograph a real user's data on staging or production.
`test-login` already 404s outside local/test, so this is defence in depth
rather than the only guard — but a screenshot tool pointed at prod is worth
failing loudly and early.

## Files

| File | Status | Purpose |
|---|---|---|
| `backend/db/seed_showcase.py` | new | Showcase database rows, `show-*` ids |
| `backend/agents/function_handlers_showcase.py` | new | Showcase agent output |
| `frontend/e2e/gallery-shots.spec.ts` | new | Capture, recipes, slot contract |
| `scripts/gallery-shots.sh` | new | Boot showcase mode, run capture, tear down |
| `Makefile` | edit | `gallery-shots` target |
| `frontend/public/gallery/*.png` | new | Twelve committed screenshots |
| `frontend/src/app/(public)/gallery/page.tsx` | edit | Render the image |
| `frontend/src/lib/landing/gallery.test.ts` | new | Slot-has-a-file guard |

## Flow

```
make gallery-shots
  └─ scripts/gallery-shots.sh
       ├─ flock /tmp/claude-<uid>/sapling-e2e-stack.lock   (whole cycle, one invocation)
       ├─ SEED_RICH=0 SAPLING_MODEL_MODE=function \
       │  SAPLING_FUNCTION_HANDLERS=agents.function_handlers_showcase  make e2e-up
       ├─ (cd backend && venv/bin/python -m db.seed_showcase)
       ├─ (cd frontend && GALLERY_SHOTS_DIR=public/gallery \
       │     npx playwright test gallery-shots.spec.ts)
       └─ make e2e-down
```

The whole cycle is one `flock` invocation. The local stack is a machine
singleton and a separately-flocked teardown deadlocks — detached servers
inherit the lock fd. This is a documented trap in `CLAUDE.md`, not a
hypothetical.

## Failure modes

- **A recipe's settle assertion times out.** The run fails with that slot
  named. It does not write a partial or blank PNG — a missing file is
  recoverable, a committed screenshot of a loading spinner is not.
- **A new gallery card without a recipe.** The spec's contract assertion fails
  before any capture runs.
- **A new gallery card with a recipe but no committed file.** The vitest guard
  fails in CI.
- **The stack is not up.** `global-setup.ts` already health-checks and fails
  with "run `make e2e-up`". `scripts/gallery-shots.sh` boots it, so this is the
  path for someone running the spec by hand.
- **The showcase user is missing.** Sign-in fails at the first shot with
  test-login's own error. This is the failure `SEED_RICH=0` invites, and the
  reason the seed owns its user.
- **A bad `SAPLING_FUNCTION_HANDLERS` module path** raises ImportError at every
  dispatch by design (`_load_env_handlers_module`), so a typo fails the run
  rather than silently serving E2E copy.

## Testing

- The slot/recipe contract and the slot/file guard are the two automated
  checks, and they cover the two ways this silently rots.
- Capture itself is verified by running it: twelve files land, and they are
  reviewed by eye before commit. Screenshots are a visual artefact; asserting
  on their pixels would be asserting on the design, which changes on purpose.
- `seed_showcase.py` follows `seed_local_rich.py`'s idempotency contract and is
  exercised by running it twice.

## Decisions

- **Extend the existing seam rather than build a showcase stack.**
  `playwright.config.ts` carries an explicit warning against duplicating the
  boot contract that `make e2e-up` owns, and that contract has drifted before.
  A parallel stack buys isolation this does not need.
- **Showcase seed *and* showcase handlers.** Rejected "rich seed as-is"
  (photographs `[e2e-function-model]`) and "real Gemini" (costs calls, and
  output changes every run, so re-capture yields different screenshots — the
  determinism this whole design is built on).
- **Recipes in the spec, not the content table.** Keeps Playwright out of the
  browser bundle.
- **Committed PNGs.** Build-time generation is impossible without a stack.
- **Make target plus coverage test, not CI diffing.** Catches the missing-shot
  bug; leaves "does this still look like the product" to a person.

## Out of scope

- The landing page's gallery act. It uses hand-built animated miniatures
  (`galleryMinis.tsx`); replacing motion with stills would be a design
  regression, and it is a separate conversation.
- Light/dark or responsive variants. One shot per slot at 1440×900.
- Staleness detection beyond "the file exists".
- `/careers`, `/privacy`, `/terms` — unrelated to the gallery, and still off
  `CompanionShell` entirely.
