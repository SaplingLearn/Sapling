# Landing page — everything below the hero

Design for #344 (`[p1] frontend PRIORITY - Landing page redesign`), phase 2.
Phase 1 was 8fb7949, which deleted unreachable effects and orphaned CSS.

## Problem

Below the hero, the landing page currently runs a 340vh scroll-jacked
`HowItWorks` (677 lines of framer-motion, a Seed→Sprout→Tree metaphor over a
mocked `AppWindow`), then a six-row hairline feature catalog, then a CTA and
footer.

#344 names five complaints. Restated as causes rather than symptoms:

1. The graph — the product's actual differentiator — is a **movie you watch**,
   not a thing you touch.
2. The features describe **generic capabilities**, not the pages Sapling
   actually ships.
3. The section carries scaffolding that exists to explain the scaffolding: a
   left-side step indicator, "drag"/"scroll" hint copy, per-step preview
   buttons.
4. It doesn't look impressive enough to hold a visitor.
5. It "feels generic," with nothing that could only be Sapling.

Point 5 is the one worth restating: **the page undersells the product more than
it under-designs it.** Tutor chat, Notes, Gradebook and Flashcards are all
shipped surfaces that the current six-feature list never mentions. Fixing that
does more for "feels generic" than any amount of new motion.

## Goals

- Make the knowledge graph manipulable, with the explanatory copy receding as
  the visitor engages.
- Present real Sapling surfaces instead of abstract capability names.
- Delete the scaffolding #344 lists.
- Keep the page fast and crawlable — this is the most-indexed surface on the
  site.

## Non-goals

- The hero, nav, and intro overlay are **untouched**. So are the sign-in and
  beta/newsletter modals.
- No live LLM generation on the public page (see Rejected alternatives).
- No backend work. Every graph in this design is a static fixture.

## Architecture

Hero (unchanged)
1. Interactive graph
2. Band — Universal Upload
3. Band — Adaptive quizzes
4. Bento — Tutor chat, Notes, Study Rooms, Gradebook
5. Band — knows what to review, and when
6. CTA
7. Footer (kept, tightened)

The ordering is a density rhythm: the graph is the densest thing on the page,
two bands decompress, the bento re-energizes, and the final band closes on a
claim so the CTA has a run-up. A grid's last tile is a weak place to ask for a
signup.

The three bands carry one arc — **material in → practice → retention** — rather
than three disconnected pitches. Band surfaces alternate sides.

### 1. Interactive graph

Replaces `HowItWorks` entirely. Roughly full-viewport, below the fold.

- Three course chips (`CS 210`, `MA 242`, `SM 275`). Picking one animates that
  course's concept graph into existence, node by node.
- Once assembled: drag nodes, hover for a concept blurb, click a node to expand
  its children.
- The instructional copy fades as the visitor interacts — the fade is driven by
  first interaction, not by a timer.
- No side step indicator, no "drag me" hint, no per-step buttons.

Data is a static fixture module — three hand-authored course graphs, each a
`{nodes, edges}` shape mirroring the real `graph_nodes` / `graph_edges`
semantics (mastery tiers included, so the colour language matches the app and
the hero legend).

### 2, 3, 5. Bands

Full-width. One built product surface on one side, copy on the other,
alternating. Surfaces are recreated in-page in the hero's liquid-glass
language — not screenshots. The repo has no product screenshots, and the hero
already recreates surfaces this way (`CS 101 · 55% mastered`, the mastery
legend, `Total nodes 2,413`), so this stays consistent, themeable, and
responsive.

| Band | Surface | Claim |
|---|---|---|
| 2 | Upload / extraction | syllabus, textbook, lecture notes → concepts on your graph |
| 3 | Quiz | presses where you're strong, meets you where you struggle |
| 5 | Review scheduling | knows what to review, and when |

Band 5 folds together what are today two separate features (Adaptive Study
Paths, Spaced Repetition) — they make one claim, not two.

### 4. Bento

Asymmetric grid, four tiles, varying sizes: **Tutor chat**, **Notes**,
**Study Rooms**, **Gradebook**. Static surface recreations; no per-tile buttons.

Flashcards and the knowledge graph are deliberately out — the graph is section 1,
and Flashcards is the surface you'd least lead with.

### 6, 7. CTA and footer

CTA keeps its current copy and `startOnboarding` behaviour. Footer keeps its
links and credit line; spacing tightened to match the new rhythm.

## Component boundaries

`(public)/page.tsx` is already ~935 lines and would grow. New work lands in
`components/marketing/` as focused files, imported by `page.tsx`:

- `KnowledgeGraphDemo/` — the interactive graph. Split so the canvas/SVG
  renderer, the layout+animation logic, and the fixture data are separately
  readable and testable.
