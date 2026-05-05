"""
Test the full OCR → Gemini → DB pipeline.

Run from backend/:
    python3 tests/test_ocr_pipeline.py
    pytest tests/test_ocr_pipeline.py -v
"""
import sys
import os
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

# The integration tests below hit live Gemini + Supabase. The agent-path
# unit tests in TestExtractAssignmentsViaAgent are fully mocked, so they
# run without GEMINI_API_KEY — gate per-test rather than at the module.
_requires_gemini = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="OCR/Gemini integration tests require GEMINI_API_KEY",
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.calendar_service import save_assignments_to_db, process_and_save_syllabus
from db.connection import table

# ── Fake syllabus text (skips OCR so no Tesseract needed) ──────────────────────
SAMPLE_SYLLABUS = """
CS 101 — Introduction to Programming
Spring 2026

Assignments & Deadlines
-----------------------
Lab 7: Recursion                    Due: March 15, 2026
Problem Set 3: Loops & Functions    Due: March 20, 2026
Midterm Project                     Due: April 1, 2026   (project)
Final Exam                          Due: May 10, 2026    (exam)
Quiz 4: OOP Basics                  Due: March 28, 2026
"""

TEST_USER = "user_andres"


@_requires_gemini
def test_gemini_parse():
    print("\n[1] Testing Gemini parsing from raw text...")
    from services.calendar_service import parse_syllabus
    result = parse_syllabus(SAMPLE_SYLLABUS)
    assignments = result.get("assignments", [])
    assert len(assignments) > 0, "Gemini returned no assignments"
    print(f"    Gemini extracted {len(assignments)} assignments:")
    for a in assignments:
        print(f"      • {a.get('title')} | {a.get('due_date')} | {a.get('assignment_type')}")


@pytest.fixture
def parsed_assignments():
    from services.calendar_service import parse_syllabus
    result = parse_syllabus(SAMPLE_SYLLABUS)
    return result.get("assignments", [])


@_requires_gemini
def test_save_to_db(parsed_assignments):
    print("\n[2] Testing save_assignments_to_db()...")
    before_rows = table("assignments").select(
        "id", filters={"user_id": f"eq.{TEST_USER}"}
    )
    before = len(before_rows)

    assignments = parsed_assignments
    saved = save_assignments_to_db(TEST_USER, assignments)
    # Deduped against DB: first run saves all; later runs may save 0 (#16)
    assert 0 <= saved <= len(assignments), f"Expected at most {len(assignments)} new rows, got {saved}"

    after_rows = table("assignments").select(
        "title,due_date,assignment_type",
        filters={"user_id": f"eq.{TEST_USER}"},
        order="due_date.asc",
    )
    after = len(after_rows)

    print(f"    Saved {saved} rows (DB went from {before} → {after} for {TEST_USER})")
    print("    Sample rows now in DB:")
    for r in after_rows[-5:]:
        print(f"      • {r['title']} | {r['due_date']} | {r['assignment_type']}")


@_requires_gemini
def test_full_pipeline():
    print("\n[3] Testing process_and_save_syllabus() full pipeline with a text/plain file...")
    fake_bytes = SAMPLE_SYLLABUS.encode("utf-8")
    result = process_and_save_syllabus(
        file_bytes=fake_bytes,
        filename="syllabus_test.txt",
        content_type="text/plain",
        user_id=TEST_USER,
    )
    print(f"    assignments returned : {len(result['assignments'])}")
    print(f"    saved_count          : {result['saved_count']}")
    print(f"    warnings             : {result.get('warnings', [])}")
    assert result["saved_count"] >= 0, "save_count should be non-negative"
    print("    Pipeline OK")


# ── Agent-path unit tests (fully mocked, no live API) ─────────────────────────


