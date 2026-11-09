"""The quiz with every quiz learning flag off is the quiz of 50e9ded8.

Learning-loop spec §13 A143-A147 put the quiz's learner-model concept plan,
its planned questions, its item gates, its misconception record and resolve,
and its results block behind five per-student flags (`quiz_concept_plan`,
`quiz_planned_questions`, `quiz_item_gates`, `quiz_misconceptions`,
`quiz_results_routing`). Off, every quiz generation
request, served question, recorded response, evidence row and stored row is
byte-identical to 50e9ded8, so the recorded `quiz_generation` eval cassettes
still replay.

Pinned here two ways:
- the generation request: the quiz agent run in function mode on fixed
  inputs, its system prompt, user message, function tools, output tool and
  schema captured and hashed (`_capture_request`);
- the route flow: /generate, /attempts/{id}/answer and /submit run end to end
  on the E2E function-mode quiz handler against in-memory tables, and every
  row the route writes, every evidence dict it hands the single writer and
  every response body hashed (`_flow`).

The hashes were computed at 50e9ded8 by this file's own helpers. Change one
only together with a recorded eval and a §13 row that says why.

Re-verified after the merge with main (spec §13 A148): at the main sync's tip
before the quiz merge (4b09d765, main's quiz changes included) every digest
here is unchanged, so "flags off" there and here is still 50e9ded8's. The one
harness change: main's route claims its rate limit through the async twin
(`aclaim_rate_limit`, #117), so that is what the flow patches. Main's #849
passes `defer=background_tasks.add_task` to the graph write; the fake
accepts it and records nothing new, and every digest is still unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

QUIZ_FLAGS = (
    "quiz_concept_plan",
    "quiz_planned_questions",
    "quiz_item_gates",
    "quiz_misconceptions",
    "quiz_results_routing",
)

# ── the generation request ──────────────────────────────────────────────────

#: The fixed course material every captured request is grounded on.
_MATERIAL_BLOCK = "COURSE CATALOG (official BU course data):\n\nCS 111: recursion and loops."

#: (name, _quiz_via_agent keyword arguments, material?, recent?, exam_days)
REQUEST_VARIANTS = {
    "adaptive_mc_grounded": (
        dict(difficulty="adaptive", question_format="multiple_choice", use_shared_context=True),
        True,
        True,
        5,
    ),
    "easy_mc_plain": (
        dict(difficulty="easy", question_format="multiple_choice", use_shared_context=False),
        False,
        False,
        None,
    ),
    "hard_mixed_grounded": (
        dict(difficulty="hard", question_format="mixed", use_shared_context=False),
        True,
        False,
        None,
    ),
    "medium_short_answer": (
        dict(difficulty="medium", question_format="short_answer", use_shared_context=True),
        False,
        True,
        12,
    ),
}


def _sha(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _context_patches(stack: ExitStack, *, material: bool, recent: bool, exam_days):
    """Fix every context read `_quiz_via_agent` gathers, so the request is a
    pure function of the variant."""
    from routes import quiz as rq
    from services.quiz_repetition import RecentQuestion
    from services.quiz_signals import QuizSignals

    course = rq.CourseRow(code="CS111", name="Intro to CS")
    mat = (
        rq.CourseMaterial(block=_MATERIAL_BLOCK, chunk_ids=("chunk-1",), k_chunks=1, has_catalog=True)
        if material
        else rq.CourseMaterial()
    )
    stack.enter_context(patch("routes.quiz._course_row", return_value=course))
    stack.enter_context(patch("routes.quiz.course_offering_ids", return_value=["off-1"]))
    stack.enter_context(patch("routes.quiz._course_material", return_value=mat))
    stack.enter_context(
        patch(
            "routes.quiz.recent_question_identities",
            return_value=[RecentQuestion("h1", "What is a base case?")] if recent else [],
        )
    )
    stack.enter_context(patch("routes.quiz.days_until_next_exam", return_value=exam_days))
    stack.enter_context(
        patch(
            "routes.quiz.gather_signals",
            return_value=QuizSignals(times_studied=3, velocity_per_day=0.02),
        )
    )
    stack.enter_context(patch("routes.quiz._log_rag_uncovered"))


def _capture_request(monkeypatch, variant: str) -> dict:
    """Run the real quiz agent in function mode through `_quiz_via_agent` and
    capture what it sends the model."""
    import asyncio

    from agents._providers import clear_function_handlers, model_for, register_function_handler
    from agents.quiz import quiz_agent
    from routes import quiz as rq

    kwargs, material, recent, exam_days = REQUEST_VARIANTS[variant]
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    seen: dict = {}

    class _Captured(Exception):
        pass

    def handler(messages, info):
        parts = [p for m in messages for p in getattr(m, "parts", [])]
        out = info.output_tools[0]
        seen.update(
            system=[p.content for p in parts if p.part_kind == "system-prompt"],
            user=[p.content for p in parts if p.part_kind == "user-prompt"],
            instructions=info.instructions,
            tools=sorted(
                (t.name, t.description, json.dumps(t.parameters_json_schema, sort_keys=True))
                for t in info.function_tools
            ),
            output=(out.name, out.description),
            schema=out.parameters_json_schema,
        )
        raise _Captured

    clear_function_handlers()
    register_function_handler("quiz", handler)
    try:
        with ExitStack() as stack:
            _context_patches(stack, material=material, recent=recent, exam_days=exam_days)
            stack.enter_context(quiz_agent.override(model=model_for("quiz")))
            with pytest.raises(_Captured):
                asyncio.run(
                    rq._quiz_via_agent(
                        user_id="user_andres",
                        course_id="course1",
                        concept_node_id="node1",
                        concept_name="Recursion",
                        num_questions=3,
                        request_id="req-1",
                        times_studied=3,
                        has_graph=True,
                        **kwargs,
                    )
                )
    finally:
        clear_function_handlers()
    return seen


#: Captured at 50e9ded8: sha256 of json.dumps(system parts) / of the user parts
#: / of the sorted function tools / of the output tool's schema (sort_keys).
PRE_QUIZ_LEARNING_REQUESTS = {
    "adaptive_mc_grounded": {
        "schema": "bd904b2453ac0ae827901ac8ce3ab7f18f16df8c1cdefa6e3b6c8eb12ce12035",
        "system": "5c8336ecb938886d74503cb90e53bfaf250214ab4b0aab5f2d7e91d6d7eb4e40",
        "tools": "4fc284cee330971fbb51cc66515c2dd2d7b4918344505da1e86d9e622b8de293",
        "user": "2a5eccf15e95ebc676976aeb7ae92f07666f2caa08323bcad7507568526f1eb5",
    },
    "easy_mc_plain": {
        "schema": "bd904b2453ac0ae827901ac8ce3ab7f18f16df8c1cdefa6e3b6c8eb12ce12035",
        "system": "5c8336ecb938886d74503cb90e53bfaf250214ab4b0aab5f2d7e91d6d7eb4e40",
        "tools": "4fc284cee330971fbb51cc66515c2dd2d7b4918344505da1e86d9e622b8de293",
        "user": "6aff0ade36748df53fe30ad0bf8cf48fe9effa24dcbd1dedcce47ad347dc45c0",
    },
    "hard_mixed_grounded": {
        "schema": "bd904b2453ac0ae827901ac8ce3ab7f18f16df8c1cdefa6e3b6c8eb12ce12035",
        "system": "5c8336ecb938886d74503cb90e53bfaf250214ab4b0aab5f2d7e91d6d7eb4e40",
        "tools": "4fc284cee330971fbb51cc66515c2dd2d7b4918344505da1e86d9e622b8de293",
        "user": "29c91f082cd026cf1bb36152f812b9008b34c26ba27c698fb2cf39f585fcabd7",
    },
    "medium_short_answer": {
        "schema": "bd904b2453ac0ae827901ac8ce3ab7f18f16df8c1cdefa6e3b6c8eb12ce12035",
        "system": "5c8336ecb938886d74503cb90e53bfaf250214ab4b0aab5f2d7e91d6d7eb4e40",
        "tools": "4fc284cee330971fbb51cc66515c2dd2d7b4918344505da1e86d9e622b8de293",
        "user": "dd1fb0015246de5b5fe5871410714e086b3551b9c10f61da825e96013ce2126b",
    },
}
PRE_QUIZ_LEARNING_PROMPT_VERSION = "9063bad6e844"
_OUTPUT_TOOL = ("final_result", "The agent's structured output.")


def _request_digest(seen: dict) -> dict:
    return {
        "system": _sha(seen["system"]),
        "user": _sha(seen["user"]),
        "tools": _sha(seen["tools"]),
        "schema": _sha(seen["schema"]),
    }


# ── the route flow ──────────────────────────────────────────────────────────

_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _normal(value):
    """Timestamps and uuids out (the claim stamp, now() and the attempt id
    differ run to run)."""
    if isinstance(value, dict):
        return {k: _normal(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normal(v) for v in value]
    if isinstance(value, str):
        return _UUID.sub("<uuid>", _TS.sub("<ts>", value))
    return value


class _Tables:
    """Every table the quiz route opens, in memory, recording each write."""

    def __init__(self, written: list):
        self.written = written
        self.attempt: dict | None = None
        self.responses: list[dict] = []
        self.claims: set[str] = set()

    def __call__(self, name):
        mock = MagicMock()
        written = self.written

        if name == "graph_nodes":
            mock.select.return_value = [
                {
                    "id": "node1",
                    "user_id": "user_andres",
                    "course_id": "course1",
                    "concept_name": "Recursion",
                    "mastery_score": 0.35,
                    "times_studied": 2,
                }
            ]
        elif name == "quiz_attempts":

            def insert(row, **_):
                written.append(("insert", name, row))
                self.attempt = {**row, "completed_at": None, "abandoned_at": None, "created_at": "2026-11-08T10:00:00+00:00"}
                return [row]

            def update(values, filters=None, **_):
                written.append(("update", name, values, filters))
                if self.attempt is not None:
                    self.attempt.update(values)
                return [{"id": "quiz-fixed", **values}]

            mock.insert.side_effect = insert
            mock.update.side_effect = update
            mock.select.side_effect = lambda *a, **k: [dict(self.attempt)] if self.attempt else []
        elif name == "quiz_responses":

            def insert(row, **_):
                written.append(("insert", name, row))
                self.responses.append(dict(row))
                return [row]

            def select(cols="*", filters=None, **_):
                index = (filters or {}).get("question_index")
                rows = self.responses
                if index:
                    rows = [r for r in rows if f"eq.{r['question_index']}" == index]
                return [dict(r) for r in rows]

            mock.insert.side_effect = insert
            mock.select.side_effect = select
        elif name == "quiz_evidence_claims":

            def claim(rows, on_conflict=None):
                fresh = [r for r in rows if r["question_hash"] not in self.claims]
                self.claims |= {r["question_hash"] for r in fresh}
                written.append(("claim", name, sorted(r["question_hash"] for r in fresh)))
                return fresh

            mock.insert_ignore_duplicates.side_effect = claim
            mock.update.return_value = []
        else:
            mock.select.return_value = []
            mock.insert.return_value = []
            mock.update.return_value = []
        return mock


def _flow(monkeypatch, *, question_format: str, difficulty: str = "adaptive") -> dict:
    """/generate → /answer (each question, the first answered "Sure") → /submit
    on the E2E quiz handler, every write and response recorded."""
    from agents._providers import clear_function_handlers, model_for, register_function_handler
    from agents.function_handlers_e2e import _quiz_check_handler, _quiz_handler
    from agents.quiz import quiz_agent
    from agents.quiz_planned import quiz_planned_agent

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    written: list = []
    tables = _Tables(written)
    evidence_calls: list = []

    # #849: the route hands the class-aggregate refresh to `defer`; the fake
    # writes nothing there, so no digest below moves.
    def apply(user_id, update, course_id=None, *, defer=None):
        evidence_calls.append({"user_id": user_id, "update": update, "course_id": course_id})
        return [
            {"node_id": e["node_id"], "before": 0.35, "after": 0.4 + 0.01 * i}
            for i, e in enumerate(update.get("evidence") or [])
        ]

    clear_function_handlers()
    register_function_handler("quiz", _quiz_handler)
    register_function_handler("quiz_check", _quiz_check_handler)
    try:
        with ExitStack() as stack:
            _context_patches(stack, material=True, recent=False, exam_days=None)
            stack.enter_context(quiz_agent.override(model=model_for("quiz")))
            stack.enter_context(quiz_planned_agent.override(model=model_for("quiz")))
            stack.enter_context(patch("routes.quiz.table", side_effect=tables))
            stack.enter_context(patch("routes.quiz.encrypt_json", side_effect=lambda v: {"enc": v}))
            stack.enter_context(
                patch("routes.quiz.decrypt_json_column", side_effect=lambda v: v.get("enc") if isinstance(v, dict) and "enc" in v else v)
            )
            # main (#117): the route claims through the async limiter twin
            stack.enter_context(patch("routes.quiz.aclaim_rate_limit", new=AsyncMock(return_value=(None, 1.0))))
            stack.enter_context(patch("routes.quiz._daily_spend_exceeded", return_value=False))
            stack.enter_context(patch("routes.quiz.apply_graph_update", side_effect=apply))
            stack.enter_context(patch("routes.quiz.max_help_many", return_value={}))
            stack.enter_context(patch("routes.quiz.get_quiz_context", return_value={}))
            stack.enter_context(patch("routes.quiz.save_quiz_context"))
            stack.enter_context(
                patch(
                    "routes.quiz.quiz_context_agent.run",
                    new=AsyncMock(return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))),
                )
            )
            stack.enter_context(patch("routes.quiz.get_display_name", return_value="Andres"))
            stack.enter_context(patch("routes.quiz.award_xp_safe", return_value=None))
            stack.enter_context(patch("routes.quiz.me_snapshot", return_value={"total_xp": 10}))
            events = stack.enter_context(patch("routes.quiz.events_service.log_event"))

            generated = client.post(
                "/api/quiz/generate",
                json={
                    "user_id": "user_andres",
                    "concept_node_id": "node1",
                    "num_questions": 3,
                    "difficulty": difficulty,
                    "question_format": question_format,
                    "use_shared_context": False,
                },
            )
            assert generated.status_code == 200, generated.text
            quiz_id = generated.json()["quiz_id"]
            answers = []
            stored = tables.attempt["questions_json"]["enc"]
            for i, question in enumerate(stored):
                body = {"question_index": i, "question_id": question["id"], "time_ms": 1000}
                if i == 0:
                    body["confidence"] = "sure"
                if question.get("type") in ("short_answer", "numeric", "symbolic"):
                    body["answer_text"] = question["correct_answer"] if i % 2 == 0 else "wrong"
                else:
                    body["selected_index"] = 1 if i % 2 == 0 else 0
                answers.append(client.post(f"/api/quiz/attempts/{quiz_id}/answer", json=body))
            submitted = client.post("/api/quiz/submit", json={"quiz_id": quiz_id, "answers": []})
            assert submitted.status_code == 200, submitted.text
    finally:
        clear_function_handlers()
    return _normal(
        {
            "generate": generated.json(),
            "answers": [a.json() for a in answers],
            "submit": submitted.json(),
            "written": written,
            "evidence": evidence_calls,
            "events": [
                [c.args[0], c.kwargs.get("category"), c.kwargs.get("payload")]
                for c in events.call_args_list
                if c.args
            ],
        }
    )


#: Captured at 50e9ded8: sha256 of json.dumps(_flow(...)) per part (sort_keys).
PRE_QUIZ_LEARNING_FLOWS = {
    "multiple_choice": {
        "answers": "426a221e51f916cbc547362097895b0d113bda4892c8f1bbbf8dff06d17a4103",
        "events": "e31979b6e523e1b27d92b55a25e950fdd66cc19b05c637af13e9f126aaa33601",
        "evidence": "4987621eb470f0100c53e3ef45410c23ab76c0b61d0873f61686262dc13c99b2",
        "generate": "f23f85b95a4272e3f11f9c83ba801c24e325c4fcf7735cde3f49a024bf724ca3",
        "submit": "066ea06ded4f555715975fb082bea236b3ef18c5a47e50ab1c2dc6fa194a7277",
        "written": "06e978f69a2b050c8e1044e0f44aa64697a705e9adbf4efeae589d9509e19d34",
    },
    "short_answer": {
        "answers": "b3f730d39498e86edad172f99e28027046c8464feb23d2c2250611976184ae0d",
        "events": "0e3fec38d28b25c38020bb790d03e4d7d40f867fed8fd6536783fdcf42ff9b4c",
        "evidence": "d8eff42c09f8d84957e2776f4171e7f30917602b05257a89387b0d86ebfe44d2",
        "generate": "a15cfc7761c15c5378057eb8c2cf4fdce965c6386c9fd7de8be1ad3fef072fa8",
        "submit": "0ea1f5cfa8a5e2e6d9497412629bf2c48fbae66a25e2f67eaa1a8bc5294c6d85",
        "written": "0bf04da6d08a44621a3329811aafa89ee1be1a371da3933f9f760ebc578a30b1",
    },
}


def _flow_digest(flow: dict) -> dict:
    return {part: _sha(flow[part]) for part in ("generate", "answers", "submit", "written", "evidence", "events")}


@pytest.fixture
def flags_off(monkeypatch):
    """Every quiz learning flag resolves off (the env override, the resolver's
    first step), so the test does not depend on the flag store."""
    for key in QUIZ_FLAGS:
        monkeypatch.setenv(f"SAPLING_FLAG_{key.upper()}", "off")


@pytest.mark.parametrize("variant", sorted(REQUEST_VARIANTS))
def test_flag_off_generation_requests_are_byte_identical_to_50e9ded8(monkeypatch, flags_off, variant):
    seen = _capture_request(monkeypatch, variant)
    assert seen["instructions"] is None
    assert seen["output"] == _OUTPUT_TOOL
    assert _request_digest(seen) == PRE_QUIZ_LEARNING_REQUESTS[variant]


def test_flag_off_quiz_prompt_version_is_50e9ded8s():
    from agents.quiz import PROMPT_VERSION

    assert PROMPT_VERSION == PRE_QUIZ_LEARNING_PROMPT_VERSION


@pytest.mark.parametrize("question_format", sorted(PRE_QUIZ_LEARNING_FLOWS))
def test_flag_off_route_flow_is_byte_identical_to_50e9ded8(monkeypatch, flags_off, question_format):
    flow = _flow(monkeypatch, question_format=question_format)
    assert _flow_digest(flow) == PRE_QUIZ_LEARNING_FLOWS[question_format]
