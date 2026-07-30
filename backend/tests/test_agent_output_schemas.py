"""Structural pins for every agent's output schema and retry budget (#153).

Codifies docs/attempts/2026-05-03-orchestrator-schema-complexity.md: Gemini's
native structured-output API compiles the output schema into a constrained-
decoding automaton and rejects rich schemas outright ("too many states for
serving") — the request 400s before the model runs. The budget lives in the
agents/__init__.py docstring; this module makes it executable so the next
rich schema fails in CI, not in production against Gemini.

Two layers:

1. Discovery — walk every module in ``backend/agents`` and collect every
   ``pydantic_ai.Agent`` instance, then assert the roster matches the frozen
   expectation. A new agent must be added here consciously, which is what
   keeps the retry-policy sets below honest.
2. Budget — every structured output model must satisfy:
     - at most 8 properties per object;
     - at most one level of object nesting below the root
       (root -> list[Item] is the ceiling);
     - no optional NESTED models (``Sub | None``) — optional scalars are fine;
     - enum/const values are plain strings (flat enums, not patterned
       strings);
     - at most 20 properties across the whole schema.
   ``DocumentProcessingResult`` — the exact schema Gemini rejected on
   2026-05-03 — is kept as the negative control: the checker must flag it.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent

import agents as agents_pkg
from agents.document import DocumentProcessingResult

# ── Budget constants (see agents/__init__.py docstring) ───────────────────

MAX_PROPERTIES_PER_OBJECT = 8
MAX_OBJECT_DEPTH = 2
MAX_TOTAL_PROPERTIES = 20

# Modules that never define agents. `function_handlers_e2e` self-registers
# E2E seam handlers on import — never import it from the hermetic lane.
_SKIP_MODULES = {"function_handlers_e2e"}

# name -> has structured (BaseModel) output. Free-text (str) agents have no
# output validation to retry; the streaming tutor's failure handling belongs
# to chat_stream's rung ladder, never a hidden re-roll.
EXPECTED_STRUCTURED_AGENTS = {
    "classifier_agent",
    "concept_describe_agent",
    "concept_extraction_agent",
    "concept_scan_agent",
    "course_summary_agent",
    "flashcard_agent",
    "note_concepts_agent",
    "note_summary_agent",
    "quiz_agent",
    "quiz_context_agent",
    "social_summary_agent",
    "study_guide_agent",
    "summary_agent",
    "syllabus_extraction_agent",
}
EXPECTED_TEXT_AGENTS = {
    "expository_agent",
    "health_probe_agent",
    "note_chat_agent",
    "ocr_vision_agent",
    "socratic_agent",
    "teachback_agent",
}

OUTPUT_RETRY_BUDGET = 2  # structured agents: 1 initial + 2 validation retries


def _discover_agents() -> dict[str, Agent]:
    """Every Agent instance defined anywhere in the agents package, deduped
    by identity (workers are re-imported by agents/document.py)."""
    found: dict[int, tuple[str, Agent]] = {}
    for info in pkgutil.iter_modules(agents_pkg.__path__):
        if info.name.startswith("_") or info.name in _SKIP_MODULES:
            continue
        module = importlib.import_module(f"agents.{info.name}")
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if isinstance(obj, Agent):
                found.setdefault(id(obj), (attr_name, obj))
    return {name: agent for name, agent in found.values()}


AGENTS = _discover_agents()


def _output_model(agent: Agent) -> type[BaseModel] | None:
    """The agent's declared output model, unwrapping PromptedOutput; None for
    free-text (str) agents."""
    output_type = agent.output_type
    # PromptedOutput wraps the model in `.outputs` (same attribute on 1.89
    # and 1.107).
    output_type = getattr(output_type, "outputs", output_type)
    if isinstance(output_type, type) and issubclass(output_type, BaseModel):
        return output_type
    assert output_type is str, (
        f"unexpected output_type {output_type!r} — extend this test's "
        "classification before shipping a new output shape"
    )
    return None


def _output_retry_budget(agent: Agent) -> int:
    """Version-portable read of the output-validation retry budget:
    `_max_result_retries` on pydantic-ai 1.89, `_max_output_retries` on
    1.107+. Must be an int — a dict here means someone configured
    `retries={"output": ...}`, which 1.89 mis-stores into the retry counter
    and blows up with TypeError at retry time."""
    for attr in ("_max_output_retries", "_max_result_retries"):
        value = getattr(agent, attr, None)
        if value is not None:
            assert isinstance(value, int), (
                f"{attr} is {value!r} — dict-form retries break pydantic-ai "
                "1.89; use output_retries=<int> (or retries=<int> on "
                "tool-less agents)"
            )
            return value
    raise AssertionError(
        "could not read the output-retry budget off this pydantic-ai "
        "version; update _output_retry_budget"
    )


# ── Schema walker ─────────────────────────────────────────────────────────


def _resolve(node: dict, defs: dict) -> dict:
    while "$ref" in node:
        name = node["$ref"].split("/")[-1]
        node = defs[name]
    return node


def schema_violations(model: type[BaseModel]) -> list[str]:
    """All budget violations for a model's JSON schema (empty = conforms)."""
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    violations: list[str] = []
    total_properties = 0

    def walk(node: dict, depth: int, path: str, optional_ctx: bool) -> None:
        nonlocal total_properties
        node = _resolve(node, defs)

        for key in ("anyOf", "oneOf", "allOf"):
            if key in node:
                branches = [_resolve(b, defs) for b in node[key]]
                has_null = any(b.get("type") == "null" for b in branches)
                for branch in branches:
                    if branch.get("type") == "null":
                        continue
                    walk(branch, depth, path, optional_ctx or has_null)
                return

        if "enum" in node or "const" in node:
            values = node.get("enum", [node.get("const")])
            if not all(isinstance(v, str) for v in values):
                violations.append(f"{path}: non-string enum values {values!r}")

        node_type = node.get("type")
        if node_type == "array":
            walk(node.get("items", {}), depth, f"{path}[]", optional_ctx)
            return
        if node_type != "object" and "properties" not in node:
            return

        # An object below an Optional union is the "nested optional model"
        # shape that helped kill the orchestrator schema.
        if optional_ctx and depth >= 1:
            violations.append(
                f"{path}: optional nested model (Sub | None) — run a second "
                "agent or compose in route code instead"
            )
        object_depth = depth + 1
        if object_depth > MAX_OBJECT_DEPTH:
            violations.append(
                f"{path}: object nesting depth {object_depth} exceeds "
                f"{MAX_OBJECT_DEPTH} (root -> list[Item] is the ceiling)"
            )
        properties = node.get("properties", {})
        if len(properties) > MAX_PROPERTIES_PER_OBJECT:
            violations.append(
                f"{path}: {len(properties)} properties exceeds "
                f"{MAX_PROPERTIES_PER_OBJECT} per object"
            )
        total_properties += len(properties)
        for name, sub in properties.items():
            walk(sub, object_depth, f"{path}.{name}", False)

    walk(schema, 0, model.__name__, False)
    if total_properties > MAX_TOTAL_PROPERTIES:
        violations.append(
            f"{model.__name__}: {total_properties} total properties exceeds "
            f"{MAX_TOTAL_PROPERTIES}"
        )
    return violations


