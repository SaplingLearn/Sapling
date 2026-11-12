"""`services.study_guides.blocks`: one block is written again and saved in
place, under the guide's claim, and nothing around it moves."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from models.study_guide import (
    ChartBlock,
    ChartPoint,
    ChartSeries,
    CheckBlock,
    CheckOption,
    ConceptMapBlock,
    ConceptMapNode,
    FormulaBlock,
    GuideContent,
    KeyTerm,
    KeyTermsBlock,
    Paragraph,
    ProseItem,
    Section,
    Source,
)
from services import request_limits
from services.encryption import encrypt_json
from services.llm_budget import LLMBudgetExceeded
from services.study_guides import blocks, limits, prompts, writer
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideNotFound,
    GuideRateLimited,
)
from tests.test_study_guides_generation import (  # noqa: F401 (fixtures)
    GUIDE,
    MADE_AT,
    World,
    function_mode,
    world,
)
from tests.test_study_guides_store import ME

DOC = "document:doc-1"
KEY_TERMS = KeyTermsBlock(id="s1-i2", title="New in this section", terms=[
    KeyTerm(term="Base case", definition="The input answered directly."),
    KeyTerm(term="Recursive step", definition="The call on a smaller input."),
])
FORMULA = FormulaBlock(id="s1-i3", name="Factorial", latex="n! = n \\cdot (n-1)!",
                       spoken="n times the factorial of n minus one.", source_id=DOC)
CHECK = CheckBlock(
    id="s1-i4", question="What does factorial(3) return?",
    options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="6"),
             CheckOption(id="c", text="9")],
    correct_id="b", explain_correct="3 times 2 times 1.", explain_incorrect="Trace the calls.",
    concept="Recursion",
)


def run(coro):
    return asyncio.run(coro)


def _content() -> GuideContent:
    prose = ProseItem(id="s1-i1", paragraphs=[Paragraph(text="A function that calls itself.")],
                      summary="It calls itself.")
    other = Section(id="s2", title="Control flow", concept="Control Flow", tier="learning",
                    weight=40, one_line="What runs next.", status="written",
                    items=[ProseItem(id="s2-i1", paragraphs=[Paragraph(text="Conditions.")])])
    section = Section(id="s1", title="Recursion", concept="Recursion", tier="struggling", weight=60,
                      one_line="A function calls itself.", status="written",
                      items=[prose, KEY_TERMS, FORMULA, CHECK])
    return GuideContent(title="Recursion", deck="Two sections.", sections=[section, other],
                        scope_label="Midterm 1",
                        sources=[Source(id=DOC, name="recursion.pdf", kind="PDF")])


def _guide(world: World, **over) -> GuideContent:  # noqa: F811
    content = _content()
    fields = dict(
        status="ready", generated_at=MADE_AT, content=encrypt_json(content.model_dump(mode="json")),
        read_sections=["s1"], answers=encrypt_json({"s1-i4": {"option_id": "b", "correct": True}}),
    )
    world.guide(**{**fields, **over})
    return content


class Rewriter:
    """Stands in for `writer.arewrite_block`: answers with a block (or None,
    or an exception) and records what it was asked."""

    def __init__(self, monkeypatch, reply):
        self.reply = reply
        self.calls: list[dict] = []
        monkeypatch.setattr(writer, "arewrite_block", self.arewrite_block)

    async def arewrite_block(self, brief, content, section, **kwargs):
        self.calls.append({"brief": brief, "content": content, "section": section, **kwargs})
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def _regenerate(block_id: str, user_id: str = ME):
    return run(blocks.aregenerate_block(user_id, GUIDE, block_id))


def _charges(user_id: str = ME) -> int:
    return len(request_limits._rate_state.get(f"study-guide-block:{user_id}", []))


# ── Through the function-mode seam ────────────────────────────────────────────


def test_a_block_is_rewritten_in_place_and_nothing_else_moves(world, function_mode):  # noqa: F811
    before = _guide(world)
    row_before = dict(world.stored())

    block = _regenerate("s1-i2")

    # The E2E handler's rewritten key terms, under the old block's id.
    assert (block.id, block.type, block.title) == ("s1-i2", "key_terms", "Key terms, rewritten")
    assert [term.term for term in block.terms] == ["Base case", "Stack overflow"]
    after, row = world.content(), world.stored()
    assert after.sections[0].items == [before.sections[0].items[0], block, FORMULA, CHECK]
    assert after.sections[1] == before.sections[1]
    assert after.model_copy(update={"sections": []}) == before.model_copy(update={"sections": []})
    for column in ("status", "generated_at", "read_sections", "answers", "material_ids",
                   "previous_content", "saved_at"):
        assert row[column] == row_before[column]
    assert row["generating_at"] is None


def test_a_regenerated_block_is_logged_by_type_only(world, function_mode):  # noqa: F811
    _guide(world)

    _regenerate("s1-i2")

    (event,) = world.logged
    assert (event["name"], event["category"], event["user_id"]) == (
        "study_guide.block_regenerated", "usage", ME)
    assert event["payload"] == {"guide_id": GUIDE, "block_type": "key_terms"}


def test_every_other_block_of_the_e2e_section_comes_back_as_its_own_type(world, function_mode):  # noqa: F811
    before = _guide(world)

    block = _regenerate("s1-i3")

    assert (block.id, block.type, block.name) == ("s1-i3", "formula", "Factorial, defined recursively, rewritten")
    assert block.source_id == DOC
    assert world.content().sections[0].items == [
        before.sections[0].items[0], KEY_TERMS, block, CHECK]


def test_a_reply_of_another_type_changes_nothing(world, function_mode):  # noqa: F811
    """The handler has no chart to answer with, so asking it for one comes
    back as key terms: the wrong type."""
    content = _content()
    chart = ChartBlock(
        id="s1-i3", title="Calls", x_label="n", y_label="Calls", alt="A rising line.",
        series=[ChartSeries(label="Calls", points=[ChartPoint(x=1, y=1), ChartPoint(x=3, y=3)])],
    )
    content.sections[0].items[2] = chart
    _guide(world, content=encrypt_json(content.model_dump(mode="json")))

    with pytest.raises(GuideGenerationFailed) as failed:
        _regenerate("s1-i3")

    assert failed.value.status_code == 502
    assert world.content() == content
    assert world.stored()["generating_at"] is None and world.logged == []


# ── What the rewriter is asked ────────────────────────────────────────────────


def test_the_rewriter_gets_the_block_as_written_and_the_students_reason(world, monkeypatch):  # noqa: F811
    before = _guide(world)
    rewriter = Rewriter(monkeypatch, FORMULA.model_copy(update={"name": "Factorial, again"}))

    block = _regenerate("s1-i3")

    (call,) = rewriter.calls
    assert block.name == "Factorial, again"
    assert (call["block_id"], call["block_type"], call["why"]) == (
        "s1-i3", "formula", prompts.REWRITE_ASKED)
    assert call["section"] == before.sections[0] and call["content"] == before
    written = json.loads(call["block_text"])
    assert written["source"] == "S1" and "id" not in written and "source_id" not in written
    assert [s.source.id for s in call["brief"].sources] == [DOC]
    assert call["deps"].user_id == ME


# ── The check ─────────────────────────────────────────────────────────────────


def test_a_rewritten_block_passes_the_same_check_as_a_generated_one(world, monkeypatch):  # noqa: F811
    _guide(world)
    world.documents["doc-1"] = ("recursion.pdf", "factorial(3) is 6 and factorial(4) is 24.", [])
    chart = ChartBlock(
        id="s1-i3", title="Growth [S1]", x_label="n", y_label="n!", alt="A rising line.",
        series=[ChartSeries(label="Factorial", points=[ChartPoint(x=3, y=6), ChartPoint(x=4, y=24)])],
        source_id=DOC,
    )
    # A formula block cannot become a chart through the writer; the check is
    # what is under test here, so the stand-in returns one directly.
    Rewriter(monkeypatch, chart)

    block = _regenerate("s1-i3")

    assert block.illustrative is False
    assert block.title == "Growth"
    assert world.content().sections[0].items[2] == block


def test_a_rewrite_that_fails_the_check_changes_nothing(world, monkeypatch):  # noqa: F811
    before = _guide(world)
    Rewriter(monkeypatch, ConceptMapBlock(id="s1-i2", title="Builds on", nodes=[
        ConceptMapNode(concept="Game Theory", step="Aside"),
        ConceptMapNode(concept="Recursion", step="Here"),
    ]))

    with pytest.raises(GuideGenerationFailed):
        _regenerate("s1-i2")

    assert world.content() == before and world.stored()["generating_at"] is None


def test_no_valid_rewrite_is_generation_failed(world, monkeypatch):  # noqa: F811
    before = _guide(world)
    Rewriter(monkeypatch, None)

    with pytest.raises(GuideGenerationFailed) as failed:
        _regenerate("s1-i2")

    assert failed.value.detail == blocks.NOT_REWRITTEN_DETAIL
    assert world.content() == before and world.stored()["generating_at"] is None


def test_a_budget_refusal_is_raised_as_itself_and_the_claim_is_released(world, monkeypatch):  # noqa: F811
    _guide(world)
    refusal = LLMBudgetExceeded(limit=10, used=11,
                                reset_at=datetime.now(timezone.utc) + timedelta(hours=3))
    Rewriter(monkeypatch, refusal)

    with pytest.raises(LLMBudgetExceeded) as raised:
        _regenerate("s1-i2")

    assert raised.value is refusal
    assert world.stored()["generating_at"] is None


# ── What cannot be regenerated ────────────────────────────────────────────────


def test_what_is_not_a_block_of_the_users_guide_is_not_found(world, monkeypatch):  # noqa: F811
    _guide(world)
    world.db.add("theirs", user_id="user_other")
    rewriter = Rewriter(monkeypatch, KEY_TERMS)

    for block_id in ("s1-i9", "s9-i1", "s1-i1", "s1", ""):
        with pytest.raises(GuideNotFound):
            _regenerate(block_id)
    with pytest.raises(GuideNotFound):
        run(blocks.aregenerate_block(ME, "theirs", "s1-i2"))
    with pytest.raises(GuideNotFound):
        _regenerate("s1-i2", user_id="user_other")

    assert rewriter.calls == [] and _charges() == 0


def test_a_check_question_cannot_be_regenerated(world, monkeypatch):  # noqa: F811
    before = _guide(world)
    rewriter = Rewriter(monkeypatch, CHECK)

    with pytest.raises(GuideInvalid) as invalid:
        _regenerate("s1-i4")

    assert invalid.value.detail == "A check question cannot be regenerated."
    assert rewriter.calls == [] and _charges() == 0
    assert world.content() == before


def test_an_unreadable_guide_is_refused(world, monkeypatch):  # noqa: F811
    _guide(world, content="bm90LWNpcGhlcnRleHQtbm90LWNpcGhlcnRleHQ=")
    rewriter = Rewriter(monkeypatch, KEY_TERMS)

    with pytest.raises(GuideInvalid, match="cannot be read"):
        _regenerate("s1-i2")

    assert rewriter.calls == [] and _charges() == 0


# ── The claim and the limit ───────────────────────────────────────────────────


def test_a_guide_that_is_being_written_is_busy(world, monkeypatch):  # noqa: F811
    held = datetime.now(timezone.utc).isoformat()
    before = _guide(world, generating_at=held)
    rewriter = Rewriter(monkeypatch, KEY_TERMS)

    with pytest.raises(GuideBusy) as busy:
        _regenerate("s1-i2")

    assert busy.value.status_code == 409
    assert rewriter.calls == []
    # The generation's claim is untouched, and the refused request is not
    # counted against the hourly limit.
    assert world.stored()["generating_at"] == held and _charges() == 0
    assert world.content() == before


def test_the_guide_is_claimed_while_the_block_is_rewritten(world, monkeypatch):  # noqa: F811
    _guide(world)
    seen: list[str | None] = []
    rewriter = Rewriter(monkeypatch, KEY_TERMS.model_copy(update={"title": "Again"}))
    asked = rewriter.arewrite_block

    async def while_claimed(brief, content, section, **kwargs):
        seen.append(world.stored()["generating_at"])
        return await asked(brief, content, section, **kwargs)

    monkeypatch.setattr(writer, "arewrite_block", while_claimed)

    _regenerate("s1-i2")

    assert seen and seen[0] is not None
    assert world.stored()["generating_at"] is None


def test_a_rewrite_that_loses_the_claim_writes_nothing(world, monkeypatch):  # noqa: F811
    before = _guide(world)
    taken_over = "2026-11-12T12:00:00+00:00"
    rewriter = Rewriter(monkeypatch, KEY_TERMS.model_copy(update={"title": "Again"}))
    asked = rewriter.arewrite_block

    async def overtaken(brief, content, section, **kwargs):
        world.stored()["generating_at"] = taken_over
        return await asked(brief, content, section, **kwargs)

    monkeypatch.setattr(writer, "arewrite_block", overtaken)

    with pytest.raises(GuideBusy):
        _regenerate("s1-i2")

    assert world.content() == before
    assert world.stored()["generating_at"] == taken_over


def test_the_hourly_limit_is_its_own(world, monkeypatch):  # noqa: F811
    assert limits.STUDY_GUIDE_BLOCK_LIMIT == 40
    _guide(world)
    Rewriter(monkeypatch, KEY_TERMS.model_copy(update={"title": "Again"}))
    monkeypatch.setattr(limits, "STUDY_GUIDE_BLOCK_LIMIT", 2)

    _regenerate("s1-i2")
    _regenerate("s1-i2")
    with pytest.raises(GuideRateLimited) as limited:
        _regenerate("s1-i2")

    assert limited.value.status_code == 429
    # Block rewrites do not spend the generation limit.
    assert f"study-guide-generate:{ME}" not in request_limits._rate_state
