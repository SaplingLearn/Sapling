# HANDOFF — AI learning system remaining (no quiz UI)

**For:** Andres (or next agent claiming this handoff)  
**Written:** 2026-11-24  
**Org:** [saplinglearn on Trov](https://trov.dev/saplinglearn)  
**Branch:** `feat/learning-loop-reland` · PR [#866](https://github.com/SaplingLearn/Sapling/pull/866)  
**Tip when written:** `0ad949d1`  
**Plan of record:** [`alvar-trilogy-implementation-plan.md`](./alvar-trilogy-implementation-plan.md)  
**Scope of THIS handoff:** the **AI learning system** only — loop tutor, flags, evals, learner model spine, W0–W5–W8 learning work.  
**Out of scope here:** quiz shell / kit UI / DC polish / Bloom chips / Exam Twin timer / Hint ladder chrome (already landed or tracked separately in [`HANDOFF.md`](./HANDOFF.md)).

---

## Mission

Finish whatever is still missing from the Alvar trilogy **implementation plan for the learning system**, so #866 is merge-ready with flags still **off**, and leave a clean operator path to turn dials on.

---

## Hard constraints

1. **Never flip population `REGISTRY` defaults** for `learning_loop`, `loop_tutor_v2`, or prompt-change flags. Operator Admin Flags only ([`w0-flag-enable-checklist.md`](./w0-flag-enable-checklist.md)).
2. **Graded-only belief** — no mastery from hints, free text, or UI chrome alone.
3. **Do not reopen settled Alvar refusals** (per-step prediction as mastery, free-text as mastery, etc.).
4. E2E human ports `:3000`/`:5000` vs slots `:310N`/`:510N` — never mix.
5. Kill switch: `LEARNING_LOOP_ENABLED=false` overrides the flag.

---

## Already true (do not redo)

- Loop + Tutor V2 + quiz **learning** features (A143–A147) coded; flags default **off**.
- W0.1–W0.3 Claude evals recorded; `__v2` lite/standard/deep served gates **1.0** ×3 floors.
- W0.5 three E2E lanes GREEN (default / kill-switch / flag-off) — see checklist.
- Day 9 eng complete except **#9 operator HOLD**.
- W8 spine (Library/Tree/Study/`learner_next`/cross-links) largely done in plan.
- Quiz *UI* pack landed separately — **ignore for this handoff**.

---

## Remaining — learning system only

### A. Operator (agent prepares checklist; does not flip)

- [ ] Self-target dogfood order in [`w0-flag-enable-checklist.md`](./w0-flag-enable-checklist.md):
  1. `learning_loop` (self)
  2. Read-only: `quiz_concept_plan`, `quiz_results_routing`, `item_reports`, `next_probe_hint`
  3. Prompt children: `segment_prequestion`, `self_explanation_prompts`
  4. `loop_tutor_v2` — self-target OK; **population HOLD** (`LOOP_ROUTABLE_TIERS={deep}`)
  5. Later W5.E3–E4 quiz/drafting pack — still self/class only
  6. Last: class → % → only then `default_variant: "on"`
- [ ] Rollout watches / kill-switch drills ([`flag-rollout.md`](./flag-rollout.md))
- [ ] Crisis copy review before broad `crisis_support`

### B. Merge hygiene for learning code on tip

- [ ] Re-run focused learning E2E on current tip:
  ```sh
  export PATH="/opt/homebrew/bin:$PATH"
  export SAPLING_MODEL_MODE=function
  export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  unset LEARNING_LOOP_ENABLED SAPLING_FLAG_LEARNING_LOOP
  scripts/e2e-cycle.sh -- bash -c \
    'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts --reporter=list'
  ```
- [ ] Kill-switch + flag-off lanes if tip moved since W0.5 logs
- [ ] Backend learning/quiz-learning pytest packs green
- [ ] Update PR #866 test-plan for learning gates; CI green

### C. Plan residuals (learning — from implementation plan)

Walk [`alvar-trilogy-implementation-plan.md`](./alvar-trilogy-implementation-plan.md) and close open learning boxes:

- [ ] **W1** pedagogy `__pedagogy` cassette live scoring if still PARTIAL
- [ ] **W2.3** reason-before-submit E2E if still open
- [ ] **W3.1** plan dependency **UI** (`prereq_edges` API done; UI open)
- [ ] **W3.5** learner mini-map — only if product still wants beyond wrap-up stub (never mastery edges)
- [ ] **W4** Stage B SVG verify / grounded cite-or-rewrite — cost-gated; Stage A withheld figure done
- [ ] **W5.E2–E4** code/dogfood readiness docs; enable remains operator
- [x] **W8** residual: Hub/Dashboard call sites on `learner_next` (Dashboard Today-plan quiz item was the last bypass; Tutor T1 `weakestConcept` and quiz-results `next_step.learn` still rank on their own — Tutor/Quiz-summary, out of W8.6 scope)
- [ ] Cross-surface copy pass ([`w3-handoffs.md`](./w3-handoffs.md))

### D. Explicit non-goals for this handoff

- Quiz shell / kit stubs / DC visual polish / skill chip / Exam Twin timer UX
- Mid-session XP wager
- Quiz Hint → loop `POST /hint` bridge
- Population REGISTRY default on

---

## Suggested order

1. Confirm tip E2E learning lanes (B).  
2. Sweep plan § checkboxes for W1–W5–W8 learning gaps (C); implement only code gaps.  
3. Hand operator checklist (A) — stop at “ready for self-target dogfood.”  
4. Do **not** spend cycles on quiz UI.

---

## Key paths

| Area | Path |
|---|---|
| Plan | `docs/learning-loop/alvar-trilogy-implementation-plan.md` |
| Full quiz+loop handoff (broader) | `docs/learning-loop/HANDOFF.md` |
| Flag enable | `docs/learning-loop/w0-flag-enable-checklist.md` |
| Flag rollout | `docs/learning-loop/flag-rollout.md` |
| Loop tutor | `backend/agents/loop_tutor.py` |
| Flags | `backend/services/feature_flags.py` |
| Learner next | `backend/learning/learner_next.py`, `backend/services/learner_next.py` |
| Gate | `backend/learning/gate.py` |

---

## Verify

```sh
# Learning E2E (slot cycle — not :3000)
export PATH="/opt/homebrew/bin:$PATH"
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
scripts/e2e-cycle.sh -- bash -c \
  'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts --reporter=list'

# Eval floors still hold (no re-record unless you change prompts)
cd backend && venv/bin/python tests/evals/floors.py --check
```

---

## One-line

**Close remaining Alvar learning-system plan gaps on #866 with flags off; leave operator enable checklist; skip all quiz UI work.**
