"""Every major's seed pack is valid content.

`MajorPack` validation runs at import, so a malformed pack would already fail
here — these tests pin the product-level promises on top of the schema: the
six majors the admin UI offers, four distinct catalog courses each, and no
placeholder text reaching a tester's screen on prod.
"""
from __future__ import annotations

import re

import pytest

from services.account_seed.packs import PACKS

EXPECTED_MAJORS = ["cs", "business", "biology", "psychology", "health", "mech_eng"]

# BU catalog format: SCHOOL DEPT NUMBER, e.g. "CAS CS 111".
_CODE_RE = re.compile(r"^[A-Z]{2,4} [A-Z]{2} \d{3}$")
_PLACEHOLDER_RE = re.compile(r"lorem ipsum|\bTODO\b|\bTBD\b|concept \d+\b|placeholder", re.I)


def test_registry_lists_the_six_majors_in_ui_order():
    assert list(PACKS) == EXPECTED_MAJORS


@pytest.mark.parametrize("key", EXPECTED_MAJORS)
def test_pack_has_four_distinct_catalog_courses(key):
    pack = PACKS[key]
    assert pack.key == key
    codes = [c.code for c in pack.courses]
    assert len(codes) == 4 and len(set(codes)) == 4
    for code in codes:
        assert _CODE_RE.match(code), code


@pytest.mark.parametrize("key", EXPECTED_MAJORS)
def test_pack_has_no_placeholder_text(key):
    dumped = PACKS[key].model_dump_json()
    match = _PLACEHOLDER_RE.search(dumped)
    assert match is None, f"{key}: placeholder text {match.group(0)!r}"


@pytest.mark.parametrize("key", EXPECTED_MAJORS)
def test_pack_has_graded_history_and_upcoming_work(key):
    # The seeder grades only past-due items. A term-start offset split keeps
    # both the gradebook (graded) and the dashboard (upcoming) populated on
    # any seed day inside the term.
    for course in PACKS[key].courses:
        offsets = sorted(a.due_offset_days for a in course.assignments)
        assert any(a.points_earned is not None for a in course.assignments), course.code
        assert offsets[0] < 45 and offsets[-1] > 70, (course.code, offsets)


def test_course_nicknames_and_colors_distinct_within_a_major():
    for key, pack in PACKS.items():
        assert len({c.nickname for c in pack.courses}) == 4, key
        assert len({c.color.lower() for c in pack.courses}) == 4, key
