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
never leaks its reference into the prompt, and is stored — valid under
validate_draft once repair_draft has made the repairs that need no guess,
exactly as check_item_service.create_items stores it (the A22 / A37 option,
numeric and stepwise rules and the A34 final_answer rules included).
McOptionsValid (spec §13 A37) is required at 1.0: every mc_reason draft's
options pass every A37 option rule, and a case with no mc_reason draft scores
0.0 — the live sequence test of 2026-09-27 stored 0 of 12 when the options were
parallel arrays. McReasonValid is the share of mc_reason drafts stored (the A34
final_answer rules included), gated at its recorded rate.
McCorrectNotLongest (review of A37) is the share of stored mc_reason drafts
whose correct option is not strictly the longest, gated at its recorded rate.
FinalAnswerValid (spec §13 A34) is required at 1.0: every accepted draft states
a final_answer copied character for character from its reference_answer (a
substring, surrounding whitespace and a closing period aside) that is not in
its prompt — the answer the tutor's leak check matches. validate_draft already
rejects an answer missing from the reference after checks.answer_tokens'
normalisation, so repeating that check here would score 1.0 whatever the
model wrote; the verbatim copy is what the prompt asks for and code does not
enforce.
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
from learning.checks import (  # noqa: E402
    MC_OPTION_RULES,
    answer_in,
    leak_in_prompt,
    repair_draft,
    validate_draft,
)
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


def _stored(draft) -> bool:
    """Whether create_items would store `draft`: valid once repaired (A37)."""
    return validate_draft(repair_draft(draft)[0]) == []


@dataclass
class DraftValidEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """Share of items that would be stored — the A22 / A37 option, numeric
    and stepwise rules included, after repair_draft (partial credit)."""

    def evaluate(self, ctx: _Ctx) -> float:
        items = ctx.output.items
        return sum(_stored(i) for i in items) / len(items) if items else 0.0


def _mc_share(ctx: _Ctx, pred) -> float:
    """The share of the case's mc_reason drafts satisfying pred; 0.0 when it
    has none (the mc_reasoned channel would have no items)."""
    mc = [i for i in ctx.output.items if i.format == "mc_reason"]
    return sum(pred(i) for i in mc) / len(mc) if mc else 0.0


@dataclass
class McReasonValidEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """A37: the share of the case's mc_reason drafts that would be stored."""

    def evaluate(self, ctx: _Ctx) -> float:
        return _mc_share(ctx, _stored)


@dataclass
class McOptionsValidEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """A37, required 1.0: the share of the case's mc_reason drafts whose
    options pass every A37 option rule (MC_OPTION_RULES) once repaired — the
    structure the parallel arrays broke; the A34 rules are McReasonValid's."""

    def evaluate(self, ctx: _Ctx) -> float:
        def options_ok(draft) -> bool:
            reasons = validate_draft(repair_draft(draft)[0])
            return not any(r.startswith(f"{rule}:") for r in reasons for rule in MC_OPTION_RULES)

        return _mc_share(ctx, options_ok)


def _correct_is_longest(draft) -> bool:
    """Whether the option marked correct is STRICTLY the longest by
    characters (whitespace runs collapsed): a student who picks the longest
    option finds it. A tie hides it."""
    lengths = [(len(" ".join(o.text.split())), o.is_correct) for o in draft.options]
    right = [n for n, correct in lengths if correct]
    others = [n for n, correct in lengths if not correct]
    return len(right) == 1 and bool(others) and right[0] > max(others)


@dataclass
class McCorrectNotLongestEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """A37 review: the share of the case's STORED mc_reason drafts whose
    correct option is not strictly the longest — the length cue that let
    "pick the longest" find the answer in 10 of 12 live HIST200 items. Gated
    at its recorded rate (the prompt asks for options alike in length; code
    cannot shorten an option, and a drop rule cost most of the yield); 0.0
    when the case stores no mc_reason draft."""

    def evaluate(self, ctx: _Ctx) -> float:
        stored = [i for i in ctx.output.items if i.format == "mc_reason" and _stored(i)]
        return sum(not _correct_is_longest(i) for i in stored) / len(stored) if stored else 0.0


def _copied(final_answer: str, text: str) -> bool:
    """A34's "copied verbatim": the final answer, trimmed of surrounding
    whitespace and a closing period, is a substring of `text`."""
    core = final_answer.strip().rstrip(".").strip()
    return bool(core) and core in text


@dataclass
class FinalAnswerValidEvaluator(Evaluator[CheckItemsInput, CheckItemsOutput]):
    """A34, required 1.0: every accepted draft (one create_items would
    store) states a final_answer copied verbatim from its reference_answer and
    not in its prompt; 0.0 when no draft is accepted."""

    def evaluate(self, ctx: _Ctx) -> float:
        accepted = [i for i in ctx.output.items if _stored(i)]
        ok = all(
            _copied(i.final_answer, i.reference_answer) and not answer_in(i.prompt, i.final_answer)
            for i in accepted
        )
        return 1.0 if accepted and ok else 0.0


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
            McReasonValidEvaluator(),
            McOptionsValidEvaluator(),
            McCorrectNotLongestEvaluator(),
            FinalAnswerValidEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