- `FeatureBand.tsx` — presentational; takes a side, copy, and a surface node.
- `SurfaceBento.tsx` — the four-tile grid.
- `surfaces/` — the in-page product recreations (upload, quiz, review, tutor,
  notes, rooms, gradebook), each self-contained.

`HowItWorks.tsx` is deleted, along with its `next/dynamic` import and the
340vh placeholder in `page.tsx`.

## Motion

**The helix fires once.** #344 asks for "3D helix animations"; the budget is
spent in a single place — nodes arriving along a helical path as the graph
assembles after a course chip is picked. That is a real 3D helix, at the exact
moment the page makes its argument. Bands and bento get quiet entrance
transitions only.

Scattering helix motifs through every section is how a page becomes generic
rather than less so, and the hero already runs a full canvas RAF loop directly
above this.

**Reduced motion and test mode.** The graph parks on a static, fully-laid-out
frame under `prefers-reduced-motion: reduce` and under `IS_TEST_MODE`, matching
how the hero canvas already behaves. A parked graph must still be *complete* —
laid out and readable, not blank. Any randomness routes through
`lib/testMode`'s `random()` / `now()` so the E2E lane is deterministic.

## Performance

- The graph component lazy-loads via `next/dynamic` below the fold, following
  the existing `HowItWorks` precedent — but with SSR **kept** so crawlers still
  receive the section's marketing copy, which is why the current code avoids
  `ssr: false`.
- Its RAF loop must not start until the section is near the viewport, and must
  stop when it leaves. The hero's canvas is already running above it.
- Placeholder height must match the resolved section height so nothing below
  shifts during chunk load (CLS).

## Styling

Everything is scoped under `.landing-page`, which re-declares the same token
names as the warm app shell (`docs/frontend-rhythm-audit.md`). New CSS must be
added inside that scope and must not leak token redefinitions outward — this is
the documented cause of the "get-started/beta feels off" class of bug.

## Testing

- **Unit/vitest**: fixture graph shape (every edge references a real node; no
  orphans), band alternation, reduced-motion parking.
- **Testids**: new interactive surfaces need a prefix registered per
  `docs/frontend-testids.md` §"Adding a surface" — add the row, add the owning
  file to the lint block's `files` array, and run `npm run lint`, which
  enumerates interactive elements still missing testids.
- **E2E journey** (`frontend/e2e/`, fixtures-based `test` from
  `support/fixtures.ts`): the landing page renders the graph section; picking a
  course chip assembles a graph; interacting fades the instructional copy; the
  page still routes to onboarding from both CTAs. Auto-waiting `expect` only,
  no timeouts.
- `public-seo.spec.ts` already asserts the landing page ships social cards and a
  canonical URL — it must stay green, which is the guard on not breaking SSR.

## What gets deleted

- `components/marketing/HowItWorks.tsx` (677 lines) and its dynamic import
- Seed / Sprout / Tree SVG components and the `AppWindow` mock
- the left-side step indicator, drag/scroll hint copy, per-step preview buttons
- the six-row hairline feature catalog and its "— end of catalog" rule
- any CSS in `globals.css` left orphaned by the above

## Rejected alternatives

**Live generation on the public page.** Letting a visitor type any topic and
generating a real graph is the most convincing option — it *is* the product
rather than a picture of it. Rejected for now: it puts an unauthenticated,
billable LLM endpoint on the most-crawled page on the site, with real cost,
rate-limiting, prompt-abuse and slow-Gemini failure modes. It is a strong second
pass once the section exists and can sit behind a hardened, rate-limited
endpoint.

**Sticky rail with a swapping panel.** Compact, but it is a left-side index that
scroll-drives a panel — close to the "left side page indication" #344 explicitly
asks to remove.

**Straight to bento after the graph.** Rejected on pacing: the graph is dense
and immersive, and a dense grid immediately after gives the eye nowhere to rest.

**Screenshots for the feature surfaces.** No product screenshots exist in the
repo, and in-page recreations stay themeable, responsive, and consistent with
the hero's existing glass cards.

## Sequencing

This is two shippable pieces, and they should not land as one PR.

1. **The graph** — section 1, plus deleting `HowItWorks` and the old catalog.
   The page is coherent at the end of this step: graph, then CTA, then footer.
2. **Bands, bento, and the seven surface recreations** — sections 2–5.

Step 1 carries the risk and the reviewer attention; step 2 is mostly
presentational and parallelises well across the seven surfaces. Splitting also
means a mediocre graph gets caught before seven surfaces are built on top of it.

## Risks

- The interactive graph is the largest single build here and carries the page.
  If it lands mediocre, the redesign fails regardless of the rest.
- Three bands plus a bento plus a full-viewport graph makes a long page. Each
  band has to earn its height; if one reads as filler during implementation, cut
  it rather than pad it.
- Two graph renderings now exist on one page (the hero's atmospheric canvas and
  this labelled interactive one). They must read as deliberately different —
  atmosphere versus instrument — not as the same effect twice.
