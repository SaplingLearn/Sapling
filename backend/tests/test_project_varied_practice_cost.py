"""scripts/project_varied_practice_cost.py (spec §13 A140, A141): the offline
flag-on drafting estimate's arithmetic, hand-checked. The measurement itself
replays the check_items eval's cassettes; nothing here calls a model."""

from __future__ import annotations

import importlib
import math
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def estimate():
    saved = list(sys.path)
    sys.path.insert(0, str(SCRIPTS))
    try:
        return importlib.import_module("project_varied_practice_cost")
    finally:
        sys.path[:] = saved


def test_a_varied_item_carries_the_descriptor_not_the_derived_fields(estimate):
    from tests.test_learning_check_items import _draft

    item = estimate._varied_item(_draft())
    assert "answer_kind" not in item and "stepwise" not in item
    assert item["surface_representation"] == "numeric"
    assert len(item["surface_context"].split()) == 4  # at SURFACE_CONTEXT_MAX_WORDS


def test_the_projection_prices_the_varied_delta_and_the_combination_calls(estimate):
    from learning.params import MULTI_CONCEPT_COMBOS_PER_CALL, MULTI_CONCEPT_COMBOS_PER_DOC

    base = estimate._base()
    call = base.Call
    measured = {
        "plain": call("check_items", 1000, 500, 2000),
        "varied": call("check_items", 1200, 500, 2100),
        "varied_redraft": call("check_items", 1200, 700, 2100),
        "combo": [
            call("check_items", 1100, 300, 900),
            call("check_items_verify", 400, 1000, 300),
            call("check_items_solve", 300, 300, 200),
        ],
    }
    mix = {"check_items": "gemini-2.5-flash-lite", "check_items_verify": base.HAIKU, "check_items_solve": base.HAIKU}
    out = estimate.project(measured, mix, cached=False)
    batches = math.ceil(base.UPLOAD_CONCEPTS / 3)
    combo_calls = math.ceil(MULTI_CONCEPT_COMBOS_PER_DOC / MULTI_CONCEPT_COMBOS_PER_CALL)

    def cost(c, calls):
        return base.call_cost(c, mix[c.slot], cached=False, calls=calls)[0]

    assert out["a140"] == pytest.approx(cost(measured["varied"], batches) - cost(measured["plain"], batches))
    assert out["a140"] > 0
    assert out["a141"] == pytest.approx(sum(cost(c, combo_calls) for c in measured["combo"]))
    assert out["month"] == pytest.approx((out["a140"] + out["a141"]) * base.UPLOADS_PER_STUDENT_MONTH)
