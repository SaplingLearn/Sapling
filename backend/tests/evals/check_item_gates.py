"""pydantic-evals datasets for the check-item pipeline's own model steps
(#866 Z24, Z25; learning loop spec §13 A37, A119, A124, A140, A141).

Every drafting call of a learning-loop uploader runs more model steps than the
drafter (`check_items.py`): the A119 alignment check decides which criteria
and which concept an item is stored under, the A124 blind solve (and the key
match for a free-text pair code cannot settle) decides whether its key is
verified, and the A37 mc_reason top-up refills a concept below the floor. With
`varied_isomorphs` on the drafter and the top-up are the A140 varied agents;
with `multi_concept_items` on, the A141 combination drafter and its own check
run too. Their verdicts decide what every student's evidence is graded
against, and none had a dataset. One dataset per step, each on the slot the
step runs on, each case built with production's own message builder:

    check_items_verify   the A119 check (check_items_verify slot)
    check_items_solve    the A124 blind solve and key match (check_items_solve slot)
    check_items_topup    the A37 mc_reason top-up (check_items slot)
    check_items_varied   the A140 varied drafter and varied top-up (check_items slot)
    check_items_combo    the A141 combination drafter (check_items slot) and its
                         check (check_items_verify slot)

    cd backend
    SAPLING_EVAL_MODE=record python tests/evals/check_item_gates.py     # three runs: README
    python tests/evals/check_item_gates.py                              # replay

Recorded in the A111 pass (three runs, floors from their minimum); until then
each fails closed in replay (no cassette, no baseline). Cassettes store what
they were recorded under (`_replay.recorded_under`), so a changed prompt,
schema, model or message never replays an old answer. Add a case when
production surfaces a miss; never edit one to make it pass.

The drafting datasets score what code would store — the check_items.py
evaluators, after `learning.surface.from_varied` for a varied draft — plus each
step's own contract (the top-up's count, format and difficulties; a varied
concept's distinct surfaces; a combination draft's label). The checks are
scored by production's own reading of their answers: `item_alignment.align`
for A119, `item_keys.compare` for the solve, `check_items_key_match.matches`
for the key match, `item_alignment.collect_components` for A141.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import BaseModel  # noqa: E402
from pydantic_evals import Case, Dataset  # noqa: E402
from pydantic_evals.evaluators import Evaluator  # noqa: E402

import check_items as plain  # noqa: E402  (sibling: the drafter's evaluators)
from _replay import (  # noqa: E402
    CASSETTE_DIR,
    ensure_utf8_output,
    evaluate_dataset,
    input_identity,
    prompt_identity,
    recorded_under,
    run_settings,
    run_with_cassette,
    schema_hash,
)
from agents._providers import model_name_for  # noqa: E402
from agents.check_items import CheckItemsOutput  # noqa: E402
from agents.check_items_combo import (  # noqa: E402
    _PROMPT_HASH as COMBO_PROMPT_HASH,
    build_combo_prompt,
    check_items_combo_agent,
)
from agents.check_items_combo_verify import (  # noqa: E402
    _PROMPT_HASH as COMBO_VERIFY_PROMPT_HASH,
    ComboVerifyItem,
    ComponentChecks,
    build_combo_verify_prompt,
    check_items_combo_verify_agent,
    component_verdicts,
)
from agents.check_items_key_match import (  # noqa: E402
    _PROMPT_HASH as MATCH_PROMPT_HASH,
    KeyMatches,
    MatchItem,
    build_match_prompt,
    check_items_key_match_agent,
    matches,
)
from agents.check_items_solve import (  # noqa: E402
    _PROMPT_HASH as SOLVE_PROMPT_HASH,
    SOLVE_TASK,
    Solutions,
    SolveItem,
    build_solve_prompt,
    check_items_solve_agent,
    solutions,
)
from agents.check_items_topup import (  # noqa: E402
    _PROMPT_HASH as TOPUP_PROMPT_HASH,
    build_topup_prompt,
    check_items_topup_agent,
)
from agents.check_items_varied import (  # noqa: E402
    _PROMPT_HASH as VARIED_PROMPT_HASH,
    build_varied_prompt,
    check_items_varied_agent,
)
from agents.check_items_varied_topup import (  # noqa: E402
    _PROMPT_HASH as VARIED_TOPUP_PROMPT_HASH,
    build_varied_topup_prompt,
    check_items_varied_topup_agent,
)
from agents.check_items_verify import (  # noqa: E402
    _PROMPT_HASH as VERIFY_PROMPT_HASH,
    VERIFY_TASK,
    AlignmentChecks,
    VerifyItem,
    build_verify_prompt,
    check_items_verify_agent,
    verdicts,
)
from learning.item_alignment import (  # noqa: E402
    NO_CONCEPT,
    NONE,
    UNASKED_RUBRIC,
    align,
    component_ids,
    concept_key,
)
from learning.item_keys import (  # noqa: E402
    AGREE,
    DISPUTED,
    DISPUTED_REASON,
    TO_MATCH,
    UNSOLVED,
    KeySubject,
    compare,
)
from learning.multi_concept import label as combo_label  # noqa: E402
from learning.surface import VariedCheckItemsOutput, from_varied, surface_of  # noqa: E402

#: Every dataset stays inside the eval-recording budget of the series.
MAX_CASES = 8

# ── shared fixtures ──────────────────────────────────────────────────────────

_FIXTURE = Path(__file__).parent / "fixtures" / "tutor_course.json"


def _course_doc(index: int) -> tuple[list[str], tuple[tuple[str, str], ...]]:
    """(concept names, chunks) of one fixture document, chunked as check_items.py does."""
    doc = json.loads(_FIXTURE.read_text())["documents"][index]
    chunks = ((f"{doc['document_id']}:c0", doc["summary"]),) + tuple(
        (f"{doc['document_id']}:c{i + 1}", f"{n['name']}: {n['description']}")
        for i, n in enumerate(doc["concept_notes"])
    )
    return [n["name"] for n in doc["concept_notes"]], chunks


def _passages(chunks) -> list[dict]:
    return [{"id": cid, "text": text} for cid, text in chunks]


#: The A119 live walkthrough's course (spec §13 A119): a hash-tables lecture.
HASH_CONCEPTS = [
    "Hash Table",
    "Hash Function",
    "Load Factor",
    "Separate Chaining",
    "Open Addressing",
    "Linear Probing",
    "Tombstone Deletion",
]
HASH_PASSAGES = [
    {
        "id": "h1",
        "text": (
            "A hash table's load factor is the number of stored entries divided by the number of "
            "buckets. A table with 12 entries in 16 buckets has a load factor of 0.75; one with 6 "
            "entries in 8 buckets also has 0.75."
        ),
    },
    {
        "id": "h2",
        "text": (
            "Separate chaining keeps a linked list in each bucket: every key that hashes to the "
            "bucket is stored in that list. Open addressing stores every key in the table itself "
            "and, after a collision, probes for another free bucket; linear probing tries the next "
            "bucket, wrapping around at the end of the table."
        ),
    },
]


@dataclass(frozen=True)
class Step:
    """One case's model step: the agent, its output schema, its prompt hash and
    the slot whose model it runs on (the slot's model is the agent's own)."""

    agent: object
    output: type
    prompt_hash: str
    slot: str


def _identity(step: Step, message: str) -> dict:
    return recorded_under(
        prompt_hash=prompt_identity(step.prompt_hash, step.agent),
        schema_hash=schema_hash(step.output),
        model=model_name_for(step.slot),
        input_sha256=input_identity(message, run_settings(step.agent)),
    )


def _runner(dataset: str, cases: list[Case], steps: dict[str, Step]):
    """The run function of one dataset: each case's message through its step,
    record or replay (`_replay.run_with_cassette`, identity-checked)."""
    by_input = {c.inputs: c for c in cases}

    async def _run(case_input):
        case = by_input[case_input]
        step = steps[case.metadata["kind"]]
        message = case.metadata["message"]
        return await run_with_cassette(
            dataset=dataset,
            case_name=case.name,
            agent=step.agent,
            case_input=message,
            output_model=step.output,
            identity=_identity(step, message),
        )

    _run.identity = lambda case: _identity(steps[case.metadata["kind"]], case.metadata["message"])
    return _run


def _case(name: str, kind: str, message: str, inputs=None, **expected) -> Case:
    """A case whose input is its message (unique per dataset) unless `inputs`
    gives the drafter-shaped input the check_items evaluators read."""
    return Case(
        name=name,
        inputs=inputs if inputs is not None else message,
        metadata={"kind": kind, "message": message, **expected},
    )


def _kind(ctx) -> str:
    return (ctx.metadata or {}).get("kind", "")


# ── A119: the alignment check (check_items_verify) ──────────────────────────

VERIFY = Step(check_items_verify_agent, AlignmentChecks, VERIFY_PROMPT_HASH, VERIFY_TASK)


def _vitem(n: int, fmt: str, prompt: str, criteria: tuple[str, ...], correct=None, others=()):
    return VerifyItem(str(n), fmt, prompt, correct, tuple(others), criteria)


def _verify_case(name: str, items: list[VerifyItem], expected: dict[str, tuple]) -> Case:
    """`expected`: item id -> (criteria kept, the concept it tests or NONE)."""
    return _case(
        name,
        "verify",
        build_verify_prompt(HASH_CONCEPTS, items),
        criteria={i.id: len(i.criteria) for i in items},
        expected={k: [list(keep), concept] for k, (keep, concept) in expected.items()},
    )


VERIFY_CASES = [
    _verify_case(  # the A119 live item: r2 is not asked, and it tests Load Factor
        "verify_live_load_factor",
        [
            _vitem(
                1,
                "mc_reason",
                "A linear-probing table has m = 5 buckets and holds 4 entries. Pick the load "
                "factor and give the reason.",
                (
                    "Reasons that the 4 entries are divided by the 5 buckets",
                    "Notes that 0.8 is above the 0.5 linear-probing threshold",
                ),
                correct="0.8",
                others=("1.25", "0.2", "4"),
            )
        ],
        {"1": ((0,), "Load Factor")},
    ),
    _verify_case(  # the A119 live smoke's five-item call
        "verify_live_five_item_call",
        [
            _vitem(1, "free", "What does a hash function map a key to?",
                   ("States that it maps the key to a bucket index",)),
            _vitem(2, "teachback",
                   "Explain to a classmate how separate chaining stores two keys that hash to the "
                   "same bucket.",
                   ("Explains that both keys are kept in that bucket's list",
                    "Describes how a lookup walks the list to find a key")),
            _vitem(3, "free",
                   "Why does open addressing mark a deleted slot with a tombstone instead of "
                   "emptying it?",
                   ("Says an emptied slot would end a later probe early and hide keys stored past it",
                    "Says the table must be resized when tombstones pile up")),
            _vitem(4, "free",
                   "In a sorted array of 16 values, how many comparisons does binary search need "
                   "at most to find a value?",
                   ("Gives the number of halvings of the range",)),
            _vitem(5, "free", "A table holds 12 entries in 16 buckets. What is its load factor?",
                   ("Divides the 12 entries by the 16 buckets", "Gives 0.75")),
        ],
        {
            "1": ((0,), "Hash Function"),
            "2": ((0,), "Separate Chaining"),
            "3": ((0,), "Tombstone Deletion"),
            "4": ((0,), NONE),
            "5": ((0, 1), "Load Factor"),
        },
    ),
    _verify_case(  # the most specific listed concept, not the setting
        "verify_most_specific_concept",
        [
            _vitem(1, "free",
                   "In a table of 8 buckets that uses linear probing, a key collides at bucket 7. "
                   "Which bucket is tried next?",
                   ("Names bucket 0, wrapping around past the end",)),
        ],
        {"1": ((0,), "Linear Probing")},
    ),
]


def _verdict_alignments(ctx):
    """(item id, expected, production's Alignment) for every item of a verify case."""
    found = verdicts(ctx.output)
    scope = {concept_key(n): n for n in HASH_CONCEPTS}
    for item_id, (keep, concept) in ctx.metadata["expected"].items():
        own = concept_key(concept if concept != NONE else HASH_CONCEPTS[0])
        verdict = found.get(item_id)
        yield item_id, (tuple(keep), concept), align(
            ctx.metadata["criteria"][item_id], own, verdict, scope
        )


@dataclass
class CriteriaKept(Evaluator):
    """A119 (a): the share of items whose kept criteria are exactly the asked ones."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) != "verify":
            return 1.0
        rows = [
            got.keep == keep
            for _, (keep, concept), got in _verdict_alignments(ctx)
            if concept != NONE and not got.unverified
        ] + [False for _, _, got in _verdict_alignments(ctx) if got.unverified]
        return sum(rows) / len(rows) if rows else 0.0


@dataclass
class ConceptTested(Evaluator):
    """A119 (b): the share of items filed under the concept they test (a
    question testing none of the listed concepts is rejected as such)."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) != "verify":
            return 1.0
        rows = []
        for _, (_, concept), got in _verdict_alignments(ctx):
            if concept == NONE:
                rows.append(got.reject == NO_CONCEPT)
            else:
                rows.append(got.reject is None and got.concept_key == concept_key(concept))
        return sum(rows) / len(rows) if rows else 0.0


@dataclass
class EveryItemAnswered(Evaluator):
    """Every item (and, for a combination, every component) got one complete,
    consistent answer: an unanswered item is held as unverified."""

    def evaluate(self, ctx) -> float:
        kind, meta, out = _kind(ctx), ctx.metadata, ctx.output
        if kind == "verify":
            return 1.0 if set(meta["expected"]) <= set(verdicts(out)) else 0.0
        if kind == "solve":
            return 1.0 if set(meta["expected"]) <= set(solutions(out)) else 0.0
        if kind == "match":
            return 1.0 if set(meta["expected"]) <= set(matches(out)) else 0.0
        if kind == "combo_verify":
            return 1.0 if set(meta["expected"]) <= set(component_verdicts(out)) else 0.0
        return 1.0


def make_verify_dataset() -> Dataset:
    return Dataset(
        name="check_items_verify",
        cases=VERIFY_CASES,
        evaluators=[CriteriaKept(), ConceptTested(), EveryItemAnswered()],
    )


# ── A124: the blind solve and the key match (check_items_solve) ─────────────

SOLVE = Step(check_items_solve_agent, Solutions, SOLVE_PROMPT_HASH, SOLVE_TASK)
MATCH = Step(check_items_key_match_agent, KeyMatches, MATCH_PROMPT_HASH, SOLVE_TASK)


def _subject(fmt, prompt, options=(), *, answer_kind="free", correct=None, canonical=None,
             final=""):
    return KeySubject(fmt, prompt, tuple(options), answer_kind, correct, canonical, None, final)


#: (the stored key, the outcomes a correct solve gives) per item, ids "1".. as
#: services/check_item_service.py::_key_checks_for numbers them.
_SOLVE_ITEMS = [
    (_subject("mc_reason", "A table holds 12 entries in 16 buckets. Which value is its load factor?",
              (("A", "0.75"), ("B", "1.33"), ("C", "16"), ("D", "4")), correct="A", final="0.75"),
     [AGREE]),
    (_subject("mc_reason",  # a wrong key: the independent solve must dispute it
              "Which collision strategy keeps a linked list in each bucket?",
              (("A", "Open addressing"), ("B", "Linear probing"), ("C", "Separate chaining"),
               ("D", "Tombstone deletion")), correct="B", final="Linear probing"),
     [DISPUTED]),
    (_subject("free", "A table holds 6 entries in 8 buckets. Give its load factor as a decimal.",
              answer_kind="numeric", canonical="0.75", final="0.75"),
     [AGREE]),
    (_subject("free", "In what year was the hash table first described?", final="1953"),
     [UNSOLVED]),  # the passages do not settle it
    (_subject("free", "What does separate chaining keep in each bucket?", final="a linked list"),
     [AGREE, TO_MATCH]),  # solvable; a free-text pair the key match settles
]
_SOLVE_MESSAGE = build_solve_prompt(
    HASH_PASSAGES,
    [SolveItem(str(n), s.format, s.prompt, s.options, s.answer_kind)
     for n, (s, _) in enumerate(_SOLVE_ITEMS, start=1)],
)

_MATCH_ITEMS = [  # (question, the key, an independent answer, same?)
    ("What does separate chaining keep in each bucket?", "a linked list",
     "a list of the entries that hash to it", True),
    ("What is the derivative of x^2?", "2x", "x^2/2", False),
    ("What is the load factor of a table with 12 entries in 16 buckets?", "0.75",
     "three quarters", True),
    ("Which collision strategy keeps a linked list in each bucket?", "separate chaining",
     "open addressing", False),
    ("What stops factorial(0) from recursing forever?", "the base case returns 1",
     "the base case, which returns 1 when n is 0", True),
]
_MATCH_MESSAGE = build_match_prompt(
    [MatchItem(str(n), q, key, other) for n, (q, key, other, _) in enumerate(_MATCH_ITEMS, start=1)]
)

SOLVE_CASES = [
    _case("solve_five_item_call", "solve", _SOLVE_MESSAGE,
          expected={str(n): [list(outcomes), s._asdict()]
                    for n, (s, outcomes) in enumerate(_SOLVE_ITEMS, start=1)}),
    _case("key_match_five_pairs", "match", _MATCH_MESSAGE,
          expected={str(n): same for n, (_, _, _, same) in enumerate(_MATCH_ITEMS, start=1)}),
]


@dataclass
class SolveAgreement(Evaluator):
    """A124: the share of items whose solve, compared with the key in code
    (`item_keys.compare`), gives a correct solve's outcome — agreeing with a
    right key, disputing a wrong one, unsolved when the passages do not settle it."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) != "solve":
            return 1.0
        solved = solutions(ctx.output)
        rows = [
            compare(KeySubject(**{**subject, "options": tuple(map(tuple, subject["options"]))}),
                    solved.get(item_id)) in outcomes
            for item_id, (outcomes, subject) in ctx.metadata["expected"].items()
        ]
        return sum(rows) / len(rows)


@dataclass
class MatchAgreement(Evaluator):
    """A124: the share of free-text pairs the key match judges as a person would."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) != "match":
            return 1.0
        found = matches(ctx.output)
        rows = [found.get(item_id) is same for item_id, same in ctx.metadata["expected"].items()]
        return sum(rows) / len(rows)


def make_solve_dataset() -> Dataset:
    return Dataset(
        name="check_items_solve",
        cases=SOLVE_CASES,
        evaluators=[SolveAgreement(), MatchAgreement(), EveryItemAnswered()],
    )


# ── drafting outputs, scored as code would store them ───────────────────────


class Drafts(BaseModel):
    """What a drafting step stores from: `items` (a varied draft as
    `from_varied` reads it back), the shape check_items.py's evaluators read."""

    items: list


def _as_drafts(out) -> Drafts:
    if isinstance(out, VariedCheckItemsOutput):
        return Drafts(items=[from_varied(d) for d in out.items])
    return Drafts(items=list(out.items))


#: check_items.py's evaluators: the contracts code enforces (repair, validate_draft,
#: the A34 / A37 rules) and grounding.
_STORE_EVALUATORS = (
    plain.HasReferenceEvaluator,
    plain.RubricCountEvaluator,
    plain.WrongReasonCountEvaluator,
    plain.CitesChunkEvaluator,
    plain.NoLeakInPromptEvaluator,
    plain.DraftValidEvaluator,
    plain.FinalAnswerValidEvaluator,
)


@dataclass
class ScoredAsStored(Evaluator):
    """One check_items.py evaluator, on the case's drafts as code reads them."""

    inner: Evaluator

    def evaluate(self, ctx) -> float:
        if _kind(ctx) not in ("topup", "varied", "varied_topup", "combo"):
            return 1.0
        return self.inner.evaluate(_Ctx(ctx.inputs, _as_drafts(ctx.output), ctx.metadata))

    def get_default_evaluation_name(self) -> str:
        return type(self.inner).__name__


@dataclass
class _Ctx:
    inputs: object
    output: Drafts
    metadata: dict


# ── A37: the mc_reason top-up (check_items slot) ────────────────────────────

TOPUP = Step(check_items_topup_agent, CheckItemsOutput, TOPUP_PROMPT_HASH, "check_items")


def _topup_case(name: str, doc: int, concept: str, difficulties: list[int], reasons: list[str],
                *, varied: bool = False, used=()) -> Case:
    _, chunks = _course_doc(doc)
    if varied:
        message = build_varied_topup_prompt(
            concept, _passages(chunks), difficulties=difficulties, drop_reasons=reasons, used=used
        )
    else:
        message = build_topup_prompt(
            concept, _passages(chunks), difficulties=difficulties, drop_reasons=reasons
        )
    return _case(name, "varied_topup" if varied else "topup", message, inputs=(concept, chunks),
                 concepts=[concept], difficulties=difficulties)


TOPUP_CASES = [
    _topup_case("topup_limits_after_dropped_drafts", 0, "Limits", [2, 3],
                [UNASKED_RUBRIC, DISPUTED_REASON]),
    _topup_case("topup_recursion_too_few", 1, "Recursion", [1], []),
]


@dataclass
class TopupShape(Evaluator):
    """A37: exactly the items asked for — mc_reason, one per requested
    difficulty in order, on the one concept."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) not in ("topup", "varied_topup"):
            return 1.0
        items = _as_drafts(ctx.output).items
        want = ctx.metadata["difficulties"]
        concept = concept_key(ctx.metadata["concepts"][0])
        ok = (
            [i.difficulty for i in items] == want
            and all(i.format == "mc_reason" for i in items)
            and all(concept_key(i.concept) == concept for i in items)
        )
        return 1.0 if ok else 0.0


def _drafting_evaluators(*extra: Evaluator) -> list[Evaluator]:
    return [ScoredAsStored(e()) for e in _STORE_EVALUATORS] + [
        ScoredAsStored(plain.McOptionsValidEvaluator()),
        *extra,
    ]


def make_topup_dataset() -> Dataset:
    return Dataset(name="check_items_topup", cases=TOPUP_CASES, evaluators=_drafting_evaluators(TopupShape()))


# ── A140: the varied drafter and varied top-up (check_items slot) ───────────

VARIED = Step(check_items_varied_agent, VariedCheckItemsOutput, VARIED_PROMPT_HASH, "check_items")
VARIED_TOPUP = Step(
    check_items_varied_topup_agent, VariedCheckItemsOutput, VARIED_TOPUP_PROMPT_HASH, "check_items"
)


def _varied_case(name: str, doc: int, used: dict | None = None) -> Case:
    concepts, chunks = _course_doc(doc)
    concepts = concepts[:3]  # one production call: CHECK_ITEM_CONCEPTS_PER_CALL concepts
    message = build_varied_prompt(concepts, _passages(chunks), used or {})
    return _case(name, "varied", message, inputs=(tuple(concepts), chunks), concepts=concepts)


VARIED_CASES = [
    _varied_case("varied_calculus_three_concepts", 0),
    _varied_case(  # an upload after an earlier run: the stored surfaces are listed
        "varied_recursion_with_stored_surfaces",
        1,
        {"Recursion": [("symbolic", "factorial function"), ("applied", "nested folders")]},
    ),
    _topup_case("varied_topup_limits", 0, "Limits", [2, 3], [UNASKED_RUBRIC], varied=True,
                used=[("numeric", "table of values near 0")]),
]


@dataclass
class SurfacesVary(Evaluator):
    """A140: every drafted item states a surface, and within a concept no two
    items share one (the varied prompt's whole point)."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) not in ("varied", "varied_topup"):
            return 1.0
        by_concept: dict[str, list] = {}
        for item in _as_drafts(ctx.output).items:
            surface = surface_of(item)
            if surface is None:
                return 0.0
            by_concept.setdefault(concept_key(item.concept), []).append(surface)
        if not by_concept:
            return 0.0
        return sum(len(set(s)) == len(s) for s in by_concept.values()) / len(by_concept)


@dataclass
class ConceptsCovered(Evaluator):
    """check_items.py's ConceptsCovered on a multi-concept drafting call: every
    requested concept (or combination) gets a stored item, none unasked."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) not in ("varied", "combo"):
            return 1.0
        return plain.ConceptsCoveredEvaluator().evaluate(
            _Ctx(ctx.inputs, _as_drafts(ctx.output), ctx.metadata)
        )


def make_varied_dataset() -> Dataset:
    return Dataset(
        name="check_items_varied",
        cases=VARIED_CASES,
        evaluators=_drafting_evaluators(TopupShape(), SurfacesVary(), ConceptsCovered()),
    )


# ── A141: the combination drafter and its check ─────────────────────────────

COMBO = Step(check_items_combo_agent, CheckItemsOutput, COMBO_PROMPT_HASH, "check_items")
COMBO_VERIFY = Step(
    check_items_combo_verify_agent, ComponentChecks, COMBO_VERIFY_PROMPT_HASH, VERIFY_TASK
)

_CALCULUS, _CALC_CHUNKS = _course_doc(0)  # Limits, Derivatives, Chain Rule
_COMBOS = [combo_label(["Chain Rule", "Derivatives"]), combo_label(["Derivatives", "Limits"])]


def _combo_verify_case(name: str, items: list[tuple[VerifyItem, tuple[str, ...], dict]]) -> Case:
    """`items`: (the item, its components apex first, component id -> required)."""
    message = build_combo_verify_prompt([ComboVerifyItem(item, comps) for item, comps, _ in items])
    return _case(
        name,
        "combo_verify",
        message,
        expected={item.id: required for item, _, required in items},
        criteria={item.id: len(item.criteria) for item, _, _ in items},
    )


COMBO_CASES = [
    _case("combo_two_calculus_combinations", "combo",
          build_combo_prompt(_COMBOS, _passages(_CALC_CHUNKS)),
          inputs=(tuple(_COMBOS), _CALC_CHUNKS), concepts=_COMBOS),
    _combo_verify_case(
        "combo_verify_needed_and_setting_only",
        [
            (  # both concepts are steps of the answer
                _vitem(1, "free", "Differentiate sin(x^2) and name the rule you used.",
                       ("Gives 2x cos(x^2)", "Names the chain rule")),
                ("Chain Rule", "Derivatives"),
                {"k1": True, "k2": True},
            ),
            (  # Limits is only the setting: the answer never uses it
                _vitem(2, "free",
                       "A limit problem sheet asks for the derivative of 3x^2. What is it?",
                       ("Gives 6x",)),
                ("Derivatives", "Limits"),
                {"k1": True, "k2": False},
            ),
        ],
    ),
]


@dataclass
class ComponentsRequired(Evaluator):
    """A141: the share of components judged as the question needs them (an item
    whose every component is needed is stored; one that names a setting-only
    concept is rejected, never stored under a narrower tag)."""

    def evaluate(self, ctx) -> float:
        if _kind(ctx) != "combo_verify":
            return 1.0
        found = component_verdicts(ctx.output)
        rows = []
        for item_id, required in ctx.metadata["expected"].items():
            verdict = found.get(item_id)
            for kid in component_ids(len(required)):
                rows.append(verdict is not None and verdict.required.get(kid) is required[kid])
        return sum(rows) / len(rows) if rows else 0.0


def make_combo_dataset() -> Dataset:
    return Dataset(
        name="check_items_combo",
        cases=COMBO_CASES,
        evaluators=_drafting_evaluators(ConceptsCovered(), ComponentsRequired(), EveryItemAnswered()),
    )


# ── the datasets ─────────────────────────────────────────────────────────────

_STEPS = {
    "verify": VERIFY,
    "solve": SOLVE,
    "match": MATCH,
    "topup": TOPUP,
    "varied": VARIED,
    "varied_topup": VARIED_TOPUP,
    "combo": COMBO,
    "combo_verify": COMBO_VERIFY,
}

#: The steps every learning-loop uploader's drafting runs: always replayed, so
#: a missing recording fails CI (fail closed, like any dataset in run_all.py).
DEFAULT_PATH = ("check_items_verify", "check_items_solve", "check_items_topup")
#: The flag-gated drafters (`varied_isomorphs`, `multi_concept_items`, both off):
#: replayed once recorded, like `quiz_generation_planned` — the flag waits on
#: the recording, and from then on CI keeps scoring its prompt.
ONCE_RECORDED = ("check_items_varied", "check_items_combo")

#: dataset name -> (make, run), every dataset (what a record run records).
ALL_VARIANTS = {
    name: (make, _runner(name, make().cases, _STEPS))
    for name, make in (
        ("check_items_verify", make_verify_dataset),
        ("check_items_solve", make_solve_dataset),
        ("check_items_topup", make_topup_dataset),
        ("check_items_varied", make_varied_dataset),
        ("check_items_combo", make_combo_dataset),
    )
}
assert set(ALL_VARIANTS) == set(DEFAULT_PATH) | set(ONCE_RECORDED)
for _name, (_make, _run_fn) in ALL_VARIANTS.items():
    _cases = _make().cases
    assert len(_cases) <= MAX_CASES, _name
    assert len({c.inputs for c in _cases}) == len(_cases), f"{_name}: inputs must be unique"


def recorded(name: str) -> bool:
    """Whether a dataset's cassette namespace holds recordings."""
    folder = CASSETTE_DIR / name
    return folder.is_dir() and any(folder.glob("*.json"))


def replay_variants(*, recorded=recorded) -> dict:
    """The datasets a replay scores: the default path always, a flag-gated
    drafter once it is recorded. Baselines key on the dataset name."""
    return {
        name: pair
        for name, pair in ALL_VARIANTS.items()
        if name in DEFAULT_PATH or recorded(name)
    }


#: run_all.py iterates these.
VARIANTS = replay_variants()


if __name__ == "__main__":
    ensure_utf8_output()
    update = os.getenv("SAPLING_EVAL_UPDATE_BASELINES") == "1"
    only = [s for s in (os.getenv("CHECK_ITEM_GATES_DATASETS") or "").split(",") if s]
    results = {
        name: evaluate_dataset(make, run, update=update)
        for name, (make, run) in ALL_VARIANTS.items()
        if not only or name in only
    }
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if not all(results.values()):
        sys.exit(1)
