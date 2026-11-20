"""pydantic-evals cases for the planned quiz writer (learning-loop spec §13
A144, flag `quiz_planned_questions`; agents/quiz_planned.py).

The flag sends a new quiz prompt and schema, so it is turned on only after
this dataset is recorded live and passes. Not in run_all.py's DATASETS until
then (a dataset with no cassettes fails replay); record it with:

    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/quiz_generation_planned.py
    SAPLING_EVAL_UPDATE_BASELINES=1 SAPLING_EVAL_MODE=replay python tests/evals/quiz_generation_planned.py

then add "quiz_generation_planned" to run_all.py's DATASETS in the same change.

Every case's input is the message the route builds (agents/quiz_planned.py::
build_message) from a fixed plan, so the evaluators can check the output
against the plan itself: one item per QUESTION line, the requested format,
four options with the key among them, every tag a listed key and never on the
key, every TARGET embodied by a tagged distractor, and — the yield the prompt
was written to raise (A132 (g)) — no item-writing flaw that keeps an answer
out of evidence (learning/quiz_evidence.py::EVIDENCE_EXCLUDING_FLAGS).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agents.quiz_planned import PlannedQuiz, build_message, quiz_planned_agent
from learning import quiz_evidence, quiz_gates, quiz_plan
from _replay import cli_main, run_with_cassette

DATASET = "quiz_generation_planned"


def _plan_case(name, *, concept, fmt, p_known, requested, count, open_keys, bank, material=""):
    keys = quiz_plan.misconception_keys(open_keys, bank)
    specs = quiz_plan.question_specs(count, requested=requested, p_known=p_known, keys=keys, question_format=fmt)
    message = build_message(
        concept_name=concept, question_format=fmt, specs=specs, keys=keys, material_block=material
    )
    return Case(
        name=name,
        inputs=message,
        metadata={
            "format": fmt,
            "slots": [s.slot for s in specs],
            "targets": {s.slot: s.target for s in specs if s.target},
            "keys": [k.key for k in keys],
        },
    )


_HASH_BANK = [
    ("divides_buckets_by_entries", "Divides the number of buckets by the number of entries."),
    ("counts_only_occupied_buckets", "Counts only the occupied buckets as the table size."),
    ("load_factor_is_percent_full_rows", "Thinks the load factor is the share of full chains."),
]
_HASH_MATERIAL = (
    "[chunk c1]\nA hash table's load factor is the number of stored entries divided by the "
    "number of buckets. With linear probing, performance degrades sharply as the load factor "
    "approaches 1, so tables usually resize when it passes 0.5 to 0.75."
)

CASES: list[Case[str, PlannedQuiz]] = [
    _plan_case(
        "novice_mc_targets_held_key",
        concept="Load Factor",
        fmt="multiple_choice",
        p_known=0.2,
        requested="adaptive",
        count=3,
        open_keys=[("divides_buckets_by_entries", 2)],
        bank=_HASH_BANK,
        material=_HASH_MATERIAL,
    ),
    _plan_case(
        "developing_mc_three_targets",
        concept="Load Factor",
        fmt="multiple_choice",
        p_known=0.5,
        requested="adaptive",
        count=4,
        open_keys=[],
        bank=_HASH_BANK,
        material=_HASH_MATERIAL,
    ),
    _plan_case(
        "proficient_mc_no_keys",
        concept="Photosynthesis",
        fmt="multiple_choice",
        p_known=0.9,
        requested="adaptive",
        count=3,
        open_keys=[],
        bank=[],
    ),
    _plan_case(
        "explicit_easy_short_answer",
        concept="Mitosis",
        fmt="short_answer",
        p_known=0.6,
        requested="easy",
        count=3,
        open_keys=[],
        bank=[("confuses_mitosis_with_meiosis", "Confuses mitosis with meiosis.")],
    ),
    _plan_case(
        "mixed_hard_with_targets",
        concept="Derivatives",
        fmt="mixed",
        p_known=0.85,
        requested="hard",
        count=4,
        open_keys=[("power_rule_drops_exponent", 1)],
        bank=[("product_rule_multiplies_derivatives", "Multiplies the two derivatives in the product rule.")],
    ),
]


@dataclass
class SlotCoverageEvaluator(Evaluator[str, PlannedQuiz]):
    """One item per QUESTION line: every slot answered, exactly once."""

    def evaluate(self, ctx: EvaluatorContext[str, PlannedQuiz]) -> float:
        slots = (ctx.metadata or {}).get("slots", [])
        got = [q.slot for q in ctx.output.questions]
        return 1.0 if sorted(got) == sorted(slots) else 0.0


@dataclass
class FormatEvaluator(Evaluator[str, PlannedQuiz]):
    def evaluate(self, ctx: EvaluatorContext[str, PlannedQuiz]) -> float:
        fmt = (ctx.metadata or {}).get("format")
        qs = ctx.output.questions
        if fmt == "mixed" or not qs:
            return 1.0
        return sum(1 for q in qs if q.type == fmt) / len(qs)


@dataclass
class McShapeEvaluator(Evaluator[str, PlannedQuiz]):
    """Four options, the key copied verbatim among them."""

    def evaluate(self, ctx: EvaluatorContext[str, PlannedQuiz]) -> float:
        mc = [q for q in ctx.output.questions if q.type == "multiple_choice"]
        if not mc:
            return 1.0
        return sum(1 for q in mc if len(q.options) == 4 and q.correct_answer in q.options) / len(mc)


@dataclass
class TagValidityEvaluator(Evaluator[str, PlannedQuiz]):
    """Every non-empty tag is a listed key, on a distractor; one tag per option."""

    def evaluate(self, ctx: EvaluatorContext[str, PlannedQuiz]) -> float:
        keys = set((ctx.metadata or {}).get("keys", []))
        mc = [q for q in ctx.output.questions if q.type == "multiple_choice"]
        if not mc:
            return 1.0
        ok = 0
        for q in mc:
            tags = q.option_misconceptions
            if len(tags) != len(q.options):
                continue
            correct = q.options.index(q.correct_answer) if q.correct_answer in q.options else -1
            if all((not t) or (t in keys and i != correct) for i, t in enumerate(tags)):
                ok += 1
        return ok / len(mc)


@dataclass
class TargetEvaluator(Evaluator[str, PlannedQuiz]):
    """A multiple-choice item for a TARGET slot tags a distractor with it."""

    def evaluate(self, ctx: EvaluatorContext[str, PlannedQuiz]) -> float:
        targets = {int(k): v for k, v in ((ctx.metadata or {}).get("targets") or {}).items()}
        items = {q.slot: q for q in ctx.output.questions if q.type == "multiple_choice"}
        asked = [(slot, key) for slot, key in targets.items() if slot in items]
        if not asked:
            return 1.0
        hit = 0
        for slot, key in asked:
            q = items[slot]
            correct = q.options.index(q.correct_answer) if q.correct_answer in q.options else -1
            kept = quiz_gates.validate_tags(
                q.option_misconceptions, options=len(q.options), correct_index=correct, allowed={key}
            )
            hit += key in kept
        return hit / len(asked)


@dataclass
class EvidenceYieldEvaluator(Evaluator[str, PlannedQuiz]):
    """No multiple-choice item carries an item-writing flaw that keeps its
    answer out of evidence (A132 (g)): the plain prompt's measured rate was
    10 of 29 (`correct_longest`)."""

    def evaluate(self, ctx: EvaluatorContext[str, PlannedQuiz]) -> float:
        mc = [q for q in ctx.output.questions if q.type == "multiple_choice" and q.correct_answer in q.options]
        if not mc:
            return 1.0
        clean = 0
        for q in mc:
            correct = q.options.index(q.correct_answer)
            wire = {
                "question": q.question,
                "options": [{"text": t, "correct": i == correct} for i, t in enumerate(q.options)],
            }
            clean += not quiz_evidence.evidence_exclusion(quiz_evidence.lint_question(wire))
        return clean / len(mc)


_INPUT_TO_NAME: dict[str, str] = {c.inputs: c.name for c in CASES}


async def _run(case_input: str) -> PlannedQuiz:
    return await run_with_cassette(
        dataset=DATASET,
        case_name=_INPUT_TO_NAME.get(case_input, "unknown"),
        agent=quiz_planned_agent,
        case_input=case_input,
        output_model=PlannedQuiz,
    )


def make_dataset() -> Dataset[str, PlannedQuiz]:
    return Dataset(
        name=DATASET,
        cases=CASES,
        evaluators=[
            SlotCoverageEvaluator(),
            FormatEvaluator(),
            McShapeEvaluator(),
            TagValidityEvaluator(),
            TargetEvaluator(),
            EvidenceYieldEvaluator(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
