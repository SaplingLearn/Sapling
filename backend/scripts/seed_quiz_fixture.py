"""Seed the quiz-grounding fixture into a staging TEST course.

Idempotent: upserts course_chunks by content hash and reuses a fixed
course/offering/concept-node id set. Run from backend/:
    python scripts/seed_quiz_fixture.py
Reads .env.staging.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
# override=True so .env.staging wins over any Supabase creds already exported
# in the caller's shell — otherwise the seed can silently hit the wrong project.
load_dotenv(BASE / ".env.staging", override=True)
sys.path.insert(0, str(BASE))

from db.connection import table                       # noqa: E402
from services.chunker import chunk_document           # noqa: E402
from services.rag_service import index_document_chunks  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "quiz_grounding"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
BU_CODE = MANIFEST["bu_course_code"]
DOC_ID = "quizfix-doc-0001"
UPLOADER = "quizfix-user-0001"

# Fixed fixture id for the abstract `courses` catalog row. `id` is TEXT (no
# UUID format required — see 0020_academics_split.sql), so a readable
# constant is fine. benchmark_quiz.py's Layer 2 passes this as `course_id`
# to `_quiz_via_agent` so `_resolve_bu_code` (routes/quiz.py) can map it to
# `BU_CODE` and actually exercise the production grounding path instead of
# generating an ungrounded quiz.
FIXTURE_COURSE_ID = "quizfix-course-0001"


def seed_fixture_course() -> None:
    """Idempotently upsert the abstract `courses` row the fixture resolves
    against. Only `course_code`/`course_name` are populated — `school_id` is
    nullable and everything else the schema requires is NOT NULL-defaulted
    or nullable (see 0020_academics_split.sql)."""
    table("courses").upsert({
        "id": FIXTURE_COURSE_ID,
        "course_code": BU_CODE,
        "course_name": "Quiz Grounding Fixture Course",
    })
    print(f"Upserted courses row id={FIXTURE_COURSE_ID} course_code={BU_CODE}.")


def main() -> None:
    seed_fixture_course()
    # Chunk each doc independently and concatenate the chunk lists — joining
    # the files first would let one chunk straddle a file boundary (tail of
    # one concept + head of the next), blurring per-concept retrieval.
    chunks: list[str] = []
    for p in sorted((FIX / "docs").glob("*")):
        chunks.extend(chunk_document(p.read_text(encoding="utf-8")))
    count = index_document_chunks(BU_CODE, DOC_ID, UPLOADER, chunks)
    print(f"Seeded {count} chunks for {BU_CODE} (doc {DOC_ID}).")


if __name__ == "__main__":
    main()
