"""Assessment extraction shares PR #728's admission/receipt path, without cache publication."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from services import study_plan_service as svc


def test_plan_generation_uses_budgeted_dispatch_without_replacing_course_outline(monkeypatch):
    reservation = object()
    generation = SimpleNamespace(outline=object())
    admit = Mock(return_value=reservation)
    finish = Mock()
    monkeypatch.setattr(svc.checklist_budget, "admit", admit)
    monkeypatch.setattr(svc.ai_budget, "check", lambda *args: SimpleNamespace(level="normal"))
    monkeypatch.setattr(svc.checklist, "_finish_generation", finish)
    calls = []

    async def generate(payload, user_id, admitted, **kwargs):
        calls.append((payload, user_id, admitted))
        return generation

    monkeypatch.setattr(svc.checklist, "_generate", generate)
    payload = {"sources": [], "assessments": []}
    assert svc.generate_topics(payload, "u", "enrollment") is generation.outline
    assert calls == [(payload, "u", reservation)]
    assert admit.call_args.args[:2] == ("u", "enrollment")
    assert len(admit.call_args.args[2]) == 64
    finish.assert_called_once_with(generation, payload, publish=False)


def test_budget_unavailability_releases_undispatched_reservation(monkeypatch):
    reservation = object()
    reconcile = Mock()
    monkeypatch.setattr(svc.checklist_budget, "admit", lambda *args: reservation)
    monkeypatch.setattr(svc.checklist_budget, "reconcile", reconcile)
    monkeypatch.setattr(svc.ai_budget, "check", Mock(side_effect=svc.ai_budget.AIBudgetUnavailable()))
    with pytest.raises(HTTPException) as error:
        svc.generate_topics({"sources": []}, "u", "enrollment")
    assert error.value.status_code == 503
    reconcile.assert_called_once_with(reservation, no_dispatch=True)


def test_hard_budget_blocks_dispatch_and_releases_the_reservation(monkeypatch):
    reservation = object()
    reconcile = Mock()
    generate = Mock()
    monkeypatch.setattr(svc.checklist_budget, "admit", lambda *args: reservation)
    monkeypatch.setattr(svc.checklist_budget, "reconcile", reconcile)
    monkeypatch.setattr(svc.ai_budget, "check", lambda *args: SimpleNamespace(level="hard"))
    monkeypatch.setattr(svc.checklist, "_generate", generate)
    with pytest.raises(svc.ai_budget.AIBudgetExceeded):
        svc.generate_topics({"sources": []}, "u", "enrollment")
    generate.assert_not_called()
    reconcile.assert_called_once_with(reservation, no_dispatch=True)


def test_receipts_settle_without_publishing_assessment_topics(monkeypatch):
    receipt = object()
    reservation = SimpleNamespace(operation_id="operation", user_id="u", dispatch_at=None)
    tracker = SimpleNamespace(reservation=reservation, dispatched=1, responses=[object()], nonbillable_test=False)
    generation = SimpleNamespace(dispatches=tracker, usage=object(), outline=object(), error=None)
    reconcile = Mock()
    monkeypatch.setattr(svc.checklist, "validate_evidence", Mock())
    monkeypatch.setattr(svc.checklist, "prepare_checklist_usage_receipt", lambda **kwargs: receipt)
    monkeypatch.setattr(svc.checklist_budget, "reconcile", reconcile)
    svc.checklist._finish_generation(generation, {"sources": []}, publish=False)
    reconcile.assert_called_once_with(reservation, receipt=receipt, content=None, no_dispatch=False)


def test_combined_agent_retries_unsupported_evidence_and_returns_guide_points():
    from agents.assessment_guide import assessment_guide_agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    calls = []

    def handler(messages, info):
        value = {"overview": "Review functions before recursion.", "topics": [{
            "name": "Functions", "description": "Inputs and outputs.", "importance": 0.8,
            "source_ids": ["unknown" if not calls else "document:notes"],
            "study_points": ["Explain how inputs map to outputs."],
        }]}
        calls.append(value)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, value)])

    with assessment_guide_agent.override(model=FunctionModel(handler)):
        result = assessment_guide_agent.run_sync("Generate assessment guide", deps={
            "sources": [{"id": "document:notes"}], "assessments": [],
        })
    assert len(calls) == 2
    assert result.output.overview == "Review functions before recursion."
    assert result.output.topics[0].study_points == ["Explain how inputs map to outputs."]
