# W2.3 Reason-before-submit (evidence-safe)

Optional “show your reasoning” on **free** and **teachback** loop checks.

## Storage

Nested ciphertext on the check step inside `sessions.loop_state`:

- Key: `reasoning_encrypted`
- Binding: `encryption.nested_bind("sessions", "loop_state", "reasoning_encrypted", session_id)`
- Registry: `encryption.NESTED_CIPHERTEXTS` + `account_bundle.NESTED_ENCRYPTED`
- Writer: `learning/check_reason.py` (called from `services/loop/grading.py` under the grading claim)

No dedicated table. Same durability as a pending `grade_checkpoint` on the step.

## Hard invariants

| Rule | How |
|---|---|
| Reasoning never calls `apply_graph_update` / never bumps `p_known` | Store module has no graph/evidence imports; route stashes under claim then grades `CheckAnswer` without the field |
| Grader inputs = answer + rubric only | `CheckAnswer` gets `answer_text` / `selected_option` / `reason` (mc) — never `reasoning` |
| Encrypted at rest | Nested AES-GCM; plaintext never left on the step |
| mc_reason | Optional `reasoning` is ignored; graded one-sentence field stays `reason` |

## API / UI

- Body field: `LoopCheckAnswerBody.reasoning` (optional; max = grader answer cap)
- UI: `CheckCard` — textarea labelled **Your reasoning (optional)** for free/teachback only (`data-testid="loop-attempt-reasoning"`)
- Not required to submit; empty omits the field on the wire

## Non-goals (this slice)

- W2.4 low-trust next-probe routing from reasoning text — see [w2-next-probe-hint.md](./w2-next-probe-hint.md)
- Mastery or evidence from self-explain / reasoning

## E2E

`frontend/e2e/learn-loop.spec.ts` — "W2.3 reason-before-submit" (default lane), on
`python -m scripts.seed_learning_check_beats reason` (one free + one mc_reason item):

- free: the box is optional and never the answer (reasoning alone leaves Submit
  disabled); the reasoning carries the grader's correct token while the answer
  does not, and the check grades **not yet** with one `correct=false` evidence
  row — the reasoning is not a grader input and not evidence; it lands as
  `reasoning_encrypted` ciphertext (nested-bind decrypt), absent from the
  plaintext of `loop_state` and of every transcript row.
- mc_reason: no optional box; Submit stays disabled until an option AND a
  non-blank reason (K02); a `reasoning` field a client adds anyway is dropped
  (no `reasoning_encrypted` on the step); the graded reason rides the encrypted
  transcript as `(<letter>) <reason>`.
