# HANDOFF — finish #866 / Alvar trilogy → Sapling A+

**Written:** 2026-11-24  
**Branch:** `feat/learning-loop-reland` (tracks `origin/feat/learning-loop-reland`)  
**PR:** [#866](https://github.com/SaplingLearn/Sapling/pull/866)  
**Tip (at handoff):** `0ad949d1` — `feat(#866): land deferred W7 quiz UX pack`  
**Plan of record:** [`alvar-trilogy-implementation-plan.md`](./alvar-trilogy-implementation-plan.md)  
**Audience:** next Claude / agent session — finish **everything still open** for merge-ready + coherent product, without breaking invariants.

---

## 0. Non-negotiable constraints (read first)

1. **Never flip population flag defaults.** Do not set `REGISTRY` / `default_variant: "on"` for `learning_loop`, `loop_tutor_v2`, quiz child flags, or prompt-change flags. Operator enables via Admin → Flags only ([`w0-flag-enable-checklist.md`](./w0-flag-enable-checklist.md), [`flag-rollout.md`](./flag-rollout.md)).
2. **Never bridge quiz Hint to loop `POST /hint`.** Client Bastani-lite ladder only ([`w7-5-hint-scaffold.md`](./w7-5-hint-scaffold.md)).
3. **Wager / mid-session XP stay deferred.** A132 confidence only (`guessing` / `fairly_sure` / `sure`). No second store, no live XP in SessionTop (W7.D1 / W7.4).
4. **Plain quiz schema must stay flag-off byte-identical.** No `interaction` on `agents/quiz.QuizQuestion`. Kits live on `PlannedQuestion` + `attach_interaction` ([`w7-generation-emit.md`](./w7-generation-emit.md)).
5. **Graded-only belief.** Kit UI / hints / working-steps never invent mastery channels. Submit stays written/MC evidence through `apply_graph_update`.
6. **E2E ports:** human stack `:3000`/`:5000`; E2E slots `:310N`/`:510N`. Never boot E2E on the human ports. Prefer `127.0.0.1` for slot browsing (cookies ignore ports).
7. **Do not commit** `backend/tests/evals/runs/*.jsonl`, the local, untracked frontend AGENTS.md / CLAUDE.md unless asked.

---

## 1. What is true now (landed)

### Loop / W0–W5 (code)

- Learning loop + Tutor V2 + quiz learning features (A143–A147) on this branch; flags **off** by default.
- W0.1–W0.3 Claude evals recorded; `LOOP_SLOTS_PENDING_CLAUDE_EVAL` empty. **Correction (2026-11-24):** the `__v2` floors fail `floors.py --check` (safety gates 0.875–0.9 in some runs); re-record pending — see [`w0-flag-enable-checklist.md`](./w0-flag-enable-checklist.md).
- W0.5 three E2E lanes **GREEN** on tip (default / kill-switch / flag-off) — see checklist.
- Day 9 eng rows **#1–8, #10–23 done**; only Day 9 **#9 = operator HOLD**.

### Quiz shell / W7 (UI + wire)

| Slice | Status | Where |
|---|---|---|
| SessionTop forest chrome, no XP in bar | done | `QuizQuestion.tsx` + `question.css` |
| Meta: Returning + exam-distance + Bloom skill chip | done | `metaChips.ts`, `skillChip.ts`, header |
| Kit stubs Sort→Connect (+ map) | done | `*Answer.tsx` + interaction libs |
| Emit sanitize + planned kit prompt (all kinds) | done | `services/quiz/interaction.py`, `agents/quiz_planned.py` |
| Function `KIT: sort` + Playwright | done | handlers + `e2e/quiz-kit.spec.ts` |
| Hint Bastani-lite H0–H2 (scaffold) | done | `hintLadder` + `HintPanel` |
| A132 confidence under answer | done | `ConfidenceControl`; wager chrome deferred |
| Exam Twin soft timer | done | `examTimer.ts` + SessionTop |
| Calculate `value\|unit\|steps` | done | encode/UI; grade ignores steps |
| Richer kit grading (sort/connect/highlight/calculate) | done | `services/quiz/kit_grade.py` |
| Prereq banner, Practice/Exam Twin, results CTAs, Hub/Guide/Settings, Map | done | plan Day 5–8 |

### Spine W8 (mostly)

- W8.1–W8.7 marked done in plan (Library/Tree/Study/Flashcards/cross-links/`learner_next`). Treat UI polish / Hub wire gaps below as residual.

---

## 2. Remaining work — EVERYTHING

Grouped by who can do it. Check boxes as you finish. Prefer smallest safe PRs that cite plan IDs (W7.x / W5.x / W8.x).

### A. Operator-only (agents must not do)

- [ ] **W0.4 / W5.E\* population / self→class→%** per [`w0-flag-enable-checklist.md`](./w0-flag-enable-checklist.md)
  - Self-target: `learning_loop` → read-only quiz flags → prompt children → quiz pack
  - `loop_tutor_v2` population still HOLD (self-target dogfood OK; `LOOP_ROUTABLE_TIERS={deep}`)
  - Last: class → % → only then consider `default_variant: "on"`
- [ ] Rollout watches / kill-switch drills from [`flag-rollout.md`](./flag-rollout.md)
- [ ] Crisis copy review before enabling `crisis_support` broadly

### B. Merge / PR hygiene (agent OK)

- [ ] Re-run focused E2E on tip before merge claim:
  ```sh
  export PATH="/opt/homebrew/bin:$PATH"
  export SAPLING_MODEL_MODE=function
  export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  unset LEARNING_LOOP_ENABLED SAPLING_FLAG_LEARNING_LOOP
  scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts e2e/quiz-kit.spec.ts --reporter=list'
  ```
- [ ] Kill-switch + flag-off lanes if tip moved since W0.5 logs
- [ ] `cd backend && venv/bin/python -m pytest tests/ -q` (or targeted learning/quiz packs)
- [ ] Frontend: vitest for quiz shell / skillChip / examTimer / slots
- [ ] Update PR #866 body test-plan checkboxes to match tip
- [ ] Confirm CI green on #866; triage failures without flipping flags

### C. Kit / generation (agent OK — keep schema digests green)

- [ ] **Live kit-heavy generation** still mostly MC/written traffic — planned emit exists; improve real-model planned kits without touching plain `QuizQuestion` schema
- [ ] More function-mode `KIT:` fixtures beyond Sort (Label / Sequence / Calculate…) + Playwright where valuable
- [ ] Richer per-criterion kit grading beyond current sort/connect/highlight/calculate ([`w7-generation-emit.md`](./w7-generation-emit.md) “Next”)
- [ ] Pin flag-off digest tests still green after any emit change (`test_quiz_learning_flags_off` et al.)

### D. Quiz UX polish (agent OK — design constraints)

- [ ] **Full DC visual polish** — forest/chrome landed; not every handoff tone/frame. Diff against:
  - `~/Downloads/Design system audit and implementation (1)/Quiz Shell.dc.html`
  - Components `Quiz Components 7.*.dc.html`
  - Decisions: [`w7-design-decisions.md`](./w7-design-decisions.md), [`quiz-shell-port-map.md`](./quiz-shell-port-map.md)
- [ ] Optional Playwright pins: `quiz-session-top`, `quiz-skill-chip`, `quiz-exam-timer`, hint ladder climb
- [ ] Exam Twin: confirm timer shows only in `sessionMode=exam_twin`; never auto-submit
- [ ] Confidence: keep Guessing/Fairly sure/Sure in production path; do **not** ship Certain/Unsure XP wager unless product reopens W7.4
- [ ] Settings “default wager” stays deferred ([`w7-d2-hub-guide-settings.md`](./w7-d2-hub-guide-settings.md))

### E. Loop / pedagogy residuals (agent OK where no population flip)

- [ ] W1 pedagogy `__pedagogy` cassette live scoring if still PARTIAL ([plan § Day notes](./alvar-trilogy-implementation-plan.md))
- [ ] W2.3 reason-before-submit E2E if still soft/open
- [ ] W3.1 plan dependency **UI** (API `prereq_edges` done; UI open)
- [ ] W3.5 mini-map — wrap-up stub exists; productize only if plan still wants it (never mastery edges)
- [ ] W4 Stage B SVG verify / grounded cite-or-rewrite — cost-gated; Stage A withheld figure done ([`w4-visual-pipeline-spike.md`](./w4-visual-pipeline-spike.md))
- [ ] W8 residual: Hub/Dashboard `learner_next` wire polish if any call site still bypasses helper
- [ ] Cross-surface copy pass (Due on Study / Continue in Tutor / See on map) — [`w3-handoffs.md`](./w3-handoffs.md)

### F. Local / operator machine (blocked merge QA until fixed)

These blocked **Google sign-in** and human-stack quiz in the last session:

- [ ] **Local Supabase project `sapling` not running** — `supabase status` fails (`supabase_db_sapling` missing). Port **54322** held by foreign project `novus` (`supabase_db_novus`). Fix: stop conflicting project **or** free 54322, then `npx supabase start` + migrate/seed (`scripts/local-up.sh`).
- [ ] **Google OAuth placeholders** in `backend/.env`:
  - `GOOGLE_CLIENT_ID=your_google_client_id_here`
  - `GOOGLE_CLIENT_SECRET=your_google_client_secret_here`
  - Default `GOOGLE_AUTH_REDIRECT_URI` → `http://localhost:5000/api/auth/google/callback`
  - macOS **AirPlay** owns `:5000`; backend was on **`:5001`** → callback 404/403
  - Fix: real Google Cloud OAuth client; register redirect for the live backend port; set `GOOGLE_AUTH_REDIRECT_URI` + `FRONTEND_URL`; prefer running API on `:5000` if AirPlay disabled, else keep `:5001` and register that URI
- [ ] Use **http://localhost:3000** (not `127.0.0.1`) for Google cookie/nonce path after fix
- [ ] Workaround for demo without Google: `POST /api/auth/test-login` with `APP_ENV=local` + `rich-user-active` (requires DB with rich seed)
- [ ] Last successful quiz demo pointed backend at **E2E slot-1 PostgREST** `http://127.0.0.1:54421` because human Supabase was down — do not leave that as the long-term `.env`

### G. Docs sync (agent OK)

- [ ] Mark plan Day 9 #15 Calculate “working-steps deferred” → **done** (landed in `0ad949d1`)
- [ ] Mark W7.5 Bastani ladder deferred → **client H0–H2 done** (loop `/hint` still deferred)
- [ ] Refresh [`quiz-shell-port-map.md`](./quiz-shell-port-map.md) / checklist A+ boxes if still stale
- [ ] Keep this `HANDOFF.md` updated as rows close

### H. Explicit non-goals (do not reopen without owner)

- Mid-session XP / kit wager stakes
- Quiz ↔ loop session Hint bridge
- Population `learning_loop` / REGISTRY default on
- Mic for Explain kit (W6 refusal)
- Byte-for-byte LearnHarness clone
- Editing foreign Supabase projects casually without telling the human

---

## 3. Suggested finish order

1. **Unblock local stack** (F) if you need human Google/quiz QA — else use E2E cycles only.  
2. **Merge hygiene** (B): E2E lanes + unit gates on tip.  
3. **Kit traffic / fixtures** (C) if product wants more than Sort in function-mode demos.  
4. **DC polish pass** (D) against Shell HTML — visual only, no belief changes.  
5. **Pedagogy / W3–W4 residuals** (E) as time allows.  
6. Hand **operator checklist** (A) to a human — agents stop at “ready for self-target dogfood.”

---

## 4. Key paths (cheat sheet)

| Area | Path |
|---|---|
| Plan | `docs/learning-loop/alvar-trilogy-implementation-plan.md` |
| Flag enable | `docs/learning-loop/w0-flag-enable-checklist.md` |
| Quiz shell map | `docs/learning-loop/quiz-shell-port-map.md` |
| Emit contract | `docs/learning-loop/w7-generation-emit.md` |
| Skill chip | `frontend/src/lib/quiz/skillChip.ts` |
| Exam timer | `frontend/src/lib/quiz/examTimer.ts` |
| Hint ladder | `frontend/src/components/quiz/question/questionView.ts` (`hintLadder`) |
| Question shell | `frontend/src/components/quiz/question/QuizQuestion.tsx` |
| Kit grade | `backend/services/quiz/kit_grade.py` |
| Interaction sanitize | `backend/services/quiz/interaction.py` |
| Planned kits | `backend/agents/quiz_planned.py` |
| Function fixtures | `backend/agents/function_handlers_e2e.py` |
| Flags registry | `backend/services/feature_flags.py` |

---

## 5. Verify commands

```sh
# Backend kit + learning smoke
cd backend && venv/bin/python -m pytest tests/test_quiz_kit_grade.py tests/test_quiz_learning_flags_off.py -q

# Frontend quiz UX units
cd frontend && npx vitest run \
  src/lib/quiz/skillChip.test.ts \
  src/lib/quiz/examTimer.test.ts \
  src/components/quiz/question/questionView.test.ts \
  src/components/quiz/question/QuizQuestion.slots.test.tsx \
  src/components/quiz/question/CalculateAnswer.test.tsx

# Kit E2E (needs e2e-cycle / held slot — not :3000)
export PATH="/opt/homebrew/bin:$PATH"
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/quiz-kit.spec.ts --reporter=list'
```

Expected: pytest/vitest green; kit Playwright green in default lane; **no** REGISTRY diffs in the commit.

---

## 6. Open questions for the series owner

1. Enable `learning_loop` / `loop_tutor_v2` for self-target now, or wait until after #866 merge?  
2. Should Certain/Unsure wager chrome ever replace Guessing/Sure labels, or stay A132 forever?  
3. Priority for live kit mix vs keeping MC/written majority?  
4. Free port 54322 (stop `novus`) vs relocate Sapling local DB ports?  
5. Ship #866 with flags off as soon as CI green, treating W5 enable as a separate ops ticket?

---

## 7. One-line mission

**Make #866 merge-ready with flags still off, local Google/dev stack honest, kit/shell polish complete, and a clean operator checklist for turning the Alvar dials on — without breaking graded-only belief or flag-off digests.**
