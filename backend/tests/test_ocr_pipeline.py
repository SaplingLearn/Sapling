"""
Test the full OCR → agent → DB pipeline.

Run from backend/:
    python3 tests/test_ocr_pipeline.py
    pytest tests/test_ocr_pipeline.py -v
"""
import asyncio
import sys
import os
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
def test_agent_parse():
    print("\n[1] Testing agent parsing from raw text...")
    from services.calendar_service import _extract_via_agent
    result = asyncio.run(_extract_via_agent(SAMPLE_SYLLABUS))
    assignments = result.get("assignments", [])
    assert len(assignments) > 0, "Agent returned no assignments"
    print(f"    Agent extracted {len(assignments)} assignments:")
    for a in assignments:
        print(f"      • {a.get('title')} | {a.get('due_date')} | {a.get('assignment_type')}")


@pytest.fixture
def parsed_assignments():
    from services.calendar_service import _extract_via_agent
    result = asyncio.run(_extract_via_agent(SAMPLE_SYLLABUS))
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
    result = asyncio.run(process_and_save_syllabus(
        file_bytes=fake_bytes,
        filename="syllabus_test.txt",
        content_type="text/plain",
        user_id=TEST_USER,
    ))
    print(f"    assignments returned : {len(result['assignments'])}")
    print(f"    saved_count          : {result['saved_count']}")
    print(f"    warnings             : {result.get('warnings', [])}")
    assert result["saved_count"] >= 0, "save_count should be non-negative"
    print("    Pipeline OK")


# ── Agent-path unit tests (fully mocked, no live API) ─────────────────────────


class TestExtractAssignmentsViaAgent:
    """Unit tests for `extract_assignments_from_file` covering agent-first
    extraction and graceful degrade. The raw-Gemini legacy fallback was
    retired in #144, so agent failures now degrade to an empty result +
    warning — no second LLM call.

    These mocks bypass `extract_text_from_file` and the agent so the tests
    run offline and don't depend on GEMINI_API_KEY.
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
        wire dict contains those values."""
        from services import calendar_service

        agent_output = self._agent_output()
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
            result = asyncio.run(calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            ))

        assert agent_run.await_count == 1
        titles = [a["title"] for a in result["assignments"]]
        assert titles == ["Lab 7: Recursion"]
        # Adapter-added keys flow through.
        assert result["course_title"] == "CS 101"
        assert "grading_categories" in result
        # raw_text passthrough comes from the OCR-extracted text.
        assert result["raw_text"] == "syllabus body"
        # Each assignment carries the wire-format defaults.
        first = result["assignments"][0]
        assert first["assignment_type"] == "other"
        assert first["due_date"] == "2026-03-15"

    def test_degrades_gracefully_on_usage_limit(self):
        """UsageLimitExceeded from the agent degrades to an empty result
        with a warning — and does NOT make a second LLM call."""
        from services import calendar_service
        from pydantic_ai.exceptions import UsageLimitExceeded

        agent_run = AsyncMock(side_effect=UsageLimitExceeded("token cap"))

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="text body",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
        ):
            result = asyncio.run(calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            ))

        assert agent_run.await_count == 1
        assert result["assignments"] == []
        assert result["warnings"]  # non-empty, user-facing
        assert result["raw_text"] == "text body"

    def test_degrades_gracefully_on_unexpected_exception(self):
        """A bare Exception from the agent also degrades gracefully."""
        from services import calendar_service

        agent_run = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="text body",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
        ):
            result = asyncio.run(calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            ))

        assert agent_run.await_count == 1
        assert result["assignments"] == []
        assert result["warnings"]
        assert result["raw_text"] == "text body"

    def test_empty_text_shortcut(self):
        """Empty-text shortcut returns the placeholder dict and never
        invokes the agent."""
        from services import calendar_service

        agent_run = AsyncMock()

        with (
            patch.object(
                calendar_service, "extract_text_from_file",
                return_value="   \n  ",
            ),
            patch.object(
                calendar_service.syllabus_extraction_agent, "run", agent_run,
            ),
        ):
            result = asyncio.run(calendar_service.extract_assignments_from_file(
                b"raw", "syllabus.pdf", "application/pdf",
            ))

        assert result["assignments"] == []
        assert result["warnings"] == [
            "No text could be extracted from the file."
        ]
        assert result["raw_text"] == ""
        assert agent_run.await_count == 0


def test_agent_and_degrade_paths_share_required_keys():
    """Both the agent-success path and the degrade path must expose the
    legacy-required keys {assignments, warnings, raw_text} so consumers
    (`routes/calendar.py::extract`, `process_and_save_syllabus`) keep
    working. This pins the invariant against a future refactor.
    """
    from services import calendar_service

    LEGACY_REQUIRED = {"assignments", "warnings", "raw_text"}

    # ── Agent success path ────────────────────────────────────────
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
        agent_result = asyncio.run(calendar_service.extract_assignments_from_file(
            b"raw", "syllabus.pdf", "application/pdf",
        ))

    assert LEGACY_REQUIRED.issubset(set(agent_result.keys())), (
        f"Agent path missing required legacy keys: "
        f"{LEGACY_REQUIRED - set(agent_result.keys())}"
    )

    # ── Degrade path (agent fails) ────────────────────────────────
    agent_run_fail = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        patch.object(
            calendar_service, "extract_text_from_file",
            return_value="fallback body",
        ),
        patch.object(
            calendar_service.syllabus_extraction_agent, "run", agent_run_fail,
        ),
    ):
        degrade_result = asyncio.run(calendar_service.extract_assignments_from_file(
            b"raw", "syllabus.pdf", "application/pdf",
        ))

    assert LEGACY_REQUIRED.issubset(set(degrade_result.keys())), (
        f"Degrade path missing required legacy keys: "
        f"{LEGACY_REQUIRED - set(degrade_result.keys())}"
    )
    assert degrade_result["assignments"] == []


class TestNotesEncryptedAtWrite:
    """#126 / #144 acceptance: assignment `notes` are encrypted at the write
    boundary in `insert_new_assignments` — never persisted as plaintext."""

    def test_notes_encrypted_on_insert(self):
        from services import calendar_service

        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "assignments":
                def _insert(rows):
                    captured["rows"] = rows
                    return rows
                m.insert.side_effect = _insert
            m.select.return_value = []
            return m

        with (
            patch.object(calendar_service, "table", side_effect=table_side_effect),
            patch.object(
                calendar_service, "load_existing_assignment_keys", return_value=set(),
            ),
            patch("services.academics.enrollment_id_for", return_value="enr-1"),
            patch.object(
                calendar_service, "encrypt_if_present",
                side_effect=lambda v: f"enc({v})",
            ) as enc,
        ):
            n = calendar_service.insert_new_assignments(
                "user-1",
                [{
                    "title": "HW1", "due_date": "2026-03-01",
                    "course_id": "c1", "notes": "secret note",
                }],
            )

        assert n == 1
        row = captured["rows"][0]
        # notes went through encrypt_if_present — not persisted as plaintext.
        enc.assert_any_call("secret note")
        assert row["notes"] == "enc(secret note)"
        assert row["notes"] != "secret note"


if __name__ == "__main__":
    print("=" * 55)
    print("Sapling OCR Pipeline Test")
    print("DB: Supabase")
    print("=" * 55)

    try:
        from services.calendar_service import _extract_via_agent
        test_agent_parse()
        assignments = asyncio.run(_extract_via_agent(SAMPLE_SYLLABUS)).get("assignments", [])
        test_save_to_db(assignments)
        test_full_pipeline()
        print("\n✓ All tests passed")
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
