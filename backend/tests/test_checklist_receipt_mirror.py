"""A settled topic-checklist bill gets what every other usage row gets (#866 Z54).

A learning-loop student's checklist run is billed by a durable receipt that
the `checklist_budget_reconcile` SQL writes into llm_usage with the cache, in
one transaction, so it never passes through `events_service.log_llm_usage` —
the only place that sends the privacy-mode `$ai_generation` PostHog mirror
(ADR 0028: "a run that reports here is covered") and settles the run's
`llm_budget` reservation (`note_usage_recorded`). The run still passed the
model chokepoint's budget gate, which reserved its tokens, so each checklist
left a phantom reservation for LAND_LAG_S and vanished from PostHog. Once
the receipt settles, `events_service.note_written_llm_usage` now does both
from the receipt row; the row is never queued a second time.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage, RunUsage

from agents.topic_checklist import TopicOutline
from services import checklist_budget as budget
from services import events_service
from services import topic_checklist_service as svc
from services.checklist_budget_run import ChecklistDispatches

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
GEMINI = "gemini-2.5-flash"
MODELS = ("anthropic:claude-haiku-5-5", f"gemini:{GEMINI}")
PAYLOAD = {"sources": [], "assessments": []}


@pytest.fixture
def reservation():
    return replace(budget.Reservation(uuid4(), "owner", "enrollment", "a" * 64, 7, models=MODELS),
                   dispatch_at=NOW)


def _generation(reservation, *, error=None):
    response = ModelResponse(parts=[TextPart("complete")], model_name=GEMINI, provider_name="google-gla",
                             usage=RequestUsage(input_tokens=100, output_tokens=20))
    tracker = ChecklistDispatches(reservation=reservation, dispatched=1, responses=[response])
    return svc.ChecklistGeneration(RunUsage(requests=1, input_tokens=100, output_tokens=20), tracker,
                                   outline=TopicOutline(topics=[]), error=error)


@pytest.fixture
def follow_ups(monkeypatch):
    """Every follow-up a usage row gets, recorded; nothing is queued."""
    from services import llm_budget

    seen = {"settled": [], "mirrored": [], "queued": []}
    monkeypatch.setattr(events_service, "_logging_enabled", lambda: True)
    monkeypatch.setattr(llm_budget, "note_usage_recorded", lambda user_id: seen["settled"].append(user_id))
    monkeypatch.setattr(events_service.posthog_client, "capture_ai_generation",
                        lambda **kw: seen["mirrored"].append(kw))
    monkeypatch.setattr(events_service, "_enqueue", lambda table, row: seen["queued"].append(table))
    return seen


def test_a_settled_receipt_settles_the_reservation_and_mirrors_once(monkeypatch, reservation, follow_ups):
    receipts = []

    def reconcile(r, *, receipt=None, content=None, no_dispatch=False):
        receipts.append(receipt)
        return {"state": "settled"}

    monkeypatch.setattr(budget, "reconcile", reconcile)
    svc._finish_generation(_generation(reservation), PAYLOAD)
    row = receipts[0].to_row()
    assert follow_ups["settled"] == ["owner"]
    assert follow_ups["mirrored"] == [{
        "user_id": "owner", "model": GEMINI, "provider": row["provider"], "input_tokens": 100,
        "output_tokens": 20, "cost_usd": row["cost_usd"], "request_id": row["request_id"],
        "feature": "topic_checklist", "task": "topic_checklist",
    }]
    assert row["cost_usd"] > 0
    assert follow_ups["queued"] == []  # the reconcile wrote the row; never queued again


def test_a_bill_that_did_not_settle_is_not_mirrored(monkeypatch, reservation, follow_ups):
    def reconcile(*args, **kwargs):
        raise RuntimeError("settlement unavailable")

    monkeypatch.setattr(budget, "reconcile", reconcile)
    with pytest.raises(RuntimeError):
        svc._finish_generation(_generation(reservation), PAYLOAD)
    assert follow_ups == {"settled": [], "mirrored": [], "queued": []}


def test_a_failed_outline_still_mirrors_its_settled_bill(monkeypatch, reservation, follow_ups):
    """A response that failed validation was billed: its settled bill is a real row."""
    monkeypatch.setattr(budget, "reconcile", lambda *a, **kw: {"state": "settled"})
    failure = ValueError("invalid outline")
    with pytest.raises(ValueError):
        svc._finish_generation(_generation(reservation, error=failure), PAYLOAD)
    assert follow_ups["settled"] == ["owner"] and len(follow_ups["mirrored"]) == 1


def test_no_dispatch_releases_without_a_mirror(monkeypatch, reservation, follow_ups):
    monkeypatch.setattr(budget, "reconcile", lambda *a, **kw: {"state": "released"})
    generation = svc.ChecklistGeneration(RunUsage(), ChecklistDispatches(reservation=reservation),
                                         error=ValueError("count preflight denied"))
    with pytest.raises(ValueError):
        svc._finish_generation(generation, PAYLOAD)
    assert follow_ups == {"settled": [], "mirrored": [], "queued": []}


def test_log_llm_usage_keeps_its_follow_ups(follow_ups):
    """The queued path is unchanged: one row queued, its reservation settled, one mirror."""
    events_service.log_llm_usage(feature="quiz", task="quiz", model="claude-haiku-5-5",
                                 usage=RunUsage(requests=1, input_tokens=10, output_tokens=5),
                                 user_id="u1", request_id="r1")
    assert follow_ups["queued"] == ["llm_usage"]
    assert follow_ups["settled"] == ["u1"]
    assert [m["model"] for m in follow_ups["mirrored"]] == ["claude-haiku-5-5"]


def test_with_usage_logging_off_the_bill_still_settles_its_hold_but_sends_no_mirror(
    monkeypatch, reservation, follow_ups
):
    """The receipt lands in llm_usage whatever EVENTS_LOGGING_ENABLED says (the
    reconcile writes it), so its hold must stop counting; the PostHog mirror
    rides the logging kill switch, as log_llm_usage's does."""
    monkeypatch.setattr(events_service, "_logging_enabled", lambda: False)
    monkeypatch.setattr(budget, "reconcile", lambda *a, **kw: {"state": "settled"})
    svc._finish_generation(_generation(reservation), PAYLOAD)
    assert follow_ups == {"settled": ["owner"], "mirrored": [], "queued": []}
