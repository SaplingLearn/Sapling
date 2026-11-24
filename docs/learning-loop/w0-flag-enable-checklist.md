# W0.4 / W5 — operator flag-enable checklist

Owner-run only. **Do not** flip `REGISTRY` defaults or set `default_variant: "on"` for `learning_loop` (or prompt-change flags) for everyone from this page. Enable via Admin → Flags (user targets), per [flag-rollout.md](flag-rollout.md). Plan: W0.4 / W5 in [alvar-trilogy-implementation-plan.md](alvar-trilogy-implementation-plan.md); PR [#866](https://github.com/SaplingLearn/Sapling/pull/866).

**Prereq (done 2026-11-24):** W0.1–W0.3 Claude evals recorded; `LOOP_SLOTS_PENDING_CLAUDE_EVAL` empty; `__flags` / `__v2` / check_item_gates cassettes in tree. **Day 9 W0.3b:** standard `__v2` `SycophancyResists` now **1.0** (prompt harden + re-record); still blocked for `loop_tutor_v2` population enable while standard **ServedAnswerLeak** floors at **0.9** (deep/lite `__v2` served leak gates are 1.0 — deep-routed dogfood OK).

## Self-target order (Admin Flags → your user only)

Child flags only act where `learning_loop` is on for that student (`learning/gate.py::served_flag`). For dogfood: target **yourself** with `learning_loop=on`, then the children below. Leave the stored everyone-default **off**.

| Step | Flag(s) | Gate | Notes |
|---|---|---|---|
| 0 | `learning_loop` (self only) | Kill switch unset; three E2E lanes already green on the PR head if you will keep dogfooding long | Prerequisite to observe any child flag. Not a population rollout. |
| 1 | `quiz_concept_plan` | None (read-only) | `GET /api/quiz/plan` on a seeded/enrolled course |
| 2 | `quiz_results_routing` | None (read-only) | Results next-step links; hide_* safe |
| 3 | `item_reports` | Staff owns `/api/admin/check-items` | Client-visible; two reports hold an item |
| 4 | `next_probe_hint` | W2.3 storage / plaintext into activation (else no-op) | No prompt change; never mastery |
| 5 | `crisis_support` (optional here) | Copy review (`docs/safety/crisis-support.md`) | Safety; not eval-gated |
| 6 | `segment_prequestion` | `__flags` recorded + replaying (`teach_explains_prequestion`) | W0.3 done; self-target only |
| 7 | `self_explanation_prompts` | Same `__flags` (`teach_acknowledges_self_explanation`) | W0.3 done; self-target only |
| — | **`loop_tutor_v2` — HOLD** | Deep `__v2` served gates **1.0** × 3 runs | Do not self-enable until SycophancyResists (and peers) clear 1.0 |
| 8 | Quiz / drafting pack (later W5.E3–E4) | Planned / gates / varied / combo / relations evals | After E1–E2 dogfood; still self/class only |
| 9 | **`learning_loop` population** | Three E2E lanes green (below); self/class dogfood OK | Last: class targets → `%` rollout → `default_variant: "on"` |

Rollback any step: clear your user target, or `SAPLING_FLAG_<KEY>=off` on the backend. Emergency everyone-off for the loop: `LEARNING_LOOP_ENABLED=false` (restart).

## Three E2E lanes (required before / with W0.4 population enable)

Playwright needs a held stack (`make e2e-up`) or a full cycle (`make e2e`). Export lane env in the **same shell** that boots the stack and runs Playwright (`frontend/e2e/support/lane.ts`; `global-setup.ts` asserts agreement). Do not put `LEARNING_LOOP_ENABLED` in `backend/.env` (`scripts/e2e-up.sh` refuses).

Function-mode seam (cycles default it; export explicitly for a held stack):

```sh
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
```

| Lane | Shell exports | Boot + run |
|---|---|---|
| **Default** (loop on for suite) | unset `LEARNING_LOOP_ENABLED`; leave flag default (`e2e-up` sets `SAPLING_FLAG_LEARNING_LOOP=on`) | `make e2e` **or** held: `make e2e-up` → `cd frontend && npx playwright test` → `source .e2e/env.sh && cd backend && venv/bin/python -m e2e_oracles` → `make e2e-down` |
| **Kill-switch** | `export LEARNING_LOOP_ENABLED=false` | `LEARNING_LOOP_ENABLED=false make e2e` **or** same held path with the export before `make e2e-up` and Playwright |
| **Flag-off** (prod default) | unset kill switch; `export SAPLING_FLAG_LEARNING_LOOP=off` | `SAPLING_FLAG_LEARNING_LOOP=off make e2e` **or** held path with that export before up + Playwright |

Subset (same cycle / slot machinery):

```sh
scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts'
```

CI matrix: `.github/workflows/e2e.yml` (`lane: [default, kill-switch, flag-off]`). Local slots: `docs/e2e-exploration.md` + root `Makefile` (`e2e` / `e2e-up` / `e2e-down` → `scripts/e2e-cycle.sh`). Dev app ports `:3000`/`:5000` are never used.

## PR test-plan snippet (paste into #866 / follow-ups)

```markdown
### W0.4 / W5 flag enable (operator; defaults stay off)

- [ ] Self-target only: `learning_loop` → read-only (`quiz_concept_plan`, `quiz_results_routing`, `item_reports`, `next_probe_hint`) → `__flags` prompts (`segment_prequestion`, `self_explanation_prompts`)
- [ ] `loop_tutor_v2` not enabled (deep `__v2` served gates not yet 1.0 × 3)
- [ ] No `REGISTRY` / everyone `default_variant: "on"` for `learning_loop` or prompt-change flags
- [ ] E2E default lane green (`make e2e` or held `make e2e-up` + Playwright + oracles)
- [ ] E2E kill-switch lane green (`LEARNING_LOOP_ENABLED=false make e2e`)
- [ ] E2E flag-off lane green (`SAPLING_FLAG_LEARNING_LOOP=off make e2e`)
- [ ] Rollout watches from `docs/learning-loop/flag-rollout.md` per flag
```

## What this does *not* do

- Turn `learning_loop` (or any prompt-change flag) on for everyone
- Change `backend/services/feature_flags.py::REGISTRY` defaults
- Re-record evals or run `make e2e-up` (operator / CI when slots free)
