"""
backend/services/loop/ — the learning loop's domain (#118).

What used to be ``routes/learn_loop.py`` (8,893 lines). The route is now the
HTTP surface only; each handler's body lives here under the handler's own
name, and every helper and constant moved under its old name.

Routing is code: learning.policy.model_tier picks the tier slot after
services.ai_budget.check has read the student's budget — in the same function
as every model run (invariant 23); each tutor model run is counted with
ai_budget.count_tutor_call right before it (A39). Context comes from
learning.policy.context_policy, assembled with the legacy block builders.
The tutor's output is the STRUCTURED turn (`learning.turn_shape.LoopTurnOut`),
served as `render_turn(...)`; streaming rides
services.chat_stream.stream_structured_turn with a leak-strip transform, and
the loop stream events are yielded AROUND it. A tool run that ends without a
turn (#646: flash-lite answers empty after a tool call) is finished by the
tool-less continuation. Evidence is written ONLY by the explicit-submission
writers (`_grade_submission`, `_probe_submission`, `posttest_answer` and the
review's `grade_review`; invariant 26). The reference answer of the active
check item lives only on the turn object — never in deps, the prefix, a log
line, or an event payload.

The gate (`learning.gate.learning_loop_for_request`) is read ONCE per request,
at route entry (A38 00); a delegating legacy route carries its own read in on
`request.state.learning_loop`, and the result rides on
`SaplingDeps.learning_loop`.

Loop state: PKG-06's `learning.loop_state_store` returns the typed `LoopState`;
the loop reads its JSON document (`LoopState.to_json()`) and writes ONLY
through `update_loop_state` (compare-and-set, A38 06(q)) with a mutate closure
over that document, re-validated by `LoopState.from_json`. A closure expresses
this request's own change and has no side effects (it is re-applied on a
conflict); events and message rows follow the save. The spec's
`loop_state["active"]` is the document's `current`, and the spec's per-item
`loop_state[qh]` entry is `steps[qh]`: PKG-06 owns its `rung`, `attempts`
(failed genuine attempts while the step is open), `first_shown_at`,
`last_rung_at`, `attempted_at` (Unix seconds), `showed_work` and `exam_mode`;
every other per-item key is this package's (HANDOFF-07 Deviations). The
session is checked to be the requesting student's before any read or write.

Every module logs as ``routes.learn_loop``, the name the route always logged
under (services/ops_logging.py and the tests key on it).

Modules, lowest first (each imports only the ones above it):

- ``errors``: the package's one ``fastapi`` import (``HTTPException``).
- ``posed``: the A93/A101 scan set (``posed_items``; was
  ``services/loop_posed.py``), read by the loop and by
  ``services/integrity_guard.py``.
- ``constants``: The loop's fixed texts and details: the 404/429 bodies, the
  feedback lines, the refusal and unavailable replies, the 409 details and the
  probe-phase opener template (moved verbatim from routes/learn_loop.py,
  #118).
- ``flags``: The loop's per-student feature flags (`loop_tutor_v2`,
  `help_gate_strict`, `segment_prequestion`, `self_explanation_prompts`), the
  loop_state keys they gate, and the server-side `[ACTION: ...]` cues.
- ``state``: The request's loop state: the route-entry gate (require_self +
  the loop gate, A38 00), the session's scope and arm, the budget pause, the
  PKG-06 loop state document (read, compare-and-set update), its phase and the
  guards a handler checks before it writes (open, teaching, closing, grading
  in flight).
- ``history``: The tutor's message history for a loop turn: the learner brief
  request (A19), the history window and the brief's node ids.
- ``learner``: What the loop knows about the student on a concept: the item's
  graph node, the BKT band, prerequisites, the learner view the policy reads,
  the genuine attempt rule and the band ceiling.
- ``context``: A planned turn's context (spec §3.4): the course, catalog,
  retrieval and graph blocks, the A128 materials notice, and
  `_prepare_loop_run`.
- ``continuation``: The #646 rescue: the tool-less continuation that finishes
  a run that ended without a structured turn, and the run's request count.
- ``served``: Served text (A38, A84): the leak rung, the ladder's fallback
  lines and the `served_*` renderers, `served_model_text` and the items a turn
  states.
- ``reveals``: Reveals and the help floor (A88, A93): what a served turn
  revealed, the reveal floor a grade reads, the planning-evidence tags and the
  help ledger.
- ``guard``: The served-text leak guard (A38) and the misconception
  confrontation line (PKG-10, A76).
- ``planning``: Goal and plan state shared by the probe, plan and teach paths:
  the goal's scope and version, the probe document and its items, the plan
  read and the goal's practice pool (spec §13 A143-A146).
- ``cursor``: The check cursor: the leak-checked pose payload, the H6 gate and
  the cursor's advance with its reason.
- ``pose``: The segment prequestion's pose (A138), the self-explanation
  prompts (A139) and the teach-prompt juncture they open.
- ``practice``: The next check (spec §10): band control (A122), the target
  difficulty, worked examples, the isomorph re-ask and `_activate_next_item`.
- ``turn``: `_LoopTurn`: one loop turn, shared by the JSON and streamed run
  sites (phase, band and ceiling before the budget read; plan; complete).
- ``opener``: `_LoopOpener`: the session opener (A27, A121) and the quiz-ask
  state it carries.
- ``runner``: The run sites: the JSON turn and the SSE turn (budget, plan, one
  model run or the deterministic text, complete) and the guardrail mapping
  around them.

The names below resolve lazily, so importing this package (the legacy tutor's
hand-off and the integrity guard do, at call time) loads no module of it until
a name is used: nothing of the loop loads at boot but through its route.
"""
from __future__ import annotations

import importlib

_PUBLIC = {
    "_NOT_ENABLED": "constants",
    "posed_items": "posed",
}

__all__ = sorted(_PUBLIC)


def __getattr__(name: str):
    module = _PUBLIC.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)
