# Changing the loop safely

The loop is unusually easy to break silently. A wrong number does not crash
anything: it gives students credit they did not earn, or withholds credit they
did, or leaks an answer, and every screen still looks fine. This checklist
exists because each item below was learned from such a failure; the §13 row
cited with each item tells the story. Commands for every test lane are in
[operations.md](operations.md#test-lanes); the rules themselves are in
[invariants.md](invariants.md).

## The checklist

Work through it top to bottom for any change to `backend/learning/`,
`backend/routes/learn_loop.py`, a loop agent, a learning migration or a
learning screen.

### 1. Write the spec row first

- Add a row to the spec's §13 amendments table
  ([the spec](../superpowers/specs/2026-09-26-learning-loop-design.md)) with
  the next free number, what changes, why, and what it affects. Rows override
  the spec's earlier sections, so the row is where the next engineer will look
  for the reason.
- Every number the loop uses lives in `backend/learning/params.py` under a
  name; code cites the name. Mark a value with **†** when it is an engineering
  choice without a validated cut-point. A bare numeric literal in loop code is
  a review failure (the module's docstring says so).
- Add a line for the row to [amendments.md](amendments.md).

**Why:** the loop's behaviour is the sum of 130-odd decisions, most of them
counter-intuitive until you read the case that forced them (for example A81,
built and then reverted by A83). A change without a row is a decision nobody
can find.

### 2. Put risky behaviour behind a flag

- Declare the flag in `backend/services/feature_flags.py::REGISTRY`, with
  `variants[0] == "off"` (the fail-closed answer) and `client_visible` only
  when the frontend must branch on it. Never gate with a new env var or a
  `user_settings` column (repository rule).
- Resolve it **once** per request, turn or upload and carry the answer down
  (see `backend/services/loop/flags.py::_tutor_v2_on`,
  `backend/services/loop/flags.py::_help_gate_strict_on` and
  `backend/services/concept_prereqs.py`). Resolving twice in one request can
  mix two behaviours in one turn.
- A flag that changes **what is measured** — which item is the pretest
  (`probe_matched_pretest`), when the post-test is offered
  (`retention_due_badge`) — is switched at a trial boundary, recorded, and
  kept for the whole cohort (readiness record, wave-2 items 4–5).

### 3. Keep the flag-off request byte-identical when a recorded prompt changes

If the change touches a prompt, an output schema or the message a model sees
on a slot whose quality was **recorded** (any evidence slot; see
`backend/agents/_providers.py::EVIDENCE_SLOTS`), then with the flag off the
model request must be byte-for-byte what it was. The eval cassettes and
baselines were recorded against that request; a changed request makes every
replayed score meaningless. The flag-on variant gets its own cassettes,
recorded live and passing before the flag is turned on — the pattern is
`LOOP_EVAL_VARIANT=v2` in `backend/tests/evals/loop_tutor.py` (A121), and
A118's upload extraction is the other worked example. Wave 4 shows how to
pin it: `backend/tests/test_learning_teach_prompts_flag_off.py` digests whole
route scenarios (the assembled model request, every run argument, the served
text, the response, the saved rows) against digests captured from the
pre-feature commit, and `backend/tests/test_learning_varied_drafting.py`
does the same for every drafting request.

### 4. A new model task needs the full slot wiring

For a new agent task (slot):

- Add it to the `AgentTask` literal, `_DEFAULTS` **and** `_ANTHROPIC_EFFORT`
  in `backend/agents/_providers.py`. A slot whose default is a `gemini-*`
  model must be in `LOOP_SLOTS_PENDING_CLAUDE_EVAL` and every other must
  default to Claude (`backend/tests/test_anthropic_provider.py` pins this).
- If its output is evidence or what evidence is graded against, add it to
  `EVIDENCE_SLOTS` with its evaluated model set (A128), and if it must be
  independent of another slot's model family (as `grader_second` is of
  `grader`, and `check_items_solve` of `check_items`), say so there.
- One system prompt and one `Agent(` per module (spec §8 invariant 12; add the
  module to `SERIES_AGENT_MODULES` in
  `backend/tests/test_learning_loop_invariants.py`).
- Call `ai_budget.check(` before every run, in the same function
  (invariant 23), and record usage through
  `backend/agents/usage.py::record_agent_usage` with the `session_id` and
  `course_id` you have.
- Register a function-mode handler in
  `backend/agents/function_handlers_e2e.py` if the task runs on a request
  path (an unregistered task raises `UnregisteredHandlerError` in the E2E
  lanes), add the task to `SERIES_AGENT_TASKS` (invariant 6), and keep its
  constants, the Playwright assertions and
  `backend/tests/test_e2e_function_handlers.py` in sync. Post-response
  background tasks stay unregistered on purpose.

### 5. Evidence goes through one door

- Build an `Evidence` (`backend/learning/evidence.py::Evidence`), append it to
  `deps.pending_evidence`, and let the route call `flush_pending` once.
  Nothing else writes `node_mastery_events`, `learner_state`, `graph_nodes` or
  `graph_edges` (invariant 1).
- Evidence comes only from an explicit answer submission (A16). A new
  submission handler joins the allow-list in
  `test_inv_26_evidence_only_from_explicit_submission`. A new learning
  activity that is not a measurement — a guess before teaching (A138), an
  explanation after help (A139) — stays off that list: store it for
  diagnosis if you must, but never grade it or let it reach the writer.
- A new kind of item that is not a plain single-concept question decides,
  in a spec row, what one answer to it is evidence of and at what weight
  (A141's answer: one half-weight observation on the apex, components only by
  propagation), and makes the weight a flag on `Evidence` that is dumped only
  when set, so every other evidence row and fingerprint stays unchanged.
- Take the help floor from the ledger (`backend/learning/help_ledger.py::max_help`)
  immediately before the write (A93), and claim the item before grading
  (A52) so it is graded once.
- When the grader is unavailable or capped, record **nothing** — for a right
  answer and a wrong one alike (invariant 28). Recording only one outcome
  biases the belief.

### 6. Anything a student reads is leak-checked; anything a student writes is data

- Every payload code serves below H6 passes `leak.detect_leak` with the
  item's final answer before it is emitted (invariant 27). Model text is
  leak-checked as it streams (cut before a leaking sentence, replaced by the
  ladder's fallback line if the final text still leaks), and every served
  text is scanned against the student's open posed items (A88, A101).
- Student text reaches a model only inside the nonce envelope
  (`backend/agents/loop_tutor.py::student_envelope`, A51) or the untrusted
  envelope of `backend/services/prompt_safety.py`. Policy never reads it
  (invariant 4); only the fixed phrase lists in `backend/learning/gates.py` do.
- A new student-facing AI surface outside the loop that takes request text
  runs `backend/services/integrity_guard.py::open_guard` (A125).
- Event payloads carry ids, counts, enums and numbers only; add each new event
  type to `EVENT_TAXONOMY` in `backend/services/events_service.py`
  (invariant 5).

### 7. Encrypt at the boundary

A new column holding student text, an item's text or key, or anything derived
from them is encrypted at write (`encrypt_if_present` / `encrypt_json`) and
decrypted at read, including before it is put in a prompt
(`backend/services/encryption.py`). Then: add it to the encryption list in
`CLAUDE.md`, to the ciphertext oracle's manifest in
`backend/e2e_oracles/gather.py` (`_CIPHERTEXT_MANIFEST`), and to invariant 9's
list (no `UNIQUE`, no `eq.` filter on ciphertext). Lookups key on a plaintext
hash column instead, as `question_hash` does.

### 8. Migrations: additive, timestamped, ordered before the code

- Name the file `<UTC YYYYMMDDHHMMSS>_learning_<desc>.sql` in
  `backend/db/migrations/` (invariant 8 checks the pattern; get the stamp from
  `date -u +%Y%m%d%H%M%S`). Never edit an applied file; the same invariant
  fails if git shows a learning migration modified.
- Make it additive and compatible with the code before it, and write down the
  order: most learning migrations must be applied **before** the code (the
  "release fence"), and some must ship in the same run as another (A123 ×
  A127's three re-creations of `learning_evidence_commit`). Add the order to
  the rollout section of the
  [readiness record](../operations/learning-engineering-readiness.md).
- If code depends on a new column or RPC signature, add it to the release
  verifier's critical inventory (`backend/scripts/learning_release_verify.py`)
  so `--db-audit` refuses a database without it.
- Exercise the SQL against a real database in `backend/tests/integration/`.

### 9. Test every lane the change touches

- Unit tests (hermetic: no network, no live model) for the logic; a pure
  module gets exhaustive tests and, if new, an entry in `PURE_MODULES`.
- The invariants file (`backend/tests/test_learning_loop_invariants.py`) when
  you add a writer, a submission handler, an agent module, an event or an
  encrypted column.
- Integration tests for SQL functions, locks and races.
- Eval replay for a prompt or schema change; a live re-record (owner-run, it
  costs money) when the request changed.
- The E2E default lane **and** the kill-switch lane for anything a student
  sees, plus the oracles; the accessibility lane for UI.

### 10. Pair a bug fix with a regression journey

A bug fix in territory the E2E lanes cover gets a promoted regression journey
in `frontend/e2e/` (recipe: [the E2E guide](../e2e-exploration.md), sections
7–8; journeys use the fixtures in `frontend/e2e/support/fixtures.ts` and DB
asserts from `frontend/e2e/support/db.ts`). The loop's main journey is
`frontend/e2e/learn-loop.spec.ts`.

### 11. Update the docs that pin the code

- This guide: a moved or renamed function breaks
  `backend/tests/test_learning_guide_paths.py`, which is the point — fix the
  page, not the test.
- `CLAUDE.md`'s repo map when a new module is one an engineer must know.
- An ADR in `docs/decisions/` for an architectural decision (the evidence
  transaction, the decision-seam split and the grade checkpoints each have
  one).

## Smells that mean stop and re-read the invariants

- A route that writes `learner_state` "just this once".
- A policy function that takes a `str`.
- A model call without `ai_budget.check` above it in the same function.
- Evidence recorded for a correct answer when the grader timed out — or for a
  wrong one.
- An item served without passing `is_servable`, or a picker that does not
  exclude the seen, revealed and reported sets and the post-test reserves.
- A log line, event payload or exception message that contains an answer, a
  rubric or student text.
- A `DELETE` or `UPDATE` on `node_mastery_events` or `learning_evidence_voids`.
- A migration edited after it was applied anywhere.
