# 0027: A typed decision seam; one non-Gemini backend admitted behind it, post-series

- Status: accepted
- Date: 2026-09-27
- Relates to: learning-loop spec `docs/superpowers/specs/2026-09-26-learning-loop-design.md`
  §3.6 and §13 A24 (owner decision 5), #640 (turn routing / rerank), #641 (upload
  classification), #642 → PKG-15 (the Jev backend), ADR 0008 (per-task model
  routing), ADR 0019 (the `SAPLING_MODEL_MODE` function-model seam)
- Supersedes: none. Amends ADR 0024's "there is no other sanctioned LLM seam" for
  exactly one future backend (`agents/_jev.py`, PKG-15).
- Amended by: ADR 0031 (PKG-15, 2026-10-01). The Jev backend is built: `jev` serves
  three decisions and never grading (`jev_unsupported`), and `shadow_jev` runs in the
  background. The "Until PKG-15" clauses below are history.

## Context

The learning loop asks models closed questions, not open ones: does this answer
satisfy rubric item r2; is this mc_reason reason correct; which listed wrong
reason does this answer express; can the reference be derived from these
passages; does this emitted hint reveal the reference, even by paraphrase. #641
(is this upload course material?) and #640 (which passages matter; how hard is
this turn?) ask the same shape of question. Each is a small typed judgment over
a short text state.

Typesafe's Jev answers closed questions with per-option probabilities in about
100 ms (vendor-stated), but it cannot generate text. Decision calls are under 1%
of the loop's model spend (spec §3.5), so cost is not the reason for this seam:
provenance, a per-decision backend switch and a way to shadow a candidate are.

## Options considered

1. **Direct agent calls** at each site (the grader, a leak judge, a key matcher).
   Rejected: no provenance on the verdict, no backend switch, nothing to shadow
   and nothing to compare a candidate backend against.
2. **A typed seam now, backed by Gemini, function mode and code; Jev later
   behind flags and a privacy gate** (chosen).
3. **Jev now.** Rejected: waitlist access only, no student-data terms, and its
   known weaknesses (math, literal reading, adversarial state) are unmeasured on
   our decisions.

## Decision

- `backend/services/decisions.py` owns every closed decision the loop asks a
  model. States are text only — no user id, email or name field (spec §8
  invariant 25), built from decrypted item fields and held in memory only. Every
  answer is a typed `Verdict` (`YesNo`, `Pick`, `RubricVerdict`, `ReasonVerdict`)
  that carries `Verdict.backend`. When no backend answers, the function returns
  `None` and the caller records nothing, for either outcome (invariant 28).
- Grading delegates to `agents/grader.py::grade()` — one call, the same prompt,
  the same `llm_usage` rows, so there is no second prompt stack (ADR 0024's rule
  holds). `grade_answer` grades through the seam with byte-identical grader
  messages. The other decisions run `agents/decision.py` (task `decision`,
  Flash-Lite, thinking off, one prompt, output type per run). Code-computed
  checks (`numeric_gate`) are the `deterministic` backend: no model, no
  `llm_usage` row, and never a "correct" verdict on a strong channel (A22).
- Each decision is selected by env `DECISION_BACKEND_<NAME>` ∈ {`gemini`
  (default), `jev`, `shadow_jev`}. `JEV_ENABLED=false` (the default; only `true`
  enables it) is the global kill switch that overrides every one of them to
  Gemini. Function mode (ADR 0019) serves every decision from fixed
  `E2E_DECISION_*` constants and never builds a Jev client. Until PKG-15, `jev` is
  served by Gemini with a `decision.fallback{reason: jev_absent}` event and
  `shadow_jev` is a no-op. Events `decision.made` / `decision.shadow` /
  `decision.fallback` carry ids, enums and numbers only.
- Loop routing stays in code (`learning/policy.model_tier` /
  `context_policy`): the seam never picks a tutor tier. A model-based
  `route_turn` would serve only the legacy `chat_tutor` (#640).
- **ADR 0024 is amended** to admit exactly one non-Gemini model seam:
  `backend/agents/_jev.py` (PKG-15). It is the only importer of the Python
  `typesafe-sdk==0.7.2` package, pinned exactly (spec §8 invariant 24); no Java SDK
  exists and none is used. The model is pinned to `jev-1.13.0`, never an alias.
  The client is built only when `model_mode() == "real"` and `JEV_ENABLED`, and it
  is reached only through `services/decisions.py`. Every confidence-gated decision
  uses a Choice (per-option probabilities), and its `llm_usage` rows carry
  `provider='typesafe'`. Until PKG-15 no `typesafe` code or dependency exists.
- `system-one-adapter-python` stays out of application code: it builds an
  ungated Gemini client below the `agents/_providers.py` seam (#439). It may
  appear in offline benchmark scripts only.

## Privacy gate

It must pass before any student-derived text reaches Typesafe — live, shadow,
historical or eval:

- an enterprise contract with zero data retention;
- a signed DPA, with the subprocessor list reviewed;
- FERPA "school official" and under-18 terms;
- a privacy notice that names Typesafe;
- SOC 2 or an equivalent attestation;
- acceptance of US hosting;
- data minimisation in code (States carry no identifiers; invariant 25).

Until then Jev runs offline only, on synthetic or consented de-identified gold
sets (`tests/evals/decisions.py` refuses any other provenance). Promotion is per
decision, shadow → serve, against every §3.6 gate (gold volume, accuracy drop,
kappa, calibration, false positives, injection flips, BKT replay delta, live
shadow duration/volume/agreement, p95 latency, error rate, cost).

## Consequences

- (+) `grade_answer` grades through the seam with byte-identical grader prompts
  and `llm_usage` rows; `Evidence.grader_backend` comes from the verdict's
  provenance.
- (+) `decision.*` events make provenance and outages countable; the eval
  harness measures the Gemini baseline and computes every promotion gate, and it
  refuses unconsented gold.
- (−) Vendor risk, if PKG-15 lands: a new company; early access with dynamic
  rate limits; no self-hosting; possibly subsidised pricing; zero retention on
  enterprise terms only; no stated SLA, FERPA, COPPA or SOC 2 posture. Flipping
  `JEV_ENABLED` off removes Jev from every decision at once.
- (−) One more layer between the loop and its grader. Contained: the seam adds
  no prompt, no usage row and no retry of its own.
- PKG-15 updates `CLAUDE.md`'s LLM-seam convention (the list of sanctioned raw
  client sites) when `agents/_jev.py` lands; this ADR changes no convention text
  before then.

## Revert path

Git history: revert the PKG-05b commits. `grade_answer`'s reopen commit restores
the direct `agents.grader.grade()` call; no migration, no data shape and no
dependency changed.
