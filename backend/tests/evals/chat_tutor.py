"""pydantic-evals cases for chat_tutor_agent (Socratic / Expository / TeachBack).

Run via tests.evals._replay (record/replay/live):
    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/chat_tutor.py
    SAPLING_EVAL_MODE=replay python tests/evals/chat_tutor.py

Each case input is a (mode, user_message) tuple. The adapter dispatches to
the right mode-specific agent via `agent_for_mode(mode)`. Cassette key is
the case name (NOT the input), so cassettes capture per-mode behavior even
when two modes happen to share the same user message.

Why ChatReply wraps the str output: the shared `run_with_cassette` helper
calls `output_model.model_validate(body)` on replayed JSON. `str` has no
such method, so we either (a) wrap the agent's str reply in a tiny
Pydantic model for the eval layer, or (b) bypass the helper. We chose (a)
plus a local adapter so cassettes round-trip cleanly without modifying
any file outside `backend/tests/evals/chat_tutor.py`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# `python tests/evals/chat_tutor.py` from backend/ — import path setup.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))  # for _replay sibling import

from pydantic import BaseModel, Field
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps
from _replay import MODE, cli_main, load_cassette, save_cassette
from _retrieval_fixture import FixtureRetrieval, load_fixture


# Input tuple: (mode, user_message). Output is the agent's string reply
# wrapped in ChatReply so cassettes round-trip via model_validate.
ChatInput = tuple[str, str]


class ToolCall(BaseModel):
    """One function-tool invocation the model made during the run,
    captured at record time so replay-mode evaluators can score tool
    behavior (which tools, with what args) without re-running the model."""

    tool_name: str
    args: dict = Field(default_factory=dict)


class ChatReply(BaseModel):
    """Cassette payload: the reply text plus the tool calls the model made.

    `tool_calls` defaults to [] so legacy cassettes (bare string, or
    {"text": ...} without tool_calls) still hydrate cleanly."""

    text: str
    tool_calls: list[ToolCall] = Field(default_factory=list)


# ── Evaluators ──────────────────────────────────────────────────────────────


@dataclass
class NonEmptyEvaluator(Evaluator[ChatInput, ChatReply]):
    """Reply must be at least 20 chars. Empty/near-empty replies fail."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        text = (ctx.output.text if ctx.output else "") or ""
        return 1.0 if len(text.strip()) >= 20 else 0.0


