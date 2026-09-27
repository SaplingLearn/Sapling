"""pydantic-evals cases for the check_items generator (learning loop PKG-04).

    python tests/evals/check_items.py            # replay
    SAPLING_EVAL_MODE=record python tests/evals/check_items.py

Cases are derived from fixtures/tutor_course.json (plaintext by design): for
the first two documents, up to three concept_notes each → 6 cases, one concept
per call (the standard tier; Flex is a serving choice, not a quality one).
Chunks are the document summary plus each concept_note description, ids
"<document_id>:c<i>". Add cases when production produces a bad item; never
edit an existing one to make it pass.

Evaluators score the contracts the service enforces in code
(learning/checks.py::validate_draft) plus grounding: every item has a
reference answer, >= CHECK_ITEM_MIN_RUBRIC rubric items and >=
CHECK_ITEM_MIN_WRONG paired, unique wrong reasons, cites only input chunk ids,
never leaks its reference into the prompt, and passes validate_draft (the A22
option / numeric / stepwise rules included).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic_evals import Case, Dataset  # noqa: E402
from pydantic_evals.evaluators import Evaluator, EvaluatorContext  # noqa: E402

from agents.check_items import CheckItemsOutput, build_prompt, check_items_agent  # noqa: E402
from learning.checks import leak_in_prompt, validate_draft  # noqa: E402
from learning.params import CHECK_ITEM_MIN_RUBRIC, CHECK_ITEM_MIN_WRONG  # noqa: E402
from _replay import (  # noqa: E402  (sibling, sys.path-injected)
    MODE,
    _run_with_retry,
    cli_main,
    load_cassette,
    make_deps,
    save_cassette,
)

# (concept_name, ((chunk_id, chunk_text), ...)) — hashable so _INPUT_TO_NAME works.
CheckItemsInput = tuple[str, tuple[tuple[str, str], ...]]

_FIXTURE = Path(__file__).parent / "fixtures" / "tutor_course.json"
_DOCS_PER_DATASET = 2
_CONCEPTS_PER_DOC = 3
_MAX_CASES = 8  # the eval-recording budget per dataset


def _cases() -> list[Case[CheckItemsInput, CheckItemsOutput]]:
    data = json.loads(_FIXTURE.read_text())
    cases = []
    for doc in data["documents"][:_DOCS_PER_DATASET]:
        chunks = [(f"{doc['document_id']}:c0", doc["summary"])] + [
            (f"{doc['document_id']}:c{i + 1}", f"{n['name']}: {n['description']}")
            for i, n in enumerate(doc["concept_notes"])
        ]
        for note in doc["concept_notes"][:_CONCEPTS_PER_DOC]:
            name = note["name"]
            cases.append(
                Case(
                    name=f"{doc['document_id']}__{name.lower().replace(' ', '_')}",
                    inputs=(name, tuple(chunks)),
                )
            )
    assert len(cases) <= _MAX_CASES
    return cases


CASES = _cases()
_INPUT_TO_NAME = {c.inputs: c.name for c in CASES}


def _ids(ctx) -> set[str]:
    return {cid for cid, _ in ctx.inputs[1]}


_Ctx = EvaluatorContext[CheckItemsInput, CheckItemsOutput]


def _every(ctx: _Ctx, pred) -> float:
    """1.0 when every item satisfies pred; 0.0 when none exist or one fails."""
    items = ctx.output.items
    return 1.0 if items and all(pred(i) for i in items) else 0.0


@dataclass
class HasReferenceEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    def evaluate(self, ctx: _Ctx) -> float:
        return _every(ctx, lambda i: bool(i.reference_answer.strip()))


@dataclass
class RubricCountEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    def evaluate(self, ctx: _Ctx) -> float:
        return _every(ctx, lambda i: len(i.rubric) >= CHECK_ITEM_MIN_RUBRIC)


@dataclass
class WrongReasonCountEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """>= CHECK_ITEM_MIN_WRONG reasons, unique keys, keys and texts paired."""

    def evaluate(self, ctx: _Ctx) -> float:
        return _every(
            ctx,
            lambda i: (
                len(i.wrong_keys) >= CHECK_ITEM_MIN_WRONG
                and len(set(i.wrong_keys)) == len(i.wrong_keys) == len(i.wrong_texts)
            ),
        )


@dataclass
class CitesChunkEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """Share of items whose cited ids are all input ids (partial credit)."""

    def evaluate(self, ctx: _Ctx) -> float:
        items = ctx.output.items
        return sum(set(i.chunk_ids) <= _ids(ctx) for i in items) / len(items) if items else 0.0


@dataclass
class NoLeakInPromptEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    def evaluate(self, ctx: _Ctx) -> float:
        return _every(ctx, lambda i: not leak_in_prompt(i.prompt, i.reference_answer))


@dataclass
class DraftValidEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """Share of items passing validate_draft — the A22 option / numeric /
    stepwise rules included (partial credit)."""

    def evaluate(self, ctx: _Ctx) -> float:
        items = ctx.output.items
        return sum(validate_draft(i) == [] for i in items) / len(items) if items else 0.0


async def _run(case_input: CheckItemsInput) -> CheckItemsOutput:
    concept, chunks = case_input
    case_name = _INPUT_TO_NAME.get(case_input, "unknown")
    if MODE == "replay":
        body = load_cassette("check_items", case_name)
        if body is None:
            raise RuntimeError(
                f"No cassette for check_items/{case_name}. Run with SAPLING_EVAL_MODE=record."
            )
        return CheckItemsOutput.model_validate(body)
    passages = [{"id": cid, "text": text} for cid, text in chunks]
    result = await _run_with_retry(
        check_items_agent, build_prompt([concept], passages), make_deps()
    )
    if MODE == "record":
        save_cassette("check_items", case_name, result.output)
    return result.output


def make_dataset() -> Dataset[CheckItemsInput, CheckItemsOutput]:
    return Dataset(
        name="check_items",
        cases=CASES,
        evaluators=[
            HasReferenceEvaluator(),
            RubricCountEvaluator(),
            WrongReasonCountEvaluator(),
            CitesChunkEvaluator(),
            NoLeakInPromptEvaluator(),
            DraftValidEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
