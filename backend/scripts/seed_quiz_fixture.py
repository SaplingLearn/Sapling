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
load_dotenv(BASE / ".env.staging")
sys.path.insert(0, str(BASE))

from services.chunker import chunk_document           # noqa: E402
from services.rag_service import index_document_chunks  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "quiz_grounding"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
BU_CODE = MANIFEST["bu_course_code"]
DOC_ID = "quizfix-doc-0001"
UPLOADER = "quizfix-user-0001"


def main() -> None:
    texts = []
    for p in sorted((FIX / "docs").glob("*")):
        texts.append(p.read_text(encoding="utf-8"))
    full_text = "\n\n".join(texts)
    chunks = chunk_document(full_text)
    count = index_document_chunks(BU_CODE, DOC_ID, UPLOADER, chunks)
    print(f"Seeded {count} chunks for {BU_CODE} (doc {DOC_ID}).")


if __name__ == "__main__":
    main()