class TestExtractAssignmentsViaAgent:
    """Unit tests for `extract_assignments_from_file` covering the
    agent-first / legacy-fallback orchestration added in refactor #4.

    These mocks bypass `extract_text_from_file`, the agent, and the
    legacy parser so the tests run offline and don't depend on
    GEMINI_API_KEY.
    """

    def _agent_output(self, *, due_date=None):
        from agents.syllabus_extraction import (
            SyllabusAssignments,
            SyllabusAssignment,
        )
        return SyllabusAssignments(
            course_title="CS 101",
            instructor=None,
            assignments=[
                SyllabusAssignment(
                    title="Lab 7: Recursion",
                    description="Hands-on recursion lab.",
                    due_date=due_date or date(2026, 3, 15),
                    weight_pct=10.0,
                ),
            ],
            grading_categories=[],
        )

    def test_returns_agent_assignments(self):
        """Happy path: agent.run returns a SyllabusAssignments and the
        wire dict contains those values (not the legacy parser's)."""
        from services import calendar_service

        agent_output = self._agent_output()
        agent_run = AsyncMock(return_value=SimpleNamespace(output=agent_output))

        # Sentinel so we'd notice if the legacy path fired.
        legacy_sentinel = {"assignments": [{"title": "LEGACY"}], "warnings": []}

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="syllabus body",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
            patch.object(
                calendar_service, "parse_syllabus",
                return_value=legacy_sentinel,
            ),
        ):
            result = calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            )

        # Agent path was used (not legacy sentinel).
        assert agent_run.await_count == 1
        titles = [a["title"] for a in result["assignments"]]
        assert titles == ["Lab 7: Recursion"]
        assert "LEGACY" not in titles
        # Adapter-added keys flow through.
        assert result["course_title"] == "CS 101"
        assert "grading_categories" in result
        # raw_text passthrough comes from the OCR-extracted text.
        assert result["raw_text"] == "syllabus body"
        # Each assignment carries the wire-format defaults.
        first = result["assignments"][0]
        assert first["assignment_type"] == "other"
        assert first["due_date"] == "2026-03-15"

    def test_falls_back_to_legacy_on_usage_limit(self):
        """UsageLimitExceeded from the agent triggers the legacy path."""
        from services import calendar_service
        from pydantic_ai.exceptions import UsageLimitExceeded

        agent_run = AsyncMock(side_effect=UsageLimitExceeded("token cap"))
        legacy_result = {
            "assignments": [{"title": "Legacy assignment", "due_date": "2026-04-01"}],
            "warnings": [],
        }

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="text body",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
            patch.object(
                calendar_service, "parse_syllabus",
                return_value=dict(legacy_result),
            ) as legacy_mock,
        ):
            result = calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            )

        assert agent_run.await_count == 1
        assert legacy_mock.call_count == 1
        assert result["assignments"] == legacy_result["assignments"]
        # raw_text is filled in by the fallback branch when missing.
        assert result["raw_text"] == "text body"

    def test_falls_back_to_legacy_on_unexpected_exception(self):
        """A bare Exception from the agent also degrades to legacy."""
        from services import calendar_service

        agent_run = AsyncMock(side_effect=RuntimeError("boom"))
        legacy_result = {
            "assignments": [{"title": "Fallback HW", "due_date": "2026-05-01"}],
            "warnings": ["agent failed"],
        }

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="text body",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
            patch.object(
                calendar_service, "parse_syllabus",
                return_value=dict(legacy_result),
            ) as legacy_mock,
        ):
            result = calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            )

        assert agent_run.await_count == 1
        assert legacy_mock.call_count == 1
        assert result["assignments"][0]["title"] == "Fallback HW"
        assert result["warnings"] == ["agent failed"]

    def test_legacy_path_still_works_when_text_empty(self):
        """Empty-text shortcut returns the placeholder dict and never
        invokes either the agent or the legacy parser."""
        from services import calendar_service

        agent_run = AsyncMock()
        legacy_mock = AsyncMock()  # unused; just an assertion target

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="   \n  ",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
            patch.object(
                calendar_service, "parse_syllabus", legacy_mock,
            ),
        ):
            result = calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            )

        assert result["assignments"] == []
        assert result["warnings"] == [
            "No text could be extracted from the file."
        ]
        assert result["raw_text"] == ""
        assert agent_run.await_count == 0
        assert legacy_mock.call_count == 0


def test_agent_and_legacy_paths_share_required_keys():
    """The agent path's wire format must be a SUPERSET of the legacy
    path's. Any consumer (`routes/calendar.py::extract`,
    `process_and_save_syllabus`) that worked on the legacy
    `{assignments, warnings, raw_text}` keys MUST work on the agent
    path too. Extra keys (`course_title`, `grading_categories`) are
    additive — new fields, not replacements. This test pins the
    invariant so a future refactor can't silently drop a key.
    """
    from services import calendar_service

    LEGACY_REQUIRED = {"assignments", "warnings", "raw_text"}

    # ── Agent path ────────────────────────────────────────────────
    from agents.syllabus_extraction import (
        SyllabusAssignments,
        SyllabusAssignment,
    )
    agent_output = SyllabusAssignments(
        course_title="CS 101",
        instructor=None,
        assignments=[
            SyllabusAssignment(
                title="Lab 7",
                description="recursion",
                due_date=date(2026, 3, 15),
                weight_pct=10.0,
            ),
        ],
        grading_categories=[],
    )
    agent_run = AsyncMock(return_value=SimpleNamespace(output=agent_output))

    with (
        patch.object(
            calendar_service, "extract_text_from_file",
            return_value="syllabus body",
        ),
        patch.object(
            calendar_service.syllabus_extraction_agent, "run", agent_run,
        ),
    ):
        agent_result = calendar_service.extract_assignments_from_file(
            b"raw", "syllabus.pdf", "application/pdf",
        )

    assert LEGACY_REQUIRED.issubset(set(agent_result.keys())), (
        f"Agent path missing required legacy keys: "
        f"{LEGACY_REQUIRED - set(agent_result.keys())}"
    )

    # ── Legacy fallback path ──────────────────────────────────────
    legacy_dict = {
        "assignments": [{"title": "HW1", "due_date": "2026-03-01"}],
        "warnings": [],
        # Note: parse_syllabus historically did NOT set raw_text — the
        # service backfills it via setdefault. The contract test must
        # reflect the *post-fallback* shape that consumers actually see.
    }
    agent_run_fail = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch.object(
            calendar_service, "extract_text_from_file",
            return_value="fallback body",
        ),
        patch.object(
            calendar_service.syllabus_extraction_agent, "run", agent_run_fail,
        ),
        patch.object(
            calendar_service, "parse_syllabus",
            return_value=dict(legacy_dict),
        ),
    ):
        legacy_result = calendar_service.extract_assignments_from_file(
            b"raw", "syllabus.pdf", "application/pdf",
        )

    assert LEGACY_REQUIRED.issubset(set(legacy_result.keys())), (
        f"Legacy fallback path missing required legacy keys: "
        f"{LEGACY_REQUIRED - set(legacy_result.keys())}"
    )


if __name__ == "__main__":
    print("=" * 55)
    print("Sapling OCR Pipeline Test")
    print("DB: Supabase")
    print("=" * 55)

    try:
        from services.calendar_service import parse_syllabus
        test_gemini_parse()
        assignments = parse_syllabus(SAMPLE_SYLLABUS).get("assignments", [])
        test_save_to_db(assignments)
        test_full_pipeline()
        print("\n✓ All tests passed")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
