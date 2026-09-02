# Quiz frontend redesign — the contract (#537, frontend)

Status: binding for every implementer on `feat/537-quiz-frontend`. Amendments are made here, by the lead,
never in a subagent's head. Design source of truth: the Claude Design project "UI mockups for quiz screens"
(`Sapling Quiz Prototype.dc.html` — interactive, the authority; `Sapling Quiz Screens.dc.html` — static 1a–1d).
Backend is frozen: everything below targets the six quiz endpoints that exist on `main@7863210a`.

---

## 0. Rulings (decided from recon; each records what it costs if wrong)

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| R-1 | **Styling = class names only, tokens only.** Quiz files and new `ui/` primitives carry **no `style={{}}`** except (a) binding a CSS custom property to runtime data (`style={{ "--quiz-accent": color } as CSSProperties}`) and (b) SVG geometry attributes (`cx`/`cy`/`r`/`x1`…) computed from data. Primitive rules are appended to `globals.css` in the house style (`.btn`, `.chip` precedent). Quiz screen rules live in per-screen CSS files under `components/quiz/**` imported by the screen component (App Router allows global CSS from any component). Every value is a `var(--token)`; no hex, no ad-hoc px except the design's own geometry constants declared once as tokens at the top of the quiz CSS (`--quiz-col-home: 780px` etc.). | The mission says zero inline styles; the repo's fidelity-bar screens are token-pure but inline-heavy (R2). Classes honour the stricter bar without inventing a new mechanism (no CSS Modules precedent exists). | Reviewer prefers inline tokens → mechanical conversion. |
| R-2 | **Every answer is recorded server-side as it happens** via `POST /attempts/{id}/answer`; the client-side **feedback mode** (`as-you-go` \| `at-end`) only decides *when* the verdict is shown. `/submit` is always called at the end (with the local answers as a belt-and-braces payload; server reconciliation makes recorded rows win). `generate` sends `include_answer_key: false`. | Makes leave-and-resume faithful in both modes and kills client-side grading (#546's intent). Feedback mode is not a backend option (gap G1) so it is a two-value client concept, stored in prefs — the "never hardcode option lists" rule applies to counts/difficulties, which come from `/config`. | If product wants feedback mode server-side later, only the prefs store moves. |
| R-3 | **Resume discovery** = localStorage session record (fast path) verified by `GET /attempts/{id}`, plus `GET /attempts?limit=20` filtered `status === "in_progress"` (other-device path). ~~No abandon endpoint exists (G4)~~ — **G4 CLOSED**: `POST /api/quiz/attempts/{id}/abandon` (owner-checked, 409 on a completed attempt, idempotent) stamps `abandoned_at`, so the derived status flips to `abandoned` and neither discovery path offers the attempt again. **Discard** = `useQuizHome::discard`: `dismissedAttempts` first (instant, and the across-loads fallback if the call never lands — a failed abandon is swallowed, the 24h sweep is the backstop), then the resume slot cleared in state, then the abandon call. **No refresh** (merge-gate review, 2026-08-26): one used to fire synchronously beside the POST, but the re-read routinely overtook the write and came back `in_progress`, leaving the strip hidden by localStorage alone — the single point of failure G4 exists to retire — and flashing the whole screen to a skeleton to change one row. Nothing on quiz home derives from an *unfinished* attempt (the ranking and the "missed N last time" join read COMPLETED attempts only), so it bought nothing. **`AbandonResult.abandoned_at` is nullable and `status` is DERIVED**, exactly as the read paths derive it: the route reports the state it actually observed rather than substituting its own clock for a write it did not make, so a 200 can carry `status: "in_progress"` / `abandoned_at: null` when the claim was lost to a writer that then left the row open (documented at `routes/quiz.py::abandon_attempt`; effectively unreachable). Read `status`, never the timestamp. `GET /attempts` deliberately still LISTS abandoned rows — it is the history reader (D4); what changed is the status the strip filters on. | Backend frozen — amended once the backend batch reopened. | Now only the failed-call fallback: if the abandon POST never lands, the row stays in_progress until the 24h sweep — hidden in this browser by `dismissedAttempts`, still offered on another device. |
| R-4 | **Multi-concept scopes run as a queue of single-concept attempts.** `generate` is per `concept_node_id`, so "practice on a course" and "review everything due" are sessions over a queue (max **5** concepts per session = `get_recommendations`' own limit; generation rate limit is 8/300s) of **3-question** attempts by default, each with its own results screen and a "Next: {concept} →" primary exit while the queue has more. | Honest to the backend; keeps the three screens identical per attempt. | Constants `QUEUE_MAX`, `QUEUE_COUNT` tweak. |
| R-5 | **"Practise the one(s) you missed"** = a new attempt on the same concept, `intent: "review"`, `num_questions = clamp(missedCount, config.min, config.max)`, same difficulty, **naming the finished attempt as `source_attempt_id`**. **AMENDED 2026-08-23 — G5 CLOSED:** `POST /generate` now re-serves the missed items VERBATIM (same stem, options, explanation and `question_hash`; no model call for them), deriving which ones from the source attempt's own `quiz_responses`, and generates only what it cannot recover. The response carries `source: {attempt_id, reserved_count, regenerated_count}`; the client labels a full re-serve "The ones you missed, again" and keeps "Focused on what you missed" for a partial or a fallback. The client sends the attempt id ONLY — `question_hash` stays internal and stripped. **Caveat:** `quiz_attempts.exam_days_away` (H3/#555) is resolved inside the generation call, so a FULLY re-served attempt — or a re-serve whose remainder generation failed — leaves it NULL. The column means "exam proximity at generation time", and analytics over it read as "generated quizzes only". | Was: no endpoint re-served specific questions (G5). Now: backend #537 G5. | None beyond copy — an ordinary generate omits `source_attempt_id` and is unchanged. |
| R-6 | **"Ask about this"** opens a `Sheet` over the quiz: `startSessionStream({ topic: conceptName, course_id, mode: "socratic" })` then `streamChat` with a composed first message (stem, the student's answer, the correct answer, the explanation, "Help me understand why."). The session is left open on close (it remains in the tutor's session list; no `end-session` call). The attempt is untouched. | Only seeding path that exists (G6). | Orphan tutor sessions accumulate; a follow-up can add a seed field. |
| R-7 | **Ranking reuse**: quiz home mirrors `graph_service.get_recommendations` (tier ∈ struggling/learning/unexplored, non-root, `mastery_score` asc) client-side over the already-loaded graph, in one pure module with the citation comment. Primary slot prefers the first candidate with `times_studied > 0`. "Due" set = the same membership filter over the whole scoped graph (count + distinct courses). | R4; `/recommendations` returns only `{concept_name, reason}`. | If `/recommendations` is later enriched, swap the mirror for a join (TODO left). |
| R-8 | **Concept definition** on the primary proposal comes from `POST /api/graph/{user}/concept-description` for **that one card only**, with the fallback sentence "{Course} · {tier} · {n} connected concepts" while loading/on failure. | R4 — no stored description column. | One LLM call per home visit. |
| R-9 | **XP/streak line** = `GET /api/gamification/me` read at session start and again after submit; the line renders `+{Δxp} XP · {streak}-day streak`; if either read failed the XP segment is omitted (never invented). | ~~G8: submit returns no deltas.~~ Server side closed — see R-9a. | None. |
| R-9a | **G8: server side CLOSED, client migration PENDING.** `POST /api/quiz/submit` returns an additive `gamification` block — `xp_awarded` plus the full `GET /api/gamification/me` snapshot taken right after the award, both built by `backend/services/gamification_service.py::me_snapshot` so the endpoint and the inline copy cannot disagree. The block has two halves that fail independently, and neither invents anything. The AWARD half (`xp_awarded`, `leveled_up`, `duplicate`) is read off the `XpAward` already in memory and costs no query; all three are `null` together when the XP write failed. The CARD half is the snapshot; if that read fails the block ships the award half ALONE (card fields absent, not zeroed) and the server emits `quiz.gamification_snapshot_failed` — the award half survives because it cost nothing and the client's `/me` fallback would be aimed at the same degraded database. `leveled_up` and `duplicate` are there because neither is reconstructable client-side: three separate paths all report `xp_awarded: 0` (disabled rule, zero-amount rule, idempotent replay), and detecting a level-up without `leveled_up` means re-adding the round trip the block exists to remove. The client still does R-9's two-read subtraction in `useGamificationDelta.ts`; swapping it for `result.gamification` (typed `SubmitGamification` in `lib/quiz/types.ts`, currently optional) is the follow-up, and R-9's "omit rather than invent" rule carries over to both null cases unchanged. **Caveat for the migrator:** `xp_awarded` is the `quiz_completed` ledger amount, not the total XP change across the submit — a badge earned by the same quiz pays its own `xp_reward`, which lands in `total_xp` but not in `xp_awarded`. R-9's current line (`after - before` from two `/me` reads) DOES include that badge XP, so a client that drops the pre-session read renders a smaller number on those submits. Adding an `xp_before` field to the block would close the gap; that call has not been made. | The blank XP line R-9 tolerates was a race between two reads the server could answer in one. | Until the client migrates, the extra round trips stay and behaviour is exactly R-9's. |
| R-10 | **Exits**: `returnToSource = source.returnTo ?? (conceptId ? `/tree?node=${conceptId}` : "/tree")`. The tree gains a `?node=<id>` focus param (C1). "Done" → `/quiz`. Cancel from home → `returnToSource` or `/dashboard` when there is no source. **Nothing ever lands on `/learn` without a session.** | Mission; R5 found every exit hardcoded to `/learn`. | — |
| R-11 | **Flag** ("This question is confusing") is always available; it toggles local state + toast and persists nothing — seam `TODO(#537-followup: flag persistence)`. Timing/confidence are never sent (`time_ms`/`confidence` stay undefined) — seam noted in `lib/quiz/api.ts`. | Scope guard. | — |
| R-12 | **Tier thresholds are never recomputed** from `mastery_score`; the quiz reads `mastery_tier` off the wire. `tierFor()` in `nodeStyle.ts` exists only for the `growth` variant's *after* tier (the submit response carries `mastery_after` but no tier) and mirrors `backend/config.py::get_mastery_tier` with a citation + a test that pins it. | R3 (#557). | A fifth copy, but pinned. |
| R-13 | `quiz-product-flows.md` / `quiz-design-brief.md` were not available anywhere; the session model and machine below are derived from the mission text + the prototype. | Missing inputs. | Rework of `machine.ts` if the real §11 differs. |

---

## 1. Directory layout and path ownership

```
frontend/src/
  lib/graph/nodeStyle.ts (+ .test.ts)              A1   pure node-style layer, extracted from KG2D/KG3D
  lib/graph/neighbourhood.ts (+ .test.ts)          A1   deterministic sibling pick
  components/graph/ConceptNode.tsx                 A1
  components/graph/ConceptNeighbourhood.tsx        A1
  components/graph/KnowledgeGraph2D.tsx, 3D.tsx    A1   delete local copies, import nodeStyle (golden snapshot proof)
  components/ui/{Button,SegmentedControl,AnswerOption,ProgressDots,InlineBanner,Sheet,EmptyState}.tsx, index.ts   A1
  components/Dialog.tsx                            A1   (only if focus-trap logic is factored for Sheet)
  components/screens/Gradebook/Landing.tsx         A1   (swap its private EmptyState for ui/EmptyState)
  app/globals.css                                  A1 (Wave 2)  primitive classes appended; NOBODY else in Waves 3–5
  lib/quiz/{types,api,errors,errors.test,machine,machine.test,session,session.test,source,source.test,
            proposals,proposals.test,relativeTime,relativeTime.test,exits,exits.test,prefs,
            useQuizConfig,useQuizHome,useQuizSession,useGamificationDelta}.ts           A2
  lib/api.ts                                       A2   ApiError gains code/requestId/retryAfter; old quiz fns stay until D1
  lib/errorMessage.ts                              A2   humanizeError reads `error.message`
  components/quiz/QuizScreen.tsx, quiz.css, index.ts   A2   phase switch + shared layout classes; stubs for the three screens
  components/quiz/home/**        (QuizHome.tsx, ConceptDialog.tsx, AdjustDialog.tsx, PickList.tsx, home.css)   B1
  components/quiz/question/**    (QuizQuestion.tsx, AskPanel.tsx, LeaveDialog.tsx, question.css)              B2
  components/quiz/results/**     (QuizResults.tsx, MissedList.tsx, results.css)                               B3
  app/(shell)/quiz/page.tsx                        A2   mounts QuizScreen
  eslint.config.mjs, docs/frontend-testids.md      A2 (Wave 2 adds the new files/ids) · D1 (Wave 5 removes the old)
  components/screens/Tree.tsx                      C1
  components/screens/Dashboard.tsx, SideNav.tsx, TopNav.tsx   C2
  app/(shell)/notetaker/page.tsx                   C3   (+ deep-link handling lives in A2's source.ts; C3 verifies)
  components/QuizPanel.tsx, QuizPanel.test.tsx, components/screens/Quiz.tsx   D1 (delete)
  frontend/e2e/quiz.spec.ts (+ new quiz-*.spec.ts) D2
  backend/tests/test_e2e_function_handlers.py      D3 (verify only)
```
Anything not listed is out of bounds; report the need to the lead.

---

## 2. Shared vocabulary

```ts
// lib/quiz/types.ts
export interface QuizConfig {                      // GET /api/quiz/config — the ONLY source of option lists
  num_questions: { min: number; max: number; options: number[] };
  difficulties: string[];                         // never enumerate these in code
  question_types: string[];
}
export type FeedbackMode = "as-you-go" | "at-end"; // client concept (R-2)
export interface QuizPrefs { count: number | null; difficulty: string | null; feedback: FeedbackMode } // localStorage "sapling_quiz_prefs"

export interface WireOption { label: string; text: string }                     // keyless
export interface WireQuestion { id: number; question: string; options: WireOption[]; concept_tested?: string; difficulty: string }
export interface GenerateSource { attempt_id: string; reserved_count: number; regenerated_count: number } // G5
export interface GenerateResult { quiz_id: string; questions: WireQuestion[]; requested_difficulty: string;
  resolved_difficulty: string; requested_count: number; delivered_count: number;
  source?: GenerateSource }                       // present iff the request named a source_attempt_id (R-5)
export interface AnswerResult { question_index: number; question_id: number; is_correct: boolean; correct_index: number;
  explanation: string; next_question: WireQuestion | null; recorded: boolean }
export interface SubmitResult { score: number; total: number; mastery_before: number; mastery_after: number;
  results: { question_id: string; selected: string; correct: boolean; correct_answer: string; explanation: string }[] }
export type AttemptStatus = "completed" | "abandoned" | "in_progress";
export interface AttemptSummary { quiz_id: string; status: AttemptStatus; concept_node_id: string; concept_name: string;
  course_id: string | null; score: number | null; total: number | null; difficulty: string; mastery_before: number | null;
  mastery_after: number | null; mastery_delta: number | null; created_at: string; completed_at: string | null }
export interface AttemptsPage { total: number; limit: number; offset: number; attempts: AttemptSummary[] }
export interface AttemptDetail { quiz_id: string; status: AttemptStatus; resumable: boolean; difficulty: string;
  concept_node_id: string; questions: WireQuestion[]; responses: { question_index: number; selected_index: number;
  is_correct: boolean; answered_at: string }[]; score: number | null; total: number | null; created_at: string }

export type SourceKind = "tree" | "dashboard" | "notes" | "nav" | "link" | "quiz";
export interface QuizSource { kind: SourceKind; returnTo?: string; conceptId?: string; noteId?: string }
export type QuizIntent = "practice" | "review";
export type QuizScope =
  | { kind: "concept"; conceptId: string }
  | { kind: "course";  courseId: string; queue: string[] }     // concept ids, weakest first, ≤ QUEUE_MAX
  | { kind: "due";     queue: string[] }
  | { kind: "missed";  conceptId: string; missedCount: number };

export interface QuizItem { index: number; question: WireQuestion; selectedIndex: number | null;
  verdict: { isCorrect: boolean; correctIndex: number; explanation: string } | null; flagged: boolean }
export type Phase = "home" | "configuring" | "generating" | "active" | "answered" | "confirm-leave"
  | "submitting" | "results" | "paused" | "error";
export interface QuizSession {
  intent: QuizIntent; scope: QuizScope; source: QuizSource;
  config: { count: number; difficulty: string; feedback: FeedbackMode };
  conceptId: string; courseId: string | null;
  attemptId: string | null; items: QuizItem[]; cursor: number;      // cursor = index of the current item
  queueIndex: number;                                                 // position in scope.queue (0 for concept/missed)
  phase: Phase; error: QuizError | null;
  result: SubmitResult | null; xp: { before: number; after: number; streak: number } | null;
  deliveredShort: boolean;                                            // delivered_count < requested_count
  sourceAttemptId: string | null;                                     // G5: the attempt whose misses this practises
  reserved: { reservedCount: number; regeneratedCount: number } | null; // G5: what that generate actually did
}
```

Constants (in `lib/quiz/session.ts`): `QUEUE_MAX = 5`, `QUEUE_COUNT = 3`, `STORAGE_KEY = "sapling_quiz_session"`,
`PREFS_KEY = "sapling_quiz_prefs"`, `DISMISSED_KEY = "sapling_quiz_dismissed"`.

---

## 3. Component API (A1)

All components: `"use client"`, named exports, `data-testid` passthrough prop `testid?: string`, forward no
`style`. Class names below are the public CSS API; every rule uses tokens only. Course accent is read from
`var(--quiz-accent, var(--accent))` set by the screen root.

### `lib/graph/nodeStyle.ts` (pure, no React)
```ts
export function hexToHsl(hex: string): { h: number; s: number; l: number } | null
export function hslToHex(h: number, s: number, l: number): string
export function shadeFor(baseHex: string, nodeId: string, as?: "css" | "hex"): string   // default "css" = hsl(...) (2D); "hex" (3D)
export function radiusFor(mastery: number, isRoot?: boolean): number                   // 8 + m*12 ; root 22
export function tierFor(score: number): "mastered" | "learning" | "struggling" | "unexplored"   // 0.75/0.45/0.1 — cites backend/config.py get_mastery_tier
export const TIER_OPACITY: Record<"mastered"|"learning"|"struggling"|"unexplored", number>   // 1 / .78 / .55 / .28
export function opacityFor(tier: string): number        // subject_root → 1
export function edgeWidthFor(strength: number): number  // 0.5 + s*1.2
export function truncateLabel(name: string, max?: number): string   // 18
export const NODE_STROKE_OPACITY = 0.4
export const GLOW = { pad: 8, opacity: 0.15, blur: 3 } as const
```
Proof: extend `KnowledgeGraph2D.testmode.test.tsx`'s `snapshot()` with `fill`/`opacity`/`stroke-opacity`, capture a golden
BEFORE the refactor, assert equality AFTER; KG3D's existing `nodeColor`/`nodeVal` tests keep passing; add a frozen
`shadeFor` golden table (≥5 ids).

### `lib/graph/neighbourhood.ts` — takes `lib/data.ts`'s view-model `GraphNode` (post `apiToGraphNode`), not the wire type (amended A1)
```ts
export interface NeighbourNode { id: string; name: string; mastery: number; tier: string; strength: number }
export function siblingsFor(centreId: string, nodes: GraphNode[], edges: GraphEdge[], n?: number): NeighbourNode[]
// real neighbours by strength desc (excluding ids starting "subject_root__"), then same-course peers ordered by hashSeed(id); n = 3
```

### `<ConceptNode>` — `components/graph/ConceptNode.tsx`
```ts
type ConceptNodeVariant = { kind: "dot" } | { kind: "node" } | { kind: "growth"; before: number; after: number };
interface ConceptNodeProps { size: number; mastery: number; tier: string; courseColor: string; nodeId: string;
  label?: string; variant?: ConceptNodeVariant; isRoot?: boolean; animate?: boolean; title?: string; testid?: string }
```
- `dot`: flat circle, fill `shadeFor`, opacity `opacityFor(tier)`, stroke same colour at `NODE_STROKE_OPACITY`. Used at 15px (question header) and 11px/14px (rows).
- `node`: the same mark plus the soft glow (`GLOW`) — 26px on quiz home.
- `growth`: dashed ring at `radiusFor(before)` (`stroke-dasharray 4 4`, opacity .5), filled circle at `radiusFor(after)` with `opacityFor(tierFor(after))`, glow `r+21`. On mount the filled circle grows ONCE from `before` to `after` over `var(--dur-slow)`; with `prefers-reduced-motion` (`usePrefersReducedMotion`) or `animate={false}` it renders the identical end state with no transition. The `<svg>` has `role="img"` and `aria-label` = `title` (e.g. "Recursion node grew from 29% to 46% mastery").
- Mastery radius is scaled into `size` so 15px and 26px are the same mark at two sizes.

### `<ConceptNeighbourhood>` — `components/graph/ConceptNeighbourhood.tsx`
```ts
interface ConceptNeighbourhoodProps { centre: { id: string; name: string; mastery: number; tier: string };
  siblings: NeighbourNode[]; courseColor: string; width: number; height: number; scale: number;   // scale 2 | 2.5 (×radiusFor)
  centreVariant?: ConceptNodeVariant; showLabels?: boolean; showCentreLabel?: boolean;   // default true; results passes false (the name sits below the canvas)
  composition?: "wide" | "compact";   // defaults by width (≥ wide threshold → "wide"): the two sibling layouts the prototype draws
  ariaLabel: string; testid?: string }
```
Layout: centre at (w/2 − small offset, h/2) per the prototype's three fixed sibling positions (top-left, top-right, bottom-left);
edges `stroke: var(--text-muted)` at opacity .2 and width `edgeWidthFor(strength)`; labels `font-size: var(--fs-xs)`,
`fill: var(--text-dim)`, truncated. Presets used: home 320×204 (scale 2 — the prototype's r=23 for nodeR(0.29); amended A1), concept dialog 300×200 (scale 2), results 640×212 (scale 2.5, `centreVariant` growth).

### `<Button variant="link">` (addition to `ui/Button.tsx`)
Bare text button: no padding/border/background, `color: var(--text-muted)`, hover `var(--text)`, `aria-pressed`/`data-active="true"` →
`border-bottom: 1px solid var(--quiz-accent, var(--accent))`. Class `.btn--link`.
`Button` forwards its ref (`forwardRef<HTMLButtonElement>`, amended A1) so a screen can return focus to it.
Also (amended A1): `.btn--primary:disabled, .btn--primary[aria-disabled="true"] { opacity: .55; cursor: not-allowed }` — the system had no disabled treatment for primary buttons; B2's Submit relies on it.

### `<SegmentedControl>` — `ui/SegmentedControl.tsx`
```ts
interface SegmentedControlProps<V extends string | number> { options: { value: V; label: string; disabled?: boolean }[];
  value: V; onChange: (v: V) => void; ariaLabel?: string; labelledBy?: string; testid?: string }
```
`role="radiogroup"`; each option `role="radio"` + `aria-checked`, roving tabindex, ←/→ move + select. Look: `.label-micro`
type (mono, uppercase, 0.14em), selected = `color: var(--text)` + `border-bottom: 2px solid var(--quiz-accent, var(--accent))`,
others `var(--text-muted)` + transparent 2px border (no layout shift). Option testid `${testid}-${value}`. Classes `.seg`, `.seg__opt`, `.seg__opt[aria-checked=true]`.

### `<AnswerOption>` — `ui/AnswerOption.tsx`
```ts
type AnswerState = "default" | "selected" | "correct" | "chosen-wrong" | "muted";   // muted = revealed, neither chosen nor correct
interface AnswerOptionProps { letter: string; text: string; state: AnswerState; disabled?: boolean;
  onSelect?: () => void; tabIndex?: number; testid?: string }   // tabIndex: the screen gives the first row 0 while nothing is selected (roving tab stop)
```
`role="radio"`, `aria-checked={state==="selected"||state==="chosen-wrong"}`, `tabIndex` per roving group; Enter/Space select.
Row: mono letter (`.label-micro`, 14px wide), text (`font-size: var(--fs-md)`, line-height 1.55), **mark slot always reserved**
(20px, right-aligned). States: `selected` → 2px left border `var(--quiz-accent)` + text `var(--text)`; `correct` → text 600 +
mark "✓" + `aria-label` suffix "— correct answer"; `chosen-wrong` → left border `var(--state-struggle)` + mark "✕" + suffix
"— your answer, incorrect"; `muted` → `var(--text-muted)` (amended A1: `--text-dim` is the default row colour). Default left border is 2px transparent (no shift). Classes
`.answer-option`, `.answer-option--{state}`, `.answer-option__letter|__text|__mark`.

### `<ProgressDots>` — `ui/ProgressDots.tsx`
```ts
interface ProgressDotsProps { total: number; current: number; answered: number; orientation?: "column" | "row";
  ariaLabel: string; testid?: string }   // answered = count of answered items (contiguous from 0)
```
Column variant = the design's "branch": a 1px `var(--border)` rail with dots: current = 9px hollow ring `var(--quiz-accent)`,
answered = 9px filled accent, upcoming = 7px hollow `var(--border-strong)`. `role="img"` with the aria label
("Question 3 of 5"). Classes `.progress-dots`, `.progress-dots--column`, `.progress-dots__dot--current|--done|--todo`.

### `<InlineBanner>` — `ui/InlineBanner.tsx`
```ts
interface InlineBannerProps { children: ReactNode; actions?: ReactNode; tone?: "accent" | "neutral"; testid?: string }
```
Full-width strip: `padding: 12px var(--pad-xl)`, background `color-mix(in srgb, var(--quiz-accent, var(--accent)) 6%, transparent)`,
`border-bottom: 1px solid var(--border)`, text `var(--fs-sm)` `var(--text-dim)`, actions right-aligned. `role="status"`.

### `<Sheet>` — `ui/Sheet.tsx`
```ts
interface SheetProps { open: boolean; onClose: () => void; title: string; children: ReactNode; width?: number;   // default 480
  side?: "right"; initialFocusRef?: RefObject<HTMLElement>; testid?: string }
```
Portal + dimmed backdrop (`rgba` from `var(--ink-900)` via color-mix), panel anchored right, full height, `var(--bg-panel)`,
`box-shadow: var(--shadow-lg)`; traps Tab, Escape closes, restores focus, scroll-locks (`useScrollLock`); `role="dialog"
aria-modal="true" aria-labelledby`. Header = title + close button (`Icon name="x"`, testid `${testid}-close`). Reduced motion → no slide.

### `<EmptyState>` — `ui/EmptyState.tsx`
```ts
interface EmptyStateProps { title: string; body?: string; action?: { label: string; href: string } | ReactNode; icon?: string;
  eyebrow?: string; size?: "md" | "hero"; testid?: string }   // eyebrow/size=hero keep Gradebook's promoted instance identical (amended A1; shipped as "md", not "default")
```
Promoted from `Gradebook/Landing.tsx` (which must now import it).

---

## 4. Data layer API (A2)

### Client — `lib/quiz/api.ts` (thin `fetchJSON` wrappers; same-origin `API_URL`)
```ts
fetchQuizConfig(): Promise<QuizConfig>
generateQuiz(p: { userId: string; conceptNodeId: string; numQuestions: number; difficulty: string }): Promise<GenerateResult>
  // body: { user_id, concept_node_id, num_questions, difficulty, include_answer_key: false }
answerQuestion(attemptId: string, p: { questionIndex: number; selectedIndex: number; questionId: number }): Promise<AnswerResult>
  // time_ms / confidence deliberately omitted — TODO(#537-followup: per-question timing) seam comment
submitQuiz(attemptId: string, answers: { question_id: number; selected_label: string }[]): Promise<SubmitResult>
listAttempts(userId: string, p?: { limit?: number; offset?: number }): Promise<AttemptsPage>
getAttempt(attemptId: string): Promise<AttemptDetail>
describeConcept(userId: string, conceptName: string, courseId?: string): Promise<string>   // wraps POST /api/graph/{user}/concept-description (reuse Learn's client if one exists)
```
`lib/api.ts`: `fetchJSON` parses the body; `ApiError` gains `code?: string`, `requestId?: string`, `retryAfterSec?: number`
(from the `Retry-After` header), `body?: unknown`. `humanizeError` prefers `body.error.message`.

### Errors — `lib/quiz/errors.ts` (the one module)
```ts
export type QuizErrorCode = "QUIZ_DIFFICULTY_INVALID" | "QUIZ_QUESTION_INVALID" | "QUIZ_COUNT_OUT_OF_RANGE" | "QUIZ_VALIDATION_ERROR"
  | "QUIZ_NOT_AUTHORIZED" | "QUIZ_CONCEPT_NOT_FOUND" | "QUIZ_ATTEMPT_NOT_FOUND" | "QUIZ_ATTEMPT_ALREADY_COMPLETED"
  | "QUIZ_ATTEMPT_ABANDONED" | "QUIZ_ATTEMPT_NOT_RESUMABLE" | "QUIZ_RATE_LIMITED" | "QUIZ_DAILY_LIMIT_REACHED"
  | "QUIZ_GENERATION_TIMEOUT" | "QUIZ_GENERATION_FAILED" | "QUIZ_INTERNAL_ERROR" | "QUIZ_HTTP_ERROR" | "NETWORK" | "UNKNOWN";
export interface QuizError { code: QuizErrorCode; message: string; retryable: boolean; retryAfterSec?: number; requestId?: string }
export const QUIZ_ERROR_COPY: Record<QuizErrorCode, string>
export function describeQuizError(err: unknown): QuizError
```
Human strings (final):
| code | copy | retryable |
|---|---|---|
| QUIZ_RATE_LIMITED | "You're quizzing fast — give it {n} seconds and try again." (n from Retry-After, else 60) | yes |
| QUIZ_DAILY_LIMIT_REACHED | "You've used today's quiz allowance. It resets tomorrow." | no |
| QUIZ_GENERATION_TIMEOUT | "Writing this quiz took too long. Try again — it usually works the second time." | yes |
| QUIZ_GENERATION_FAILED | "We couldn't put a quiz together for this concept right now. Try again in a moment." | yes |
| QUIZ_CONCEPT_NOT_FOUND | "That concept isn't on your tree any more. Pick another one." | no |
| QUIZ_ATTEMPT_NOT_FOUND | "We couldn't find that quiz. Start a new one." | no |
| QUIZ_ATTEMPT_ALREADY_COMPLETED | "This quiz was already scored. Your results are on your tree." | no |
| QUIZ_ATTEMPT_ABANDONED | "That quiz was discarded or expired. Start a fresh one." (G4: `abandoned_at` is stamped by the TTL sweep AND by Discard; the wire cannot say which) | no |
| QUIZ_ATTEMPT_NOT_RESUMABLE | "This quiz can't be resumed. Start a new one." | no |
| QUIZ_QUESTION_INVALID | "That answer didn't line up with the question. Reload and try again." | no |
| QUIZ_COUNT_OUT_OF_RANGE | server message verbatim (it carries the real bounds) | no |
| QUIZ_DIFFICULTY_INVALID / QUIZ_VALIDATION_ERROR | "Something about this request wasn't valid. Reload and try again." | no |
| QUIZ_NOT_AUTHORIZED | "Please sign in again to keep quizzing." | no |
| QUIZ_INTERNAL_ERROR / QUIZ_HTTP_ERROR / UNKNOWN | "Something went wrong on our side. Try again in a moment." | yes |
| NETWORK | "You look offline. Check your connection and try again." | yes |

### Source / entry URL — `lib/quiz/source.ts`
```ts
export interface EntryRequest { concept?: string; topic?: string; course?: string; scope?: "due"; attempt?: string; source: QuizSource }
export function parseEntry(params: URLSearchParams): EntryRequest
  // concept=<nodeId> | topic=<name> | course=<courseId> | scope=due | attempt=<id>; from=<SourceKind> return=<path> note=<id>
export function buildQuizHref(target: { concept?: string; course?: string; scope?: "due"; attempt?: string }, source: QuizSource): string
  // `/quiz?concept=…&from=tree&return=%2Ftree%3Fnode%3D…` — return must be same-origin path (reject anything with a scheme/host)
```

### Exits — `lib/quiz/exits.ts`
```ts
export function returnToSource(s: QuizSession): string   // R-10
export function sourceLabel(kind: SourceKind): string     // tree→"Back to your tree", notes→"Back to your note", dashboard→"Back to dashboard", else "Back to your tree"
```

### Proposals — `lib/quiz/proposals.ts` (pure; cites graph_service.get_recommendations)
```ts
export interface Candidate { node: GraphNode; course: EnrolledCourse | null; color: string; rationale: string; lastAttempt?: AttemptSummary }
export function rankCandidates(nodes: GraphNode[], courses: EnrolledCourse[], attempts: AttemptSummary[]): Candidate[]
export function primaryOf(c: Candidate[]): Candidate | null      // first with times_studied>0, else first
export function alternativesOf(c: Candidate[], primary: Candidate | null, n?: number): Candidate[]   // n=2
export function dueSet(nodes: GraphNode[]): { conceptIds: string[]; count: number; courseCount: number }   // membership filter, weakest first
export function queueFor(scope: "course" | "due", nodes: GraphNode[], courseId?: string): string[]   // ≤ QUEUE_MAX
export function groupByCourse(nodes: GraphNode[], courses: EnrolledCourse[]): { course: EnrolledCourse; nodes: GraphNode[] }[]
export function metaLine(node: GraphNode, now?: Date): string    // "29% · struggling · last studied 4 days ago" | "… · not studied yet"
export function rationaleFor(node: GraphNode, lastAttempt?: AttemptSummary, now?: Date): string
  // "31% · not reviewed in 9 days" | "44% · missed 3 last time" | "12% · not studied yet"
```
`lib/quiz/relativeTime.ts`: `daysAgo(iso, now)`, `relativeStudied(iso|null, now)` → "today" | "yesterday" | "N days ago" | "not studied yet".

### State machine — `lib/quiz/machine.ts` (pure reducer; effects live in the hook)
Events:
```
CONFIGURE(open) · START(proposal, config) · GENERATED(result) · GENERATE_FAILED(err)
SELECT(index) · SUBMIT_ANSWER · ANSWER_RECORDED(result) · ANSWER_FAILED(err) · NEXT
REQUEST_LEAVE · CANCEL_LEAVE · CONFIRM_LEAVE · RESUME(detail, session) · FINISH · SUBMITTED(result, xp) · SUBMIT_FAILED(err)
PRACTISE_MISSED · NEXT_IN_QUEUE · EXIT · FLAG · DISMISS_ERROR
```
Transitions:
```
home        --CONFIGURE--> configuring --CONFIGURE(false)--> home
home|configuring|results --START--> generating --GENERATED--> active(cursor 0) | --GENERATE_FAILED--> error(from: home)
active      --SELECT--> active(selectedIndex) ; --SUBMIT_ANSWER (selected≠null)--> active(pending) --ANSWER_RECORDED-->
              feedback=as-you-go ? answered : (last ? submitting : active(cursor+1))
answered    --NEXT--> last ? submitting : active(cursor+1)
active|answered --REQUEST_LEAVE--> confirm-leave --CANCEL_LEAVE--> (back) ; --CONFIRM_LEAVE--> paused (persist, navigate returnToSource)
paused|home --RESUME--> active(cursor = first unanswered) with source/scope restored
submitting  --SUBMITTED--> results ; --SUBMIT_FAILED--> error(from: submitting, retry allowed)
results     --PRACTISE_MISSED--> generating (scope missed) ; --NEXT_IN_QUEUE--> generating (queueIndex+1) ; --EXIT--> (navigate)
error       --DISMISS_ERROR--> the `from` phase
any         --FLAG--> same phase, items[cursor].flagged toggled
```
Invariants (each a unit test): (1) **no event takes `active`/`answered` to `home`/exit** — only CONFIRM_LEAVE → paused or the
submit path; `EXIT` in `active` is ignored. (2) `source` is identical on entry and on every terminal transition (paused, results,
exit). (3) `RESUME` after `ANSWER_RECORDED` + unmount restores `cursor` to the first unanswered item and keeps `source`. (4)
`SELECT` is ignored in `answered`. (5) `NEXT_IN_QUEUE` beyond the queue end is ignored. (6) `ANSWER_RECORDED` with
`recorded:false` still advances (idempotent replay).

### Persistence — `lib/quiz/session.ts`
`saveSession(s)` / `loadSession()` / `clearSession()` over `STORAGE_KEY` (try/catch, JSON). Saved on every transition from
`generating` onward; cleared on `SUBMITTED` (results are in memory) and on `EXIT`. `dismissAttempt(id)` / `isDismissed(id)`.

### Hooks
```ts
useQuizConfig(): { config: QuizConfig | null; error: QuizError | null }          // one fetch, cached per page
useQuizHome(userId, semester): { status: "loading"|"ready"|"error"; nodes; edges; courses; attempts: AttemptSummary[];
  candidates; primary; alternatives; due; byCourse; resumable: { attempt: AttemptDetail; session: QuizSession | null; answered: number } | null;
  refresh(): void }
useQuizSession(userId, entry: EntryRequest): { session; actions: { configure, start, select, submitAnswer, next, requestLeave,
  cancelLeave, confirmLeave, resume, finish, practiseMissed, nextInQueue, exit, flag, dismissError, retry } }
  // owns effects: generate/answer/submit calls, gamification before/after reads, persistence, router.push on paused/exit
useGamificationDelta(userId): { before: GamificationMe | null; snapshotBefore(); readAfter(): Promise<{xp: number; streak: number} | null> }
```
`QuizScreen.tsx` (A2): reads `useSearchParams` → `parseEntry`, mounts `<TopBar title="Quiz" subtitle="Test what you know."
actions={<AIDisclaimerChip/>}/>` + `<DisclaimerModal/>` (the AI-disclaimer gate, unchanged), sets `--quiz-accent` on the root
from the active concept's course colour, and switches on `phase`: home/configuring → `<QuizHome>`, generating/active/answered/
confirm-leave/submitting → `<QuizQuestion>`, results → `<QuizResults>`, error → inline error card with the mapped copy +
Retry/Back. Stubs for the three screens are created by A2 with the props below; Wave 3 replaces the bodies only.

Screen props (the seam between A2 and B1–B3):
```ts
QuizHome({ userId, home: ReturnType<typeof useQuizHome>, config, entry, session, actions })
QuizQuestion({ session, actions, config, concept: { id; name; courseCode; color; tier; mastery }, userId, courseId })
QuizResults({ session, actions, concept, neighbourhood: { siblings }, prefersReducedMotion })
```

### §4 amendments accepted from A2 (binding)
- Machine events also include `FAILED(err)` (a resume/answer failure with nowhere else to land) and `SET_CONFIG(config)` (Adjust "Done" changes settings without starting). `error(from)` is derived by `errorReturnPhase(session)`, not stored.
- `useQuizSession` returns `{ session, actions, pending, config }` — `pending` is true while a client call is in flight (B2 uses it for "Scoring…"/disabled Submit).
- `describeConcept(userId, conceptName, courseLabel?)` — third arg is the course LABEL the backend's `concept-description` route expects, not an id.
- `lib/quiz/exits.ts` also exports `cancelTarget(session)` (returnTo → `/dashboard`); B1's Cancel calls `actions.exit(cancelTarget(session))`.
- `lib/quiz/proposals.ts` also exports `entrySelection(entry, nodes, courses)` which resolves `?concept=`/`?topic=` against the scoped graph (reusing `quizSelection.resolveInitialSelection`) and returns `{ conceptId | null, unresolved: boolean }` — B1 shows the §6 toast when `unresolved`.
- The `sapling:graph-changed` CustomEvent (§5 B3) is dispatched by `useQuizSession` on SUBMITTED (`detail: { conceptId, masteryBefore, masteryAfter }`), not by the results screen.

### Wave 3 seam additions (binding)
- `components/quiz/question/AskPanel.tsx` (B2 builds it; B3 imports it from `../question/AskPanel`):
```ts
export interface AskSeed { stem: string; chosenLabel: string; chosenText: string; correctLabel: string; correctText: string; explanation: string }
export interface AskPanelProps { open: boolean; onClose: () => void; userId: string; conceptName: string; courseId: string | null;
  courseLabel?: string; seed: AskSeed; returnFocusTo?: RefObject<HTMLElement>; testid?: string }   // default testid "quiz-ask-panel"
```
  B3 may mock it in unit tests until B2 lands; the prop shape above is fixed.
- `EmptyState` size values are `"md" | "hero"` (A1 built `md`, not `default`).
- `QuizHome` does NOT take `prefs`: prefs reach the screen already resolved, as `session.config` (`useQuizSession` applies `defaultConfigFor(config, loadPrefs(config))` once `/config` lands), and the dialogs write back through `savePrefs`. The prop was declared, passed and never read — dropped in the final review wave rather than left as a seam that lies.
- `QuizScreen`'s error card carries `quiz-error`, `quiz-error-retry`, `quiz-error-back` (A2).
- Wave 3 screens import primitives from `@/components/ui` and node marks from `@/components/graph/ConceptNode` /
  `ConceptNeighbourhood`; hooks/types from `@/lib/quiz/*`. Screens own ONLY their directory; new primitives or CSS outside it go
  to the lead.

---

## 5. Screen specs (B1–B3) — the prototype is the visual authority; this is the behavioural one

Common: content column centered (`--quiz-col-home: 780px`, `--quiz-col-question: 680px`, `--quiz-col-results: 640px`), page
padding `52px var(--pad-xl) 32px` (home), `56px var(--pad-xl) 36px` (question), `28px var(--pad-xl) 32px` (results); eyebrows
`.label-micro`; display text `.h-serif`; definitions `.body-serif`; dividers `1px solid var(--border)`; nothing is signalled by
colour alone; every interactive element has a visible `:focus-visible` ring (global rule — never `outline:none`); no layout
shifts between states (reserve space for marks, feedback line `min-height: 20px`, button labels swap in place).

### B1 — Quiz home (`phase: home | configuring`)
1. **Resume strip** (`InlineBanner`, `quiz-resume-strip`) when `home.resumable`: "You left a quiz on {concept} — {answered} of
   {total} answered" · `Resume` (`quiz-resume`, secondary) · `Discard` (`quiz-resume-discard`, link; R-3).
2. **Ready for you** (`quiz-proposal`): eyebrow; `ConceptNode node 26px` + concept name (`.h-serif` 28px); `metaLine`;
   definition (R-8, `.body-serif`, max-width 380); config line `"{count} questions, {difficulty}"` + `" · answers as you go"`
   when feedback=as-you-go; `Start` (primary, `quiz-start`) + `adjust` (link, `quiz-adjust`, `data-active` while the dialog is
   open); `ConceptNeighbourhood` 320×204 on the right behind a vertical divider. Entry overrides: `concept=`/`topic=` → that
   concept is the primary with rationale "From your tree" / "From your note" / "Suggested for you"; `course=` → primary is
   `queueFor("course")[0]` and the card is titled "Practice {CODE}" with "{n} concepts due · 3 questions each"; `scope=due` →
   the card is "Review everything due" with "{count} concepts across {courseCount} courses · starting with the {min(count,5)} weakest".
3. **Also worth a look**: up to 2 `alternatives` rows (`quiz-alternative-{nodeId}`: 11px dot, name `.h-serif` 16px, course code
   mono, rationale right) → opens the **Concept dialog**. Then the **Review everything due** row (`quiz-review-due`, hollow dot,
   "{count} concepts across {courseCount} courses") → starts a due session. Hidden when `due.count === 0`.
4. **Pick something specific →** (`quiz-pick-open`, link) reveals the grouped list (`quiz-pick-list`): per course an eyebrow
   with a 9px course dot + "CODE · name", rows `quiz-pick-{nodeId}` (14px dot sized by mastery, name, `metaLine`) → Concept dialog.
   `← Back` collapses it.
5. **Concept dialog** (`Dialog size="xl"`, `quiz-concept-dialog`): name, `metaLine`, rationale, definition (R-8 for this concept),
   neighbourhood 300×200, then the three `SegmentedControl` rows (Length → `config.num_questions.options`; Difficulty →
   `config.difficulties`; Answers → as you go / at the end) and `Cancel` / `Start · {count} {difficulty}` (`quiz-concept-start`).
6. **Adjust dialog** (`Dialog size="md"`, `quiz-adjust-dialog`): title "Adjust this quiz", "{concept} · {CODE}", the same three
   rows, a note line ("After each answer you'll see whether it was right…" / "Answers stay hidden while you work…"), `Done` /
   `Start · {count} {difficulty}`. Choices persist to prefs.
7. **Empty states** (`EmptyState`, `quiz-empty-state`): no courses → "Add a course to start quizzing" → `/dashboard` (where
   courses are managed); courses but no concepts → "Your tree is empty" body "Upload notes or talk to the tutor and concepts will
   appear here." → actions `/library` and `/learn`. Never a dead end.
8. `Cancel` (`quiz-cancel`, link, top-right of the proposal region) → `returnToSource` or `/dashboard`.
Defaults: `count = prefs.count ?? (options includes 5 ? 5 : options[mid])`, `difficulty = prefs.difficulty ?? (difficulties includes "medium" ? "medium" : difficulties[0])`, `feedback = prefs.feedback ?? "at-end"`.

### B2 — Question (`phase: generating | active | answered | confirm-leave | submitting`)
- Layout: 64px left rail with `ProgressDots column` ("Question {i} of {n}"), content column, 64px right spacer.
- Header row: `ConceptNode dot 15px` + "{Concept} · {CODE}" + difficulty chip (`Badge`, uppercase mono; the item's `difficulty`).
- Stem `.h-serif` 24px/1.5, `min-height: 72px`, margin 48px 0.
- Options: `role="radiogroup" aria-label="Answer choices"` (`quiz-answer-options`) of `AnswerOption` (`quiz-answer-option-{label}`),
  top border. States: before submit `default|selected`; after `ANSWER_RECORDED` in as-you-go: `correct`, `chosen-wrong`, others `muted`.
- Feedback line (`quiz-review-verdict`, `aria-live="polite"`, min-height 20px): "Correct." / "Not quite — the answer is {letter}."
  then the explanation on the next line (`.body-serif`). In at-end mode it stays empty.
- `This question is confusing` (link, `quiz-flag`, `aria-pressed`) — always rendered, toggles `FLAG` + toast "Noted — thanks." (R-11).
- `Ask about this` (secondary, `quiz-ask`) — rendered only in `answered` (it needs the verdict); opens **AskPanel** (R-6).
- Footer: `Leave` (secondary, `quiz-leave`) left; right: `Submit` → after reveal `Next` / `See results` on the last item
  (`quiz-submit-answer` while Submit, `quiz-next` once it becomes Next/See results — same element, testid switches with the label).
  Submit disabled until a selection exists (`aria-disabled`, reduced-opacity primary — never hidden).
- **Leave dialog** (`Dialog size="sm"`, `quiz-leave-dialog`): "Leave this quiz?" body "Your answers so far are saved. You can pick
  it up again from Quiz home." `Keep going` (`quiz-leave-cancel`, autofocus) / `Leave` (`quiz-leave-confirm`). Confirm → `CONFIRM_LEAVE`.
- **AskPanel** (`Sheet`, `quiz-ask-panel`, title "Ask about this"): top = the seeded context (stem, "You chose {L} · {text}", "The
  answer is {L} · {text}", explanation) as static cards; below = the streamed tutor reply (reuse `consumeChatStream`; render with
  the same markdown component Learn uses) and an input (`quiz-ask-input`) + send (`quiz-ask-send`) for follow-ups. Close
  (`quiz-ask-panel-close` / Escape) returns focus to `quiz-ask`; the question screen is unchanged underneath.
- **Keyboard**: `A–F` / `1–6` select the matching option (active only); `Enter` = Submit / Next; `Escape` = open the leave
  dialog (when no dialog/sheet is open); arrow keys move within the radiogroup. Document this in a visually-hidden hint.
- `generating`: the same layout with `Skeleton` stem + 4 skeleton rows (`quiz-generating`), rail dots at 0/…; copy "Writing your
  quiz…". `submitting`: options disabled, footer button shows "Scoring…".
- `deliveredShort`: one toast on arrival "Only {delivered} questions were ready for this concept."

### B3 — Results (`phase: results`)
- `ConceptNeighbourhood 640×212 scale 2.5` with `centreVariant: growth {before: mastery_before, after: mastery_after}` (R-12 for the
  after-tier), `animate = !prefersReducedMotion`, aria "{Concept} node grew from {b}% to {a}% mastery".
- Concept name `.h-serif` 26px; delta line `"{b}% → {a}% · {tierBefore} → {tierAfter}"` (`quiz-results-mastery`).
- Rule: score line `"{score} of {total} correct"` (`quiz-results-score`) left; XP line `"+{Δ} XP · {streak}-day streak"` right
  (`quiz-results-xp`), omitted when unknown (R-9). Plain text, no badges.
- **Missed** (`quiz-missed-list`) when `results.some(!correct)`: eyebrow "One to look at" / "{n} to look at"; each item
  (`quiz-missed-{questionId}`) shows the stem (`.h-serif` 17px), "You chose {L} · the answer is {R}", a **Show explanation**
  disclosure (`aria-expanded`, `quiz-missed-explain-{id}`) revealing the explanation, and `Ask about this`
  (`quiz-missed-ask-{id}`) opening the same AskPanel seeded with that item. Left 2px accent bar.
- **Perfect** (`results.every(correct)`): NO review section; the line "Nothing to review — every answer was right. {Concept}
  keeps growing on your tree." (`quiz-results-perfect`).
- Exits row: primary = `Next: {nextConcept} →` (`quiz-next-concept`) when the scope queue has more; else `Practise the one(s)
  you missed` (`quiz-practise-missed`, R-5) when any missed; else `Keep going — quiz again` (`quiz-again`, same concept/config).
  Secondary = `sourceLabel(source.kind)` (`quiz-back-to-source`) → `returnToSource`. Link = `Done` (`quiz-done`) → `/quiz`.
- A mastery-moved `CustomEvent("sapling:graph-changed")` is dispatched on `window` on arrival (cheap hook for any mounted graph; the
  tree refetches on mount anyway).

---

## 6. Entry / exit URL API (Wave 4)

| Caller | href | Arrival |
|---|---|---|
| Tree node panel "Quick quiz" (concept) | `buildQuizHref({concept:id}, {kind:"tree", returnTo:`/tree?node=${id}`, conceptId:id})` | home, primary = concept |
| Tree subject root "Quick quiz" | `buildQuizHref({course:courseId}, {kind:"tree", returnTo:"/tree"})` | home, course proposal |
| Dashboard suggest card | `buildQuizHref({concept:id}, {kind:"dashboard", returnTo:"/dashboard"})` (name → id from loaded nodes) | home, primary = concept |
| Dashboard "Review what's due" (the Learn-next panel's quiz CTA) | `buildQuizHref({scope:"due"}, {kind:"dashboard", returnTo:"/dashboard"})` | home, due proposal |
| SideNav / TopNav | `/quiz` | home |
| Notetaker "Generate quiz" | `buildQuizHref({concept:nodeId}, {kind:"notes", returnTo:`/notetaker?note=${noteId}`, noteId})` — disabled-until-linked kept | home, primary = concept, rationale "From your note" |
| Legacy deep links `?concept=` / `?topic=` (no `from`) | treated as `{kind:"link"}` | home, primary = concept (resolved inside the active-semester scope; unknown → toast + ordinary home) |
| Resume strip / leave-and-return | `/quiz?attempt=<id>` | active at first unanswered |
Exits: `returnToSource` (R-10); Done → `/quiz`; Cancel → `returnToSource` or `/dashboard`. The tree honours `?node=<id>`
by selecting that node in the detail panel (C1). C1 also adds "Recent quizzes" (last five attempts for the node, from
`listAttempts(userId,{limit:100})` filtered by `concept_node_id`) to the node panel: date, `score/total`, Δ mastery.

---

## 7. Testids — the API (D2 updates `docs/frontend-testids.md`; A2 registers the files in `eslint.config.mjs`)
Kept: `quiz-panel` (question root), `quiz-start`, `quiz-cancel`, `quiz-answer-options`, `quiz-answer-option-{label}`,
`quiz-submit-answer`, `quiz-next`, `quiz-review-verdict`, `quiz-results-score`, `quiz-results-mastery`, `quiz-done`.
Renamed: `quiz-exit` → `quiz-leave`; `quiz-retake` → `quiz-again`; `quiz-explain-concept` → `quiz-ask`.
New: everything else named in §5/§6 (`quiz-home`, `quiz-resume-strip`, `quiz-resume`, `quiz-resume-discard`, `quiz-proposal`,
`quiz-adjust`, `quiz-alternative-{id}`, `quiz-review-due`, `quiz-pick-open`, `quiz-pick-list`, `quiz-pick-{id}`,
`quiz-concept-dialog`, `quiz-concept-start`, `quiz-adjust-dialog`, `quiz-seg-count`, `quiz-seg-difficulty`, `quiz-seg-feedback`,
`quiz-empty-state`, `quiz-progress`, `quiz-flag`, `quiz-leave-dialog`, `quiz-leave-confirm`, `quiz-leave-cancel`, `quiz-ask-panel`,
`quiz-ask-panel-close`, `quiz-ask-input`, `quiz-ask-send`, `quiz-generating`, `quiz-results`, `quiz-results-xp`, `quiz-missed-list`,
`quiz-missed-{id}`, `quiz-missed-explain-{id}`, `quiz-missed-ask-{id}`, `quiz-results-perfect`, `quiz-practise-missed`,
`quiz-next-concept`, `quiz-back-to-source`, `tree-node-recent-quizzes`, `tree-node-recent-quiz-{attemptId}`).

Added during Waves 3–4 (binding, register in `docs/frontend-testids.md`): `quiz-concept-cancel`, `quiz-adjust-done`, `quiz-adjust-start`,
`quiz-pick-back`, `quiz-home-error`, `quiz-home-retry`, `quiz-ask-seed`, `quiz-ask-retry`, `quiz-results-graph`,
`quiz-error`, `quiz-error-retry`, `quiz-error-back`, `dashboard-review-due`.

---

## 8. Seams left (report at the end)
- Abandon/discard endpoint (R-3) · feedback mode as a backend option (G1) · per-concept attempt history filter (G2) · ~~finished-attempt
  review (G5)~~ **CLOSED 2026-08-23 — generate re-serves the missed items by identity; see R-5** · tutor seed field (G6) · question `type` on the wire (G9) · flag persistence
  (R-11) · per-question timing/confidence (G10) · enriched `/recommendations` (R-7) · `/wiki` publishes pre-#557 tier ranges
  (R3 found `companionContent.ts:150-153`).
- **G8 (XP/streak in the submit response) is no longer a seam on the backend** — submit returns the `gamification` block (R-9a).
  What remains is the client swap: `useGamificationDelta.ts` → `result.gamification`, plus the open question that swap raises —
  `xp_awarded` is the quiz's ledger amount, so a badge earned by the same submit shows up in `total_xp` but not in `xp_awarded`,
  and a client that drops the pre-session `/me` read loses that delta. Decide whether the block needs an `xp_before`.
