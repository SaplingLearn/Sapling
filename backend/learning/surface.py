"""Surface-varied isomorphs: the surface descriptor and the cue-familiarity
dial (learning-loop spec §13 A140, flag `varied_isomorphs`).

Pure: stdlib, pydantic, learning.params and learning.checks (pure); listed in
tests/test_learning_loop_invariants.py::PURE_MODULES.

Why. Retrieval practice transfers mainly when the practice varies what the
student must recognise (Pan & Rickard 2018: transfer depends on supportive
moderators, among them varied, elaborative retrieval), and varying surface
features improves transfer and discrimination (Brunmair & Richter 2019; Raviv,
Lupyan & Green 2022). Eero Alvar's adaptive-practice framing names the dial:
how familiar a problem's cues are. So with the flag on, the drafter writes a
concept's items as ISOMORPHS — at one difficulty they test the same idea at the
same depth — that each wear their own surface, and states that surface as
structured data; and every picker that chooses the next item on a concept
prefers, among the items its own rules leave equal, one whose surface the
student has not met on that concept. Structured data only: the drafter's own
descriptor, never a text-similarity guess about two questions.

The descriptor (`Surface`): `representation`, one of
params.SURFACE_REPRESENTATIONS (how the question presents the idea), and
`context`, a short label naming its scenario (at most
SURFACE_CONTEXT_MAX_WORDS words). Stored on check_items as
`surface_representation` (plaintext: a closed enum says nothing about the
item's content) and `surface_context` (encrypted: it names the item's
scenario, which is item content).

The dial (`familiarity`): one point per surface component the student has
already met on the concept (the representation; the context), 0..2 — lower is
served first. An item with no descriptor (every item drafted before A140, and
every multi-concept item, A141) scores SURFACE_FAMILIARITY_UNKNOWN, the middle:
it is neither known to be new nor known to repeat a surface, so a picker over
only such items orders them exactly as before.

The varied drafter's output (`VariedCheckItemDraft`) is CheckItemDraft without
`answer_kind` and `stepwise` and with the two surface fields first: the check
items output sits exactly at the #153 schema budget (20 properties, recorded
live on gemini-2.5-flash-lite), so the two fields code can read off the item
make room for the two only the drafter can state. `from_varied` restores them
the way validate_draft reads them: numeric when `canonical_answer` is one
finite number, stepwise when the reference has CHECK_ITEM_STEPWISE_MIN_STEPS
numbered step lines.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field, create_model

from learning.checks import CheckItemDraft, is_finite_number, normalize, numbered_steps
from learning.params import (
    CHECK_ITEM_STEPWISE_MIN_STEPS,
    SURFACE_CONTEXT_MAX_WORDS,
    SURFACE_FAMILIARITY_UNKNOWN,
    SURFACE_REPRESENTATIONS,
)

Representation = Literal["verbal", "symbolic", "numeric", "visual", "applied"]
assert tuple(Representation.__args__) == SURFACE_REPRESENTATIONS  # one enum, two spellings

#: CheckItemDraft fields the varied draft does not carry (code reads them back).
_DERIVED = ("answer_kind", "stepwise")
#: The two surface fields, stated before the item is written (the scenario
#: steers the question), right after `difficulty`.
_SURFACE_FIELDS = {
    "surface_representation": (
        Representation,
        Field(
            description=(
                "how the question presents the idea: verbal (stated in words), symbolic "
                "(formulas, notation or code), numeric (specific numbers to work with), visual "
                "(a diagram, graph or table described in words) or applied (a concrete "
                "real-world situation)"
            )
        ),
    ),
    "surface_context": (
        str,
        Field(
            description=(
                f"at most {SURFACE_CONTEXT_MAX_WORDS} words naming the item's scenario or "
                "context; two items share a label only when they share the scenario"
            )
        ),
    ),
}


def _varied_fields() -> dict:
    fields: dict = {}
    for name, info in CheckItemDraft.model_fields.items():
        if name in _DERIVED:
            continue
        fields[name] = (info.annotation, info)
        if name == "difficulty":
            fields.update(_SURFACE_FIELDS)
    return fields


#: The varied drafter's per-item output (agents/check_items_varied.py): every
#: CheckItemDraft field with its own description, answer_kind and stepwise out,
#: the surface descriptor in. Built from CheckItemDraft's fields so a shared
#: field can never drift from the plain drafter's.
VariedCheckItemDraft = create_model(
    "VariedCheckItemDraft",
    __doc__=(
        "The varied drafter's per-item output: CheckItemDraft's fields without "
        "answer_kind and stepwise (code reads them), with the item's surface."
    ),
    **_varied_fields(),
)


class VariedCheckItemsOutput(BaseModel):
    items: list[VariedCheckItemDraft] = Field(  # type: ignore[valid-type]
        min_length=1,
        description="every item of every listed concept, one per (format, difficulty) pair",
    )


class SurfacedCheckItemDraft(CheckItemDraft):
    """A CheckItemDraft carrying the varied drafter's surface descriptor
    through repair, validation, the alignment and key checks and the write.
    Internal: never an output schema a model is sent."""

    surface_representation: str | None = None
    surface_context: str | None = None


def clip_context(label) -> str | None:
    """A context label on one line, at most SURFACE_CONTEXT_MAX_WORDS words;
    None when nothing is left."""
    words = " ".join(str(label or "").split()).split(" ")
    words = [w for w in words if w][:SURFACE_CONTEXT_MAX_WORDS]
    return " ".join(words) or None


def from_varied(draft) -> SurfacedCheckItemDraft:
    """A varied draft as the draft every later step reads: `answer_kind`
    numeric exactly when `canonical_answer` is one finite number (else free —
    validate_draft's reading), `stepwise` exactly when the reference holds
    CHECK_ITEM_STEPWISE_MIN_STEPS numbered step lines, and the surface kept
    (the context label clipped)."""
    data = draft.model_dump()
    canonical = str(data.get("canonical_answer") or "")
    data["answer_kind"] = "numeric" if is_finite_number(canonical.strip()) else "free"
    data["stepwise"] = numbered_steps(data.get("reference_answer")) >= CHECK_ITEM_STEPWISE_MIN_STEPS
    data["surface_context"] = clip_context(data.get("surface_context"))
    return SurfacedCheckItemDraft.model_validate(data)


class Surface(NamedTuple):
    representation: str
    context: str  # normalized: whitespace collapsed, case folded, no closing stop


def surface(representation, context) -> Surface | None:
    """A stored or drafted descriptor as a Surface; None unless the
    representation is one of SURFACE_REPRESENTATIONS and a context is named."""
    if representation not in SURFACE_REPRESENTATIONS:
        return None
    label = normalize(context).rstrip(".")
    return Surface(representation, label) if label else None


def surface_of(item) -> Surface | None:
    """The descriptor of a stored item or a draft (None when it has none)."""
    return surface(
        getattr(item, "surface_representation", None), getattr(item, "surface_context", None)
    )


def familiarity(candidate: Surface | None, met: Iterable[Surface]) -> int:
    """How familiar `candidate`'s surface is, given the surfaces the student
    has met on the concept: one point for a representation met, one for a
    context met (0..2); SURFACE_FAMILIARITY_UNKNOWN for no descriptor."""
    if candidate is None:
        return SURFACE_FAMILIARITY_UNKNOWN
    met = list(met)
    return int(candidate.representation in {s.representation for s in met}) + int(
        candidate.context in {s.context for s in met}
    )


def familiarity_by_hash(
    surfaces: Mapping[str, Surface | None], exposed: Collection[str]
) -> dict[str, int]:
    """question_hash → familiarity over one concept's bank. `surfaces` maps
    every item of the concept the student may have met (held ones included —
    a surface met stays met) to its descriptor; `exposed` holds the hashes the
    student has met (seen, revealed, reported, posed this session). Only a met
    item's descriptor counts as met; an item without one adds nothing."""
    met = [s for qh, s in surfaces.items() if qh in exposed and s is not None]
    return {qh: familiarity(s, met) for qh, s in surfaces.items()}
