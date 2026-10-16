"""Fixed `decision` answers shared by the function-mode handler modules.

The E2E and showcase handler modules must not import each other — importing
one runs its registrations as a side effect (see function_handlers_showcase's
docstring) — so a constant both register lives here, in a module with NO
side effects. Underscore-prefixed so the agent-discovery scan in
tests/test_agent_output_schemas.py skips it.

The tutor router's five keys (services/tutor_router.py, #640), every answer
ABOVE the default confidence floor so the lanes exercise the "answer applied"
path rather than the defaults path. They are deliberately the answers the
router's safe defaults would give anyway (retrieve, no rewrite, not graded,
not an injection) plus a complexity — and nothing acts on them
(observe-only), so no journey's or screenshot's visible behaviour depends on
them. Pinned by tests/test_e2e_function_handlers.py.
"""

from __future__ import annotations

DECISION_ANSWERS: list[dict] = [
    {"key": "needs_retrieval", "value": "yes", "confidence": 0.9},
    {"key": "needs_rewrite", "value": "no", "confidence": 0.8},
    {"key": "complexity", "value": "medium", "confidence": 0.7},
    {"key": "is_graded_work_request", "value": "no", "confidence": 0.95},
    {"key": "injection_attempt", "value": "no", "confidence": 0.99},
]