@dataclass
class SocraticEndsWithQuestionEvaluator(Evaluator[ChatInput, ChatReply]):
    """Socratic mode prompt requires every reply to end with a question."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        mode = ctx.inputs[0]
        if mode != "socratic":
            return 1.0
        reply = (ctx.output.text if ctx.output else "").rstrip()
        return 1.0 if reply.endswith("?") else 0.0


@dataclass
class ExpositoryHasStructureEvaluator(Evaluator[ChatInput, ChatReply]):
    """Expository replies should be substantive (>= 200 chars) AND not
    end with a question (the prompt says don't ask questions back unless
    the user's prompt was ambiguous)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        mode = ctx.inputs[0]
        if mode != "expository":
            return 1.0
        reply = (ctx.output.text if ctx.output else "").strip()
        long_enough = len(reply) >= 200
        not_question_loop = not reply.rstrip().endswith("?")
        return 1.0 if (long_enough and not_question_loop) else 0.0


@dataclass
class TeachBackProbesEvaluator(Evaluator[ChatInput, ChatReply]):
    """TeachBack mode should both validate parts of the student's
    explanation AND end with a probing question. We check the
    end-with-? half here (the validate half is qualitative and judged
    in the live record session)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        mode = ctx.inputs[0]
        if mode != "teachback":
            return 1.0
        reply = (ctx.output.text if ctx.output else "").rstrip()
        return 1.0 if reply.endswith("?") else 0.0


@dataclass
class NoToolMisuseEvaluator(Evaluator[ChatInput, ChatReply]):
    """The agent should NOT mention raw tool names in its reply
    (`read_user_progress`, `apply_graph_update`, etc.). Tools are
    invisible to the student."""

    BANNED_SUBSTRINGS = (
        "read_user_progress",
        "search_course_materials",
        "read_session_history",
        "apply_graph_update_tool",
        "apply_concepts_to_graph",
        "function_tool",
        # #149 graph readers (prompt-facing wire names).
        "read_graph_neighborhood",
        "read_concepts_for_user",
        "update_mastery_tool",
    )

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        reply = (ctx.output.text if ctx.output else "").lower()
        for banned in self.BANNED_SUBSTRINGS:
            if banned.lower() in reply:
                return 0.0
        return 1.0


@dataclass
class NoCourseScopeRefusalEvaluator(Evaluator[ChatInput, ChatReply]):
    """The tutor must never decline a topic on course-scope grounds.

    Regression for the CS132 report: asked about Markov chains, the tutor
    answered "I can only find information about geometric algorithms.
    Markov chains are not in the course description." Course context is
    enrichment, never a limit on what may be taught.
    """

    BANNED_SUBSTRINGS = (
        "not in the course description",
        "not in the course",
        "not part of the course",
        "not covered in the course",
        "outside the course",
        "not in the syllabus",
        "i can only find information about",
        "i can only discuss",
        "i can only help with",
        "i can only assist with",
    )

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        reply = (ctx.output.text if ctx.output else "").lower()
        for banned in self.BANNED_SUBSTRINGS:
            if banned in reply:
                return 0.0
        return 1.0


@dataclass
class OffSyllabusTopicEngagedEvaluator(Evaluator[ChatInput, ChatReply]):
    """Positive counterpart to NoCourseScopeRefusalEvaluator.

    The banned-substring check only catches the BLUNT form of the CS132
    bug ("not in the course description"). It scores 1.0 on the polite
    deflection observed pre-fix on `socratic_history_themes` — "That's a
    fascinating historical question. However, it seems like we're focused
    on topics like Calculus, Computer Science, and Biology in this
    course... would you like to tackle one of the concepts we're
    tracking?" — which redirects to course material without using any
    banned phrase. A substring blocklist can always be walked around by a
    newer model's phrasing; this evaluator instead asserts the reply
    actually engages the topic asked, which is much harder to evade.

    Cases tagged `off_syllabus` must carry `expected_topic_terms` in their
    metadata (a tuple of lowercase strings); the reply must contain at
    least one. Untagged cases pass vacuously (score 1.0)."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        metadata = ctx.metadata or {}
        if not metadata.get("off_syllabus"):
            return 1.0
        terms = metadata.get("expected_topic_terms") or ()
        if not terms:
            # Fail closed: an off_syllabus case with no expected terms is a
            # test-authoring bug, not something that should silently pass.
            return 0.0
        reply = (ctx.output.text if ctx.output else "").lower()
        return 1.0 if any(term.lower() in reply for term in terms) else 0.0


# ── #149 tool-behavior evaluators (scored off cassette tool_calls) ──────────

# The two read-only graph tools' wire names (chat_tutor._build_tools).
GRAPH_READ_TOOLS = ("read_graph_neighborhood", "read_concepts_for_user")

# Mastery-delta band from the tool schema's own guidance
# (agents/tools/graph.py::ConceptMasteryUpdate): +0.1..+0.3 for correct
# answers, −0.05..−0.1 for gaps — so any emitted delta outside
# [-0.1, +0.3] is off-script.
MASTERY_DELTA_MIN = -0.1
MASTERY_DELTA_MAX = 0.3


def _mastery_updates(output: ChatReply | None) -> list[dict]:
    """Flatten every update_mastery_tool call's `updates` entries.
    Tolerates both the typed arg shape {"update": {"updates": [...]}} and
    a flat {"updates": [...]}."""
    entries: list[dict] = []
    for call in (output.tool_calls if output else []) or []:
        if call.tool_name != "update_mastery_tool":
            continue
        args = call.args or {}
        payload = args.get("update") if isinstance(args.get("update"), dict) else args
        for u in (payload or {}).get("updates", []) or []:
            if isinstance(u, dict):
                entries.append(u)
    return entries


@dataclass
class GraphToolUsedEvaluator(Evaluator[ChatInput, ChatReply]):
    """Cases tagged `expects_graph_read` must have called at least one
    graph reader (the tags mirror observed behavior at baseline-record
    time — a prompt change that stops the model reading the graph on
    those cases regresses this score). Untagged cases pass vacuously."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        if not (ctx.metadata or {}).get("expects_graph_read"):
            return 1.0
        used = {t.tool_name for t in (ctx.output.tool_calls if ctx.output else [])}
        return 1.0 if used & set(GRAPH_READ_TOOLS) else 0.0


@dataclass
class MasteryUpdateEmittedEvaluator(Evaluator[ChatInput, ChatReply]):
    """Cases tagged `expects_mastery_update` must emit at least one
    update_mastery_tool call; and EVERY emitted delta (tagged or not)
    must sit inside the band the tool schema instructs
    ([-0.1, +0.3])."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        updates = _mastery_updates(ctx.output)
        if (ctx.metadata or {}).get("expects_mastery_update") and not updates:
            return 0.0
        for u in updates:
            try:
                delta = float(u.get("mastery_delta"))
            except (TypeError, ValueError):
                return 0.0
            if not (MASTERY_DELTA_MIN <= delta <= MASTERY_DELTA_MAX):
                return 0.0
        return 1.0


@dataclass
class GroundedConceptEvaluator(Evaluator[ChatInput, ChatReply]):
    """Cases tagged `grounded` (their topic overlaps the fixture course)
    must name at least one fixture concept in the reply — the tutor is
    supposed to teach against the student's tracked graph, not in a
    vacuum. Untagged cases pass vacuously."""

    def evaluate(self, ctx: EvaluatorContext[ChatInput, ChatReply]) -> float:
        if not (ctx.metadata or {}).get("grounded"):
            return 1.0
        reply = (ctx.output.text if ctx.output else "").lower()
        from _retrieval_fixture import load_fixture

        for concept in load_fixture().get("concepts", []):
            name = (concept.get("concept_name") or "").lower()
            if not name:
                continue
            # Number-tolerant: a tutor saying "a closure" is grounded in
            # the "Closures" concept.
            candidates = {name}
            if name.endswith("s"):
                candidates.add(name[:-1])
            if any(c in reply for c in candidates):
                return 1.0
        return 0.0


# ── Cases (5 per mode = 15 total) ───────────────────────────────────────────

CASES: list[Case[ChatInput, ChatReply]] = [
    # ── SOCRATIC ────────────────────────────────────────────────────────────
    Case(
        name="socratic_intro_calculus",
        inputs=(
            "socratic",
            "I keep getting derivatives mixed up with integrals. Can you help?",
        ),
        metadata={"mode": "socratic", "grounded": True},
    ),
    Case(
        name="socratic_python_recursion",
        inputs=(
            "socratic",
            "I don't get how recursion works in Python.",
        ),
        metadata={"mode": "socratic", "grounded": True},
    ),
    Case(
        name="socratic_chemistry_balancing",
        inputs=(
            "socratic",
            "How do you balance a redox equation?",
        ),
        metadata={"mode": "socratic"},
    ),
    Case(
        name="socratic_history_themes",
        inputs=(
            "socratic",
            "Why did the Roman Empire fall?",
        ),
        # Task 5 report / final-review Finding 2: under the old prompt this
        # case deflected in polite form ("it seems like we're focused on
        # topics like Calculus, Computer Science, and Biology in this
        # course... would you like to tackle one of the concepts we're
        # tracking?") — no banned substring, so NoCourseScopeRefusalEvaluator
        # scored it 1.0 anyway. off_syllabus + expected_topic_terms lets
        # OffSyllabusTopicEngagedEvaluator catch that polite form too.
        metadata={
            "mode": "socratic",
            "off_syllabus": True,
            "expected_topic_terms": ("rome", "roman"),
        },
    ),
    Case(
        name="socratic_open_followup",
        inputs=(
            "socratic",
            "I think I get it now — derivatives are just slope.",
        ),
        metadata={"mode": "socratic", "grounded": True},
    ),
    Case(
        # #149: a graph-shaped question the seed block CANNOT answer — the
        # GRAPH CONTEXT block carries (mastery, tier) but not review
        # recency, so answering honestly requires read_concepts_for_user
        # (whose ConceptMastery rows carry last_reviewed_at) or
        # read_graph_neighborhood (ConceptNode.last_reviewed_at).
        name="socratic_stale_concept_review",
        inputs=(
            "socratic",
            "Which of my tracked concepts have I gone the longest without "
            "reviewing? Check when I last reviewed each one and pick the "
            "rustiest for us to work on.",
        ),
        metadata={"mode": "socratic", "grounded": True, "expects_graph_read": True},
    ),
    Case(
        # Task 5 / CS132 regression: a topic genuinely outside the course
        # catalog. The tutor must teach it anyway — course context is
        # enrichment, never a limit on what may be taught.
        #
        # Lite-tier (gemini-2.5-flash-lite) confirmation, run ad hoc against
        # this exact input during task 5 (not committed as a cassette — see
        # .superpowers/sdd/2026-08-10-tutor-course-scope/task-5-report.md
        # Step 6 for the full method) and preserved here so it survives:
        #
        #   Yes, we can!
        #
        #   To start, what do you already know about Markov chains, or what
        #   makes you curious about them?
        #
        # No tool calls, no course/syllabus mention, engages the topic by
        # name — the fix holds on the weakest tier, not just Pro.
        name="socratic_off_syllabus_markov_chains",
        inputs=(
            "socratic",
            "can we talk about markov chains",
        ),
        metadata={
            "mode": "socratic",
            "off_syllabus": True,
            "expected_topic_terms": ("markov",),
        },
    ),

    # ── EXPOSITORY ──────────────────────────────────────────────────────────
    Case(
        name="expository_explain_big_o",
        inputs=(
            "expository",
            "Explain Big-O notation.",
        ),
        metadata={"mode": "expository", "grounded": True, "expects_mastery_update": True},
    ),
    Case(
        name="expository_explain_photosynthesis",
        inputs=(
            "expository",
            "Explain photosynthesis at the cellular level.",
        ),
        metadata={"mode": "expository", "grounded": True, "expects_mastery_update": True},
    ),
    Case(
        name="expository_explain_dependency_injection",
        inputs=(
            "expository",
            "What is dependency injection?",
        ),
        metadata={"mode": "expository", "expects_mastery_update": True},
    ),
    Case(
        name="expository_explain_supply_demand",
        inputs=(
            "expository",
            "Explain how supply and demand determine price.",
        ),
        metadata={"mode": "expository", "grounded": True, "expects_mastery_update": True},
    ),
    Case(
        name="expository_explain_kantian_ethics",
        inputs=(
            "expository",
            "What is Kantian ethics?",
        ),
        metadata={"mode": "expository", "expects_mastery_update": True},
    ),

    # ── TEACHBACK ──────────────────────────────────────────────────────────
    Case(
        name="teachback_correct_concept",
        inputs=(
            "teachback",
            "Let me explain mitosis: a cell duplicates its DNA, then "
            "splits into two identical daughter cells. Each one has the "
            "same chromosomes as the original.",
        ),
        metadata={"mode": "teachback", "grounded": True, "expects_mastery_update": True},
    ),
    Case(
        name="teachback_partial_correct",
        inputs=(
            "teachback",
            "OK so a closure is a function that has variables. Like, "
            "you can use them inside it.",
        ),
        metadata={"mode": "teachback", "grounded": True, "expects_mastery_update": True},
    ),
    Case(
        name="teachback_misconception",
        inputs=(
            "teachback",
            "Newton's first law says objects in motion stay in motion "
            "unless you push them. Force makes things keep moving.",
        ),
        metadata={"mode": "teachback", "grounded": True, "expects_mastery_update": True},
    ),
    Case(
        name="teachback_advanced",
        inputs=(
            "teachback",
            "The Pumping Lemma proves a language isn't regular by "
            "showing that strings of length p can be split such that "
            "the middle can be repeated and stay in the language.",
        ),
        metadata={"mode": "teachback", "expects_mastery_update": True},
    ),
    Case(
        name="teachback_minimal",
        inputs=(
            "teachback",
            "Recursion is when a function calls itself.",
        ),
        metadata={"mode": "teachback", "grounded": True, "expects_mastery_update": True},
    ),
]

assert len(CASES) == 17, (
    f"Expected 17 cases (5/5/5 + the #149 graph-read case + the Task 5 "
    f"off-syllabus case), got {len(CASES)}"
)

# Per-mode breakdown sanity check (7 / 5 / 5 — #149 and Task 5 both added a
# socratic case).
_MODE_COUNTS: dict[str, int] = {"socratic": 0, "expository": 0, "teachback": 0}
for _c in CASES:
    _MODE_COUNTS[_c.inputs[0]] = _MODE_COUNTS.get(_c.inputs[0], 0) + 1
assert _MODE_COUNTS == {"socratic": 7, "expository": 5, "teachback": 5}, (
    f"Expected 7/5/5 cases per mode, got {_MODE_COUNTS}"
)


# ── Adapter (replay layer) ──────────────────────────────────────────────────

# Lookup: (mode, user_message) -> case_name. The case name keys the
# cassette so two modes can share a user message without colliding.
_INPUT_TO_NAME: dict[ChatInput, str] = {c.inputs: c.name for c in CASES}


def _make_deps() -> SaplingDeps:
    """Eval deps: same ids as `_replay.make_deps`, plus the FixtureRetrieval
    (ADR 0023) so every tool the model calls is served from
    fixtures/tutor_course.json — record/live runs are Supabase-free."""
    return SaplingDeps(
        user_id="eval-user",
        course_id="eval-course",
        supabase=None,
        request_id="eval",
        session_id="eval-session",
        retrieval=FixtureRetrieval(),
    )


def _install_offline_graph_writes() -> None:
    """Record/live only: replace the graph WRITE seam with an in-memory stub.

    The retrieval seam covers the tutor's READS; the write tools
    (apply_graph_update_tool / update_mastery_tool) call
    `services.graph_service.apply_graph_update`, which hits Supabase — and
    an eval box has none, so a turn where the model dutifully updates
    mastery would die with ConnectError. The stub echoes plausible
    before/after deltas (seeded from fixture mastery) so the model's
    second turn sees a sensible tool result; the cassette still captures
    the model's tool_calls, which is what the evaluators score."""
    import agents.tools.graph as _graph_tools

    fixture_mastery = {
        (c.get("concept_name") or "").lower(): float(c.get("mastery") or 0.0)
        for c in load_fixture().get("concepts", [])
    }

    def _offline_apply_graph_update(user_id, graph_update, course_id=None):
        changes = []
        for upd in graph_update.get("updated_nodes", []) or []:
            name = upd.get("concept_name") or ""
            try:
                delta = float(upd.get("mastery_delta", 0.0) or 0.0)
            except (TypeError, ValueError):
                delta = 0.0
            before = fixture_mastery.get(name.lower(), 0.3)
            after = max(0.0, min(1.0, before + delta))
            changes.append({"concept": name, "before": before, "after": after})
        return changes

    _graph_tools.apply_graph_update = _offline_apply_graph_update


if MODE in ("record", "live"):
    _install_offline_graph_writes()


def _extract_tool_calls(result) -> list[ToolCall]:
    """Pull the function-tool calls out of a completed run's message log.

    chat_tutor's output_type is plain str, so every ToolCallPart in the
    transcript is a genuine function-tool call (no output-tool noise)."""
    calls: list[ToolCall] = []
    try:
        messages = result.all_messages()
    except Exception:
        return calls
    for message in messages:
        for part in getattr(message, "parts", []) or []:
            if type(part).__name__ != "ToolCallPart":
                continue
            try:
                args = part.args_as_dict()
            except Exception:
                args = {}
            calls.append(ToolCall(tool_name=part.tool_name, args=args or {}))
    return calls


def _assemble_message(user_message: str) -> str:
    """What the agent actually receives for a case's user message.

    Mirrors `routes.learn._prepare_chat_run`'s #149 assembly: the
    deterministic GRAPH CONTEXT seed block (rendered from the fixture
    course by the SAME serializer production feeds from Supabase) is
    prefixed onto the student question. Evals carry no catalog/RAG blocks
    — the fixture course has no BU catalog entry — so the assembled shape
    is `graph block + [STUDENT QUESTION] + message`.

    SAPLING_EVAL_NO_SEED=1 skips the block — used once to record the
    pre-#149 "before" baseline cassettes for the score-delta comparison."""
    import os

    if os.getenv("SAPLING_EVAL_NO_SEED") == "1":
        return user_message
    from services.graph_context import graph_context_from_rows

    fixture = load_fixture()
    nodes = [
        {
            # Fixture rows have no DB ids; the concept name doubles as the
            # row id for edge resolution (names are unique in the fixture).
            "id": c["concept_name"],
            "concept_name": c["concept_name"],
            "mastery_score": c["mastery"],
            "mastery_tier": c["mastery_tier"],
        }
        for c in fixture.get("concepts", [])
    ]
    edge_rows = [
        {
            "source": e["source"],
            "target": e["target"],
            "relationship_type": e.get("relationship_type", "related"),
        }
        for e in fixture.get("edges", [])
    ]
    block = graph_context_from_rows(nodes, edge_rows, user_message)
    if not block:
        return user_message
    return block + "\n\n[STUDENT QUESTION]\n" + user_message


async def _run(case_input: ChatInput) -> ChatReply:
    """Local adapter that mirrors `_replay.run_with_cassette` but wraps
    the agent's plain-text reply in `ChatReply` so cassettes round-trip
    via Pydantic's `model_validate`. Inlined here (rather than reusing
    the shared helper) because the shared helper assumes the agent's
    output is already a Pydantic model."""

    mode, user_message = case_input
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    dataset = "chat_tutor"

    if MODE == "replay":
        body = load_cassette(dataset, case_name)
        if body is None:
            raise RuntimeError(
                f"No cassette for {dataset}/{case_name}. "
                f"Run with SAPLING_EVAL_MODE=record to capture it."
            )
        # Cassettes recorded as plain strings (legacy) or as the
        # ChatReply dict (new, with or without tool_calls) all
        # round-trip cleanly.
        if isinstance(body, str):
            return ChatReply(text=body)
        return ChatReply.model_validate(body)

    deps = _make_deps()
    agent = agent_for_mode(mode)
    result = await agent.run(_assemble_message(user_message), deps=deps)
    reply_text = result.output if isinstance(result.output, str) else str(result.output)
    output = ChatReply(text=reply_text, tool_calls=_extract_tool_calls(result))

    if MODE == "record":
        save_cassette(dataset, case_name, output)

    return output


def make_dataset() -> Dataset[ChatInput, ChatReply]:
    return Dataset(
        name="chat_tutor",
        cases=CASES,
        evaluators=[
            NonEmptyEvaluator(),
            SocraticEndsWithQuestionEvaluator(),
            ExpositoryHasStructureEvaluator(),
            TeachBackProbesEvaluator(),
            NoToolMisuseEvaluator(),
            NoCourseScopeRefusalEvaluator(),
            OffSyllabusTopicEngagedEvaluator(),
            GraphToolUsedEvaluator(),
            MasteryUpdateEmittedEvaluator(),
            GroundedConceptEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
