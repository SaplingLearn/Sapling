"""The varied mc_reason top-up (learning loop spec §13 A37 × A140, flag
`varied_isomorphs`).

The A37 top-up (agents/check_items_topup.py) for a drafting run the varied
drafter (agents/check_items_varied.py) made: the same request — one concept's
missing mc_reason items, at the difficulties it lacks, told why earlier drafts
were dropped — under the varied schema, so each item states its surface, and
shown the surfaces the concept's stored items already use, so its items take
other contexts. Built from the plain top-up's and the varied drafter's
fragments; its own agent with ONE prompt stack (spec §8 invariant 12), on the
check_items model slot, billed under the top-up's feature.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from pydantic_ai import Agent

from agents._providers import model_for
from agents.check_items import (
    _CHUNK_IDS,
    _NO_REFERENCE_IN_PROMPT,
    _UNTRUSTED,
    CheckItemsUnavailable,
    passages_section,
    run_drafting,
)
from agents.check_items_topup import (
    _TOPUP_INTRO,
    _TOPUP_RULES,
    _TOPUP_SHAPES,
    TOPUP_FEATURE,
    build_topup_prompt,
)
from agents.check_items_varied import ANSWER_RULES, SURFACE_RULES, surfaces_section
from agents.deps import SaplingDeps
from learning.params import CHECK_ITEM_OUTPUT_RETRIES
from learning.surface import VariedCheckItemsOutput

_PROMPT = (
    f"{_TOPUP_INTRO}{SURFACE_RULES}{_TOPUP_RULES}"
    f"{ANSWER_RULES}{_NO_REFERENCE_IN_PROMPT}{_TOPUP_SHAPES}"
    f"{_CHUNK_IDS}{_UNTRUSTED}"
)
_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]

check_items_varied_topup_agent = Agent[SaplingDeps, VariedCheckItemsOutput](
    model=model_for("check_items"),
    deps_type=SaplingDeps,
    output_type=VariedCheckItemsOutput,
    # Tool-less agent, so `retries=` IS the output-validation budget (#153).
    retries=CHECK_ITEM_OUTPUT_RETRIES,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "check_items_varied_topup"},
)


def build_varied_topup_prompt(
    concept_name: str,
    passages: list[dict],
    *,
    difficulties: list[int],
    drop_reasons: list[str],
    used: Sequence[tuple[str, str]] = (),
) -> str:
    """The plain top-up's message with the concept's stored surfaces between
    the request and the passages."""
    plain = build_topup_prompt(
        concept_name, [], difficulties=difficulties, drop_reasons=drop_reasons
    )
    head = plain[: -len(passages_section([]))]
    return head + surfaces_section({concept_name: list(used)}) + passages_section(passages)


async def draft_mc_topup_varied(
    concept_name: str,
    passages: list[dict],
    *,
    difficulties: list[int],
    drop_reasons: list[str],
    used: Sequence[tuple[str, str]] = (),
    deps: SaplingDeps,
    flex: bool,
) -> VariedCheckItemsOutput | CheckItemsUnavailable:
    """One varied top-up run for one concept: never raises, Flex-retried like
    the plain top-up, billed as TOPUP_FEATURE on the check_items slot."""
    return await run_drafting(
        check_items_varied_topup_agent,
        build_varied_topup_prompt(
            concept_name,
            passages,
            difficulties=difficulties,
            drop_reasons=drop_reasons,
            used=used,
        ),
        deps=deps,
        flex=flex,
        feature=TOPUP_FEATURE,
    )

