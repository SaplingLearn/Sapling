"""Opt-in LIVE test: the slot's real model actually serves the topic-checklist output schema.

The hermetic suite (tests/test_topic_checklist_schema_states.py) pins that the
schema carries no array-length bounds, but only the real model can say whether
the compiled constraint fits its serving limit. #726's nested `maxItems`
bounds passed every hermetic test and 400'd every live refresh ("The specified
schema produces a constraint that has too many states for serving") — this
case is the one that would have caught it.

It runs the REAL `topic_checklist_agent` (system prompt, `final_result` output
output, reference validator) against the real `topic_checklist` model slot
(Claude since ADR 0030 — whose strict JSON mode cannot express the bounds at
all; a gemini-* override re-arms the original "too many states" risk) with a
small fixture payload, so the call touches no database:

    RUN_LIVE_TOPIC_CHECKLIST=1 pytest tests/test_live_topic_checklist_schema.py

Marked `live_llm` (documented opt-out of the hermetic transport guard,
tests/conftest.py) and skipped otherwise. One billable run.
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.live_llm

_OPTED_IN = os.getenv("RUN_LIVE_TOPIC_CHECKLIST") == "1"

_PAYLOAD = {
    "course": {"code": "CAS CS 111", "name": "Introduction to Computer Science 1"},
    "sources": [
        {"id": "course-description", "label": "BU course description",
         "text": "Introduction to programming in Python: variables, conditionals, loops, "
                 "functions, recursion, lists and dictionaries."},
        {"id": "document:lecture-5", "label": "Lecture 5.pdf",
         "text": "Recursion: base case and recursive case. Recursion builds on functions."},
    ],
    "assessments": [{"id": "midterm", "title": "Midterm 1", "due_date": "2026-10-30",
                     "assignment_type": "exam"}],
    "existing_topic_names": [],
}


@pytest.mark.skipif(
    not _OPTED_IN,
    reason="opt-in live test: set RUN_LIVE_TOPIC_CHECKLIST=1 (and the slot provider's key)",
)
def test_real_model_serves_the_topic_checklist_schema():
    # Opted in but unconfigured is a failure, never a silent skip: the run
    # was asked to check the live schema and must not report success unchecked.
    from agents._providers import api_key_env_for_model, model_mode, model_name_for

    key_var = api_key_env_for_model(model_name_for("topic_checklist"))
    assert os.getenv(key_var), f"RUN_LIVE_TOPIC_CHECKLIST=1 needs {key_var}"

    # Checked BEFORE the billable run: under the function-mode seam the call
    # would hit a stand-in handler and prove nothing about the real schema.
    assert model_mode() == "real", "the live schema check needs SAPLING_MODEL_MODE unset (real mode)"
    from agents.topic_checklist import MAX_TOPICS, topic_checklist_agent
    from services.topic_checklist_service import validate_evidence

    # A schema the model cannot serve fails here, on the first request, with
    # ModelHTTPError 400 INVALID_ARGUMENT — before any generation.
    result = topic_checklist_agent.run_sync(json.dumps(_PAYLOAD), deps=_PAYLOAD)

    topics = result.output.topics
    assert 1 <= len(topics) <= MAX_TOPICS
    validate_evidence(result.output, _PAYLOAD)
