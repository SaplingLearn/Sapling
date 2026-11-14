"""Encryption-at-rest + decrypt-integrity across every encrypted column (#398).

The epic's highest-value check: a silent decrypt regression corrupts data
invisibly. Using the #397 raw-SQL seam, we read the *seeded* baseline rows
directly with psycopg and assert two things per encrypted column:

  1. the raw stored bytes are ciphertext (NOT the known plaintext), and
  2. the app's decrypt helper round-trips them back to the expected value.

Reading the seed (rather than writing fresh rows) keeps the assertion anchored to
known-constant plaintext across all three flavours — text (`decrypt_if_present`),
numeric (`decrypt_numeric`, for `assignments.points_*`), and JSON
(`decrypt_json`, for `sessions.summary_json`). The route-level encrypt-on-write
path is covered separately by the flagship note test in test_local_stack.py.

Plaintext constants mirror db/seed_local_rich (kept as literals here for the same
import-ordering reason the conftest documents).
"""
import pytest

from services.encryption import decrypt_if_present, decrypt_json, decrypt_numeric

pytestmark = pytest.mark.integration


# (label, table, id_column, id_value, column, expected_plaintext)
_TEXT_COLUMNS = [
    ("user_profiles.name", "user_profiles", "user_id", "rich-user-active", "name", "Rich Active"),
    ("user_profiles.first_name", "user_profiles", "user_id", "rich-user-active", "first_name", "Rich"),
    ("notes.title", "notes", "id", "rich-note-cs-week1", "title", "Week 1 — Variables"),
    ("notes.body", "notes", "id", "rich-note-cs-week1", "body",
     "A variable binds a name to a value. Types: int, str, bool, float."),
    ("documents.summary", "documents", "id", "rich-doc-cs-syllabus", "summary",
     "CS101 syllabus: weekly homework, one midterm, final project."),
    ("documents.extracted_text", "documents", "id", "rich-doc-cs-syllabus", "extracted_text",
     "CS101 — Introduction to Computer Science. Weekly homework due Fridays..."),
    ("messages.content", "messages", "id", "rich-msg-cs-recursion-1", "content",
     "Can you explain recursion?"),
    ("room_messages.text", "room_messages", "id",
     "11111111-1111-4111-8111-000000000001", "text",
     "Anyone up for reviewing recursion before the midterm?"),
    ("feedback.comment", "feedback", "id", "rich-fb-1", "comment",
     "The tutor cited the wrong lecture."),
    ("feedback.topic", "feedback", "id", "rich-fb-1", "topic", "chat"),
    ("issue_reports.topic", "issue_reports", "id", "rich-issue-1", "topic",
     "Upload stuck"),
    ("issue_reports.description", "issue_reports", "id", "rich-issue-1",
     "description", "Syllabus upload spins forever."),
    ("flashcards.front", "flashcards", "id", "rich-fc-cs-1", "front",
     "What is a variable?"),
    ("flashcards.back", "flashcards", "id", "rich-fc-cs-1", "back",
     "A named storage location for a value."),
    ("room_summaries.summary", "room_summaries", "room_id",
     "rich-room-study-group", "summary",
     "The group is reviewing recursion before the midterm."),
]

# (label, id_value, column, expected_number)
_NUMERIC_COLUMNS = [
    ("assignments.points_possible", "rich-asg-cs-f25-hw1", "points_possible", 100.0),
    ("assignments.points_earned", "rich-asg-cs-f25-hw1", "points_earned", 88.0),
]


def _raw(db_conn, table: str, id_col: str, id_val: str, column: str):
    row = db_conn.execute(
        f'SELECT "{column}" FROM "{table}" WHERE "{id_col}" = %s', (id_val,)
    ).fetchone()
    assert row is not None, f"seed row {table}.{id_col}={id_val!r} is missing"
    return row[column]


@pytest.mark.parametrize(
    "label,table,id_col,id_val,column,expected",
    _TEXT_COLUMNS,
    ids=[c[0] for c in _TEXT_COLUMNS],
)
def test_text_column_is_ciphertext_at_rest_and_decrypts(
    db_conn, label, table, id_col, id_val, column, expected
):
    raw = _raw(db_conn, table, id_col, id_val, column)
    assert raw is not None, f"{label} is NULL — seed did not populate it"
    assert raw != expected, f"{label} stored as PLAINTEXT — encryption-at-rest regressed"
    assert decrypt_if_present(raw) == expected, f"{label} ciphertext does not round-trip"


@pytest.mark.parametrize(
    "label,id_val,column,expected",
    _NUMERIC_COLUMNS,
    ids=[c[0] for c in _NUMERIC_COLUMNS],
)
def test_numeric_column_is_ciphertext_at_rest_and_decrypts(
    db_conn, label, id_val, column, expected
):
    raw = _raw(db_conn, "assignments", "id", id_val, column)
    assert raw is not None, f"{label} is NULL — seed did not populate it"
    assert str(raw) != str(expected), f"{label} stored as PLAINTEXT — encryption-at-rest regressed"
    assert decrypt_numeric(raw) == expected, f"{label} does not decrypt to the seeded number"


