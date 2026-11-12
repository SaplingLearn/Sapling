"""`services.study_guides.writer`: the agents are run, their usage is
recorded, a rejected block gets one rewrite, and failures are mapped."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from agents.deps import SaplingDeps
from agents.study_guide import BLOCK_REWRITE_MARKER, GuideOutline
from models.study_guide import GuideContent, Section, Source
from services.llm_budget import LLMBudgetExceeded
from services.study_guides import prompts, writer
from services.study_guides.errors import GuideGenerationFailed
from services.study_guides.materials import SourceText
from services.study_guides.prompts import Brief

DEPS = SaplingDeps(user_id="user_writer", course_id="course-cs", supabase=None,
                   request_id="req-writer", feature="study_guide")
BRIEF = Brief(
    scope_kind="exam", scope_label="Midterm 1", goal="exam_prep", depth="standard",
    sources=[SourceText(label="S1", source=Source(id="document:doc-1", name="loops.pdf", kind="PDF"),
                        concepts=["Loops"], text="A loop repeats a block.")],
    concepts=["Loops"], tiers={"Loops": "learning"}, mistakes=[],
)
SECTION = Section(id="s2", title="Loops", concept="Loops", tier="learning", weight=100,
                  one_line="A loop repeats a block.")
CONTENT = GuideContent(title="Control flow", sections=[SECTION])

KEY_TERMS = {"type": "key_terms", "title": "New here", "terms": [
    {"term": "Condition", "definition": "The test before each pass."},
    {"term": "Body", "definition": "The block a loop repeats."},
]}
FORMULA = {"type": "formula", "name": "Passes", "latex": "n", "spoken": "n passes", "source": "S1"}
BROKEN_FORMULA = '{"type": "formula", "name": "Passes", "latex": "n",}'


def fenced(block: dict | str, language: str = "block") -> str:
    return f"```{language}\n{block if isinstance(block, str) else json.dumps(block)}\n```"


class _Result:
    def __init__(self, output):
        self.output = output


class FakeAgent:
    """Answers each run with the next reply; an exception reply is raised."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.runs: list[dict] = []

    async def run(self, message, **kwargs):
        self.runs.append({"message": message, **kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return _Result(reply)


@pytest.fixture
def usage(monkeypatch):
    recorded: list[dict] = []

    def record(result, **kwargs):
        recorded.append({"output": result.output, **kwargs})
        return result

    monkeypatch.setattr(writer, "record_agent_usage", record)
    return recorded


def _agents(monkeypatch, *, outline=(), section=(), block=()):
    fakes = {"outline": FakeAgent(*outline), "section": FakeAgent(*section), "block": FakeAgent(*block)}
    for name, fake in fakes.items():
        monkeypatch.setattr(writer, f"study_guide_{name}_agent", fake)
    return fakes


def run(coro):
    return asyncio.run(coro)


def _write_section():
    return writer.awrite_section(BRIEF, CONTENT, SECTION, deps=DEPS)


def _budget_refusal() -> LLMBudgetExceeded:
    return LLMBudgetExceeded(limit=10, used=11,
                             reset_at=datetime.now(timezone.utc) + timedelta(hours=3))


# ── Runs and usage ────────────────────────────────────────────────────────────


def test_the_outline_is_the_outline_agents_output(monkeypatch, usage):
    outline = GuideOutline(title="Control flow", deck="Loops.", takeaways=["One."],
                           sections=[{"title": "Loops", "one_line": "A loop repeats."}])
    agents = _agents(monkeypatch, outline=[outline])

    result = run(writer.awrite_outline(BRIEF, low=3, high=5, deps=DEPS))

    assert result is outline
    (call,) = agents["outline"].runs
    assert call["message"] == prompts.outline_message(BRIEF, low=3, high=5)
    assert call["deps"] is DEPS
    assert call["usage_limits"].tool_calls_limit == 0


def test_an_update_outline_is_given_the_current_sections_and_what_is_new(monkeypatch, usage):
    agents = _agents(monkeypatch, outline=["unused"])

    run(writer.awrite_outline(BRIEF, low=1, high=3, deps=DEPS, current=[SECTION], new_labels=["S1"]))

    message = agents["outline"].runs[0]["message"]
    assert "CURRENT OUTLINE:" in message and "New since it was written: S1" in message


def test_every_run_records_its_usage_for_the_student(monkeypatch, usage):
    _agents(
        monkeypatch,
        outline=["the outline"],
        section=[f"Prose.\n\n{fenced(BROKEN_FORMULA)}"],
        block=[fenced(FORMULA)],
    )

    run(writer.awrite_outline(BRIEF, low=1, high=3, deps=DEPS))
    run(_write_section())

    assert len(usage) == 3
    assert usage[0]["output"] == "the outline"
    for record in usage:
        assert {k: record[k] for k in ("feature", "task", "user_id", "request_id")} == {
            "feature": "study_guide", "task": "study_guide",
            "user_id": "user_writer", "request_id": "req-writer",
        }


# ── A section ─────────────────────────────────────────────────────────────────


def test_a_section_with_sound_blocks_never_calls_the_block_agent(monkeypatch, usage):
    agents = _agents(monkeypatch, section=[
        f"A **loop** repeats a block [S1].\n\n>> Loops repeat.\n\n{fenced(FORMULA)}\n\n{fenced(KEY_TERMS)}",
    ])

    items = run(_write_section())

    assert [(item.id, item.type) for item in items] == [
        ("s2-i1", "prose"), ("s2-i2", "formula"), ("s2-i3", "key_terms")]
    assert items[0].paragraphs[0].citations == ["document:doc-1"]
    assert items[1].source_id == "document:doc-1"
    assert agents["block"].runs == []
    assert agents["section"].runs[0]["message"] == prompts.section_message(BRIEF, CONTENT, SECTION)


def test_a_rejected_block_is_rewritten_once_and_put_back_in_its_place(monkeypatch, usage):
    agents = _agents(
        monkeypatch,
        section=[f"Before.\n\n{fenced(BROKEN_FORMULA)}\n\nAfter.\n\n{fenced(KEY_TERMS)}"],
        block=[fenced(FORMULA)],
    )

    items = run(_write_section())

    assert [(item.id, item.type) for item in items] == [
        ("s2-i1", "prose"), ("s2-i2", "formula"), ("s2-i3", "prose"), ("s2-i4", "key_terms")]
    (rewrite,) = agents["block"].runs
    assert rewrite["message"] == prompts.block_message(
        BRIEF, CONTENT, SECTION, block_text=BROKEN_FORMULA, why=prompts.REWRITE_REJECTED)
    assert rewrite["message"].endswith(f"{BLOCK_REWRITE_MARKER}\n{BROKEN_FORMULA}")


def test_a_block_that_is_still_invalid_after_its_one_rewrite_is_dropped(monkeypatch, usage):
    agents = _agents(
        monkeypatch,
        section=[f"Before.\n\n{fenced(BROKEN_FORMULA)}\n\n{fenced(KEY_TERMS)}"],
        block=[fenced(BROKEN_FORMULA), fenced(FORMULA)],
    )

    items = run(_write_section())

    assert [(item.id, item.type) for item in items] == [("s2-i1", "prose"), ("s2-i3", "key_terms")]
    assert len(agents["block"].runs) == 1


def test_a_rewrite_of_another_type_is_dropped(monkeypatch, usage):
    agents = _agents(
        monkeypatch,
        section=[f"Before.\n\n{fenced(BROKEN_FORMULA)}"],
        block=[fenced(KEY_TERMS)],
    )

    items = run(_write_section())

    assert [item.type for item in items] == ["prose"]
    assert len(agents["block"].runs) == 1


def test_a_block_whose_type_cannot_be_read_is_dropped_without_a_rewrite(monkeypatch, usage):
    agents = _agents(monkeypatch, section=[
        f"Before.\n\n{fenced('not json at all')}\n\n{fenced({'type': 'flashcards', 'cards': []})}"
        f"\n\n{fenced({'title': 'No type'})}",
    ])

    items = run(_write_section())

    assert [item.type for item in items] == ["prose"]
    assert agents["block"].runs == []


def test_a_code_sample_is_prose_and_is_never_sent_to_the_block_agent(monkeypatch, usage):
    agents = _agents(monkeypatch, section=[
        f"A loop in Python:\n\n{fenced('for i in range(3):\n    print(i)', 'python')}\n\n>> It prints 0 to 2.",
    ])

    (passage,) = run(_write_section())

    assert passage.paragraphs[1].text == "```python\nfor i in range(3):\n    print(i)\n```"
    assert agents["block"].runs == []


def test_a_rewrite_that_fails_costs_only_its_block(monkeypatch, usage):
    agents = _agents(
        monkeypatch,
        section=[f"Before.\n\n{fenced(BROKEN_FORMULA)}\n\n{fenced(BROKEN_FORMULA)}\n\nAfter."],
        block=[RuntimeError("upstream timeout"), fenced(FORMULA)],
    )

    items = run(_write_section())

    assert [(item.id, item.type) for item in items] == [
        ("s2-i1", "prose"), ("s2-i3", "formula"), ("s2-i4", "prose")]
    assert len(agents["block"].runs) == 2


# ── Failures ──────────────────────────────────────────────────────────────────


def test_a_failed_run_is_generation_failed(monkeypatch, usage):
    _agents(monkeypatch, outline=[RuntimeError("boom")], section=[TimeoutError()])

    with pytest.raises(GuideGenerationFailed) as outline_error:
        run(writer.awrite_outline(BRIEF, low=1, high=3, deps=DEPS))
    with pytest.raises(GuideGenerationFailed):
        run(_write_section())

    assert outline_error.value.status_code == 502
    assert "boom" not in outline_error.value.detail
    assert usage == []


@pytest.mark.parametrize("wrapped", [False, True])
def test_a_budget_refusal_is_raised_as_itself(monkeypatch, usage, wrapped):
    refusal = _budget_refusal()
    error: Exception = refusal
    if wrapped:
        error = RuntimeError("the model run failed")
        error.__cause__ = refusal
    _agents(monkeypatch, outline=[error], section=[error], block=[error])

    for call in (
        writer.awrite_outline(BRIEF, low=1, high=3, deps=DEPS),
        _write_section(),
        writer.arewrite_block(BRIEF, CONTENT, SECTION, block_id="s2-i2", block_type="formula",
                              block_text="{}", why=prompts.REWRITE_ASKED, deps=DEPS),
    ):
        with pytest.raises(LLMBudgetExceeded) as raised:
            run(call)
        assert raised.value is refusal


def test_a_budget_refusal_during_a_rewrite_ends_the_section(monkeypatch, usage):
    _agents(monkeypatch, section=[f"Before.\n\n{fenced(BROKEN_FORMULA)}"], block=[_budget_refusal()])

    with pytest.raises(LLMBudgetExceeded):
        run(_write_section())


@pytest.mark.parametrize("reply", ["", "   \n\n", fenced("not json"), ">> Only a summary."])
def test_a_section_with_nothing_usable_is_generation_failed(monkeypatch, usage, reply):
    _agents(monkeypatch, section=[reply])

    with pytest.raises(GuideGenerationFailed):
        run(_write_section())


# ── One block ─────────────────────────────────────────────────────────────────


def _rewrite(block_type: str = "formula"):
    return writer.arewrite_block(
        BRIEF, CONTENT, SECTION, block_id="s2-i5", block_type=block_type,
        block_text=json.dumps(FORMULA), why=prompts.REWRITE_ASKED, deps=DEPS,
    )


def test_a_rewritten_block_keeps_the_id_it_was_asked_under(monkeypatch, usage):
    agents = _agents(monkeypatch, block=[f"Here it is.\n\n{fenced({**FORMULA, 'id': 'mine'})}"])

    block = run(_rewrite())

    assert (block.id, block.type, block.source_id) == ("s2-i5", "formula", "document:doc-1")
    message = agents["block"].runs[0]["message"]
    assert f"WHY: {prompts.REWRITE_ASKED}" in message
    assert message.count(BLOCK_REWRITE_MARKER) == 1
    assert len(usage) == 1


@pytest.mark.parametrize("reply", ["Sorry, I cannot.", fenced(BROKEN_FORMULA), fenced(KEY_TERMS)])
def test_a_reply_that_is_not_a_valid_block_of_the_same_type_is_none(monkeypatch, usage, reply):
    _agents(monkeypatch, block=[reply])

    assert run(_rewrite()) is None
    # The run happened and was paid for, so it is still recorded.
    assert len(usage) == 1
