"""The shared study-guide contract fixture validates against the models.

`tests/fixtures/study_guide_contract.json` is the one example both sides
agree on: this test holds the backend to it, and the frontend's reader tests
render the same file (`frontend/src/lib/studyGuide/types.ts` mirrors
`models/study_guide.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

from models.study_guide import BLOCK_TYPES, GuideDetail, parse_items

FIXTURE = Path(__file__).parent / "fixtures" / "study_guide_contract.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_round_trips_through_the_models():
    raw = _fixture()
    assert GuideDetail.model_validate(raw).model_dump(mode="json") == raw


def test_fixture_shows_every_block_type():
    sections = _fixture()["content"]["sections"]
    seen = {item["type"] for section in sections for item in section["items"]}
    assert seen == {"prose", *BLOCK_TYPES}


def test_a_malformed_block_is_rejected_without_losing_its_neighbours():
    items = _fixture()["content"]["sections"][0]["items"]
    broken = {"type": "check", "id": "x", "question": "q", "options": []}
    valid, rejected = parse_items([items[0], broken, {"type": "unknown"}, items[1]])
    assert [item.id for item in valid] == [items[0]["id"], items[1]["id"]]
    assert rejected == [broken, {"type": "unknown"}]