def test_sessions_summary_json_is_ciphertext_at_rest_and_decrypts(db_conn):
    """summary_json needs the JSON pair (encrypt_json/decrypt_json), not the text
    pair — a column that's easy to enumerate with the wrong helper (#398 comment)."""
    raw = _raw(db_conn, "sessions", "id", "rich-sess-cs-recursion", "summary_json")
    assert raw is not None, "sessions.summary_json is NULL — seed did not populate it"
    decoded = decrypt_json(raw)
    assert isinstance(decoded, dict) and "bullets" in decoded
    assert "Discussed base cases" in decoded["bullets"]


def test_quiz_attempts_questions_json_is_ciphertext_and_decrypts(db_conn):
    """#521: quiz_attempts.questions_json needs the JSON pair too."""
    raw = _raw(db_conn, "quiz_attempts", "id", "rich-qa-cs-variables-1", "questions_json")
    assert raw is not None
    assert isinstance(raw, str), "questions_json stored as PLAINTEXT JSONB — encryption regressed"
    decoded = decrypt_json(raw)
    assert decoded[0]["q"] == "What keyword declares a variable in Python?"


def test_quiz_attempts_answers_json_is_ciphertext_and_decrypts(db_conn):
    raw = _raw(db_conn, "quiz_attempts", "id", "rich-qa-cs-variables-1", "answers_json")
    assert isinstance(raw, str)
    assert decrypt_json(raw)[0]["correct"] is True


def test_quiz_context_context_json_is_ciphertext_and_decrypts(db_conn):
    raw = _raw(db_conn, "quiz_context", "id", "rich-qc-cs-variables", "context_json")
    assert isinstance(raw, str)
    decoded = decrypt_json(raw)
    assert decoded["asked"] == 2


def test_study_guides_content_is_ciphertext_and_decrypts(db_conn):
    """#518: study_guides.content needs the JSON pair (encrypt_json/decrypt_json)."""
    raw = _raw(db_conn, "study_guides", "id", "rich-guide-cs-f25-mid", "content")
    assert isinstance(raw, str), "content stored as PLAINTEXT JSONB — encryption regressed"
    decoded = decrypt_json(raw)
    assert decoded["title"] == "Variables, control flow and functions"
    assert decoded["scope_label"] == "Midterm Exam"


def test_study_guides_previous_content_and_answers_are_ciphertext_and_decrypt(db_conn):
    """The seed leaves both NULL (a guide never updated, no check answered), so
    this one writes them through the store, the only writer of the table, and
    reads them back raw. It also runs the once-only answer's compare-and-set
    against the real `updated_at` trigger."""
    import asyncio

    from models.study_guide import CheckAnswer, GuideContent
    from services.study_guides import store

    user, guide_id = "rich-user-active", "rich-guide-cs-f25-mid"
    seeded = asyncio.run(store.aload_guide(user, guide_id))
    rewritten = seeded.content.model_copy(update={"title": "Rewritten for the round trip"})
    saved = asyncio.run(store.asave_content(seeded, rewritten, keep_previous=True))
    answer = CheckAnswer(option_id="b", correct=True)
    assert asyncio.run(store.arecord_answer(saved, "s2-i4", answer)) is True
    # A second click that loaded the guide before the first one wrote.
    assert asyncio.run(store.arecord_answer(saved, "s2-i4", answer)) is False

    previous = _raw(db_conn, "study_guides", "id", guide_id, "previous_content")
    assert isinstance(previous, str), "previous_content stored as PLAINTEXT JSONB"
    assert "recursive traces" not in previous
    # Validated, not compared as a dict: the store keeps fields no dump has
    # (`last_section_number`, `materials_read_at`).
    assert GuideContent.model_validate(decrypt_json(previous)) == seeded.content

    answers = _raw(db_conn, "study_guides", "id", guide_id, "answers")
    assert isinstance(answers, str), "answers stored as PLAINTEXT JSONB"
    assert "option_id" not in answers
    assert decrypt_json(answers) == {"s2-i4": {"option_id": "b", "correct": True}}
    assert asyncio.run(store.aload_guide(user, guide_id)).content == rewritten


def test_documents_concept_notes_uses_json_encryption(db_conn):
    """documents.concept_notes is stored via encrypt_json (a list of concepts)."""
    raw = _raw(db_conn, "documents", "id", "rich-doc-cs-syllabus", "concept_notes")
    assert raw is not None, "documents.concept_notes is NULL — seed did not populate it"
    decoded = decrypt_json(raw)
    assert isinstance(decoded, list) and decoded
    assert any(c.get("name") == "Variables" for c in decoded)