# ── Roster ────────────────────────────────────────────────────────────────


def test_agent_roster_is_frozen():
    """Every Agent in backend/agents is classified here. A new agent must be
    added to exactly one of the expected sets — that's the moment to decide
    its output shape (budget above) and retry policy (#153)."""
    assert set(AGENTS) == EXPECTED_STRUCTURED_AGENTS | EXPECTED_TEXT_AGENTS


def test_roster_classification_matches_output_types():
    for name in EXPECTED_STRUCTURED_AGENTS:
        assert _output_model(AGENTS[name]) is not None, f"{name} is not structured"
    for name in EXPECTED_TEXT_AGENTS:
        assert _output_model(AGENTS[name]) is None, f"{name} is not free-text"


# ── Budget ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(EXPECTED_STRUCTURED_AGENTS))
def test_output_schema_within_budget(name):
    model = _output_model(AGENTS[name])
    violations = schema_violations(model)
    assert violations == [], (
        f"{name} output schema exceeds the structured-output budget "
        f"(agents/__init__.py):\n- " + "\n- ".join(violations)
    )


def test_negative_control_rich_schema_is_rejected():
    """DocumentProcessingResult is the exact composed-result schema Gemini's
    structured-output API rejected on 2026-05-03 (it is composed in code by
    agents/document.py, never used as an output_type). The checker must flag
    it — if this passes cleanly, the budget rules have gone soft."""
    violations = schema_violations(DocumentProcessingResult)
    assert violations, "the checker no longer catches the schema Gemini rejected"
    text = "\n".join(violations)
    assert "optional nested model" in text or "nesting depth" in text


# ── Retry policy (#153) ───────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(EXPECTED_STRUCTURED_AGENTS))
def test_structured_agents_have_bounded_output_retries(name):
    assert _output_retry_budget(AGENTS[name]) == OUTPUT_RETRY_BUDGET


@pytest.mark.parametrize("name", sorted(EXPECTED_TEXT_AGENTS))
def test_text_agents_keep_default_retry_budget(name):
    """Free-text agents have no output schema to retry against; the tutor
    path in particular must never gain a hidden re-roll — its failure
    handling is chat_stream's rung ladder."""
    assert _output_retry_budget(AGENTS[name]) == 1


def test_quiz_tool_retries_stay_default():
    """quiz sets output_retries only — its three read tools keep the default
    tool-retry budget (bumping tool retries was not in #153's scope)."""
    assert AGENTS["quiz_agent"]._max_tool_retries == 1


def test_worker_request_limit_fits_the_retry_ladder():
    """WORKER_LIMITS must admit 1 initial request + OUTPUT_RETRY_BUDGET
    retries: at request_limit=2 the final retry trips UsageLimitExceeded
    instead of UnexpectedModelBehavior, which misfiles "model kept emitting
    garbage" as "input too long" at routes that distinguish the two
    (routes/notes.py 413-vs-500)."""
    from agents import WORKER_LIMITS

    assert WORKER_LIMITS.request_limit == 1 + OUTPUT_RETRY_BUDGET
