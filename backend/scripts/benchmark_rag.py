"""
RAG pipeline benchmark — tests catalog chunk retrieval and LLM response accuracy.

Run from backend/:
    python scripts/benchmark_rag.py              # chunk + LLM tests
    python scripts/benchmark_rag.py --chunks-only  # skip LLM, fast
    python scripts/benchmark_rag.py --course CAS CS 330  # one course only
"""

import argparse
import sys
import textwrap
from pathlib import Path

# Windows consoles default to cp1252, which can't encode the report's bar chars
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Allow imports from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env.staging")  # use staging DB

from routes.learn import _get_catalog_chunk  # noqa: E402
from services.gemini_service import call_gemini  # noqa: E402


# ── Ground-truth test cases ────────────────────────────────────────────────────

CASES = [
    # ── CAS CS 330 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS CS 330",
        "question": "What are the prerequisites for this course?",
        "category": "prerequisites",
        "required_keywords": ["CS 112", "CS 131"],
        "forbidden_patterns": ["don't have", "cannot provide", "no information"],
    },
    {
        "course_code": "CAS CS 330",
        "question": "How many credits is this course?",
        "category": "credits",
        "required_keywords": ["4"],
        "forbidden_patterns": ["don't know", "not sure"],
    },
    {
        "course_code": "CAS CS 330",
        "question": "What topics does this course cover?",
        "category": "description",
        "required_keywords": ["algorithm", "NP"],
        "forbidden_patterns": [],
    },
    {
        "course_code": "CAS CS 330",
        "question": "Does this course involve dynamic programming?",
        "category": "description",
        "required_keywords": ["dynamic programming"],
        "forbidden_patterns": ["don't have", "no information"],
    },

    # ── CAS CS 112 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS CS 112",
        "question": "What are the prerequisites for this course?",
        "category": "prerequisites",
        "required_keywords": ["CS 111", "111"],
        "forbidden_patterns": ["don't have", "cannot provide"],
    },
    {
        "course_code": "CAS CS 112",
        "question": "How many credits does CAS CS 112 carry?",
        "category": "credits",
        "required_keywords": ["4"],
        "forbidden_patterns": [],
    },

    # ── CAS MA 225 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS MA 225",
        "question": "What math courses are required before taking this course?",
        "category": "prerequisites",
        "required_keywords": ["MA 124", "MA 129"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "CAS MA 225",
        "question": "What topics are covered in this course? List a few.",
        "category": "description",
        "required_keywords": ["partial derivatives", "gradient"],
        "forbidden_patterns": [],
    },

    # ── ENG EK 103 ─────────────────────────────────────────────────────────────
    {
        "course_code": "ENG EK 103",
        "question": "What are the prerequisites for this course?",
        "category": "prerequisites",
        # LLM formats the code as either "EK 122" or "ENGEK122" — "122" matches both
        "required_keywords": ["122"],
        "forbidden_patterns": ["don't have", "cannot provide"],
    },
    {
        "course_code": "ENG EK 103",
        "question": "How many credits is this course?",
        "category": "credits",
        "required_keywords": ["3"],
        "forbidden_patterns": [],
    },
    {
        "course_code": "ENG EK 103",
        "question": "What real-world applications does this linear algebra course mention?",
        "category": "description",
        "required_keywords": ["PageRank", "cryptography"],
        "forbidden_patterns": [],
    },

    # ── CDS DS 110 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CDS DS 110",
        "question": "Do I need prior Python experience for this course?",
        "category": "description",
        "required_keywords": ["not required", "no"],
        "forbidden_patterns": ["don't know", "cannot say"],
    },
    {
        "course_code": "CDS DS 110",
        "question": "What libraries are used in this course?",
        "category": "description",
        "required_keywords": ["pandas", "numpy"],
        "forbidden_patterns": [],
    },

    # ── COM CM 501 ─────────────────────────────────────────────────────────────
    {
        "course_code": "COM CM 501",
        "question": "What are the prerequisites for COM CM 501?",
        "category": "prerequisites",
        "required_keywords": ["sophomore"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "COM CM 501",
        "question": "What software tools does this design course use?",
        "category": "description",
        "required_keywords": ["Illustrator", "Photoshop", "InDesign"],
        "forbidden_patterns": [],
    },

    # ── CAS CS 111 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS CS 111",
        "question": "What are the prerequisites for CAS CS 111?",
        "category": "prerequisites",
        "required_keywords": [],
        "forbidden_patterns": ["CS 112", "CS 330"],  # must not invent prereqs
        "note": "No prerequisites listed — should say none or not mention any.",
    },
    {
        "course_code": "CAS CS 111",
        "question": "What programming language is used in this course?",
        "category": "description",
        "required_keywords": ["Python"],
        "forbidden_patterns": [],
    },

    # ── CAS CS 132 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS CS 132",
        "question": "What are the prerequisites for CAS CS 132?",
        "category": "prerequisites",
        "required_keywords": ["CS 111", "MA 123"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "CAS CS 132",
        "question": "How many credits is CAS CS 132?",
        "category": "credits",
        "required_keywords": ["4"],
        "forbidden_patterns": [],
    },

    # ── CAS CS 460 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS CS 460",
        "question": "What is the prerequisite for the database systems course?",
        "category": "prerequisites",
        "required_keywords": ["CS 112", "112"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "CAS CS 460",
        "question": "Does this course cover SQL?",
        "category": "description",
        "required_keywords": ["SQL"],
        "forbidden_patterns": ["don't have", "no information"],
    },

    # ── CAS MA 123 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS MA 123",
        "question": "What are the prerequisites for Calculus I?",
        "category": "prerequisites",
        "required_keywords": [],
        "forbidden_patterns": ["MA 124", "MA 225"],  # must not invent prereqs
        "note": "No prerequisites listed — should not mention downstream courses.",
    },
    {
        "course_code": "CAS MA 123",
        "question": "What topics does Calculus I cover?",
        "category": "description",
        "required_keywords": ["derivative", "integral"],
        "forbidden_patterns": [],
    },

    # ── CAS PY 211 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS PY 211",
        "question": "What are the prerequisites for General Physics 1?",
        "category": "prerequisites",
        "required_keywords": ["MA 123"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "CAS PY 211",
        "question": "Is this physics course calculus-based?",
        "category": "description",
        "required_keywords": ["calculus"],
        "forbidden_patterns": ["don't have", "no information"],
    },

    # ── CAS CH 101 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS CH 101",
        "question": "What background do I need for General Chemistry 1?",
        "category": "prerequisites",
        "required_keywords": ["algebra", "high school"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "CAS CH 101",
        "question": "Does this course have a lab component?",
        "category": "description",
        "required_keywords": ["lab"],
        "forbidden_patterns": ["no lab", "don't have"],
    },

    # ── CAS EC 101 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS EC 101",
        "question": "What topics does Introductory Microeconomics cover?",
        "category": "description",
        "required_keywords": ["supply", "demand"],
        "forbidden_patterns": [],
    },
    {
        "course_code": "CAS EC 101",
        "question": "How many credits is CAS EC 101?",
        "category": "credits",
        "required_keywords": ["4"],
        "forbidden_patterns": [],
    },

    # ── CAS WR 120 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS WR 120",
        "question": "What are the prerequisites for the First-Year Writing Seminar?",
        "category": "prerequisites",
        "required_keywords": ["WR 112"],
        "forbidden_patterns": ["don't have", "no information"],
    },

    # ── CDS DS 210 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CDS DS 210",
        "question": "What programming language is introduced in CDS DS 210?",
        "category": "description",
        "required_keywords": ["Rust"],
        "forbidden_patterns": [],
    },
    {
        "course_code": "CDS DS 210",
        "question": "What course does DS 210 build on?",
        "category": "description",
        "required_keywords": ["DS 110"],
        "forbidden_patterns": [],
    },

    # ── ENG EC 401 ─────────────────────────────────────────────────────────────
    {
        "course_code": "ENG EC 401",
        "question": "What are the prerequisites for Signals and Systems?",
        "category": "prerequisites",
        "required_keywords": ["MA 226", "EK 307"],
        "forbidden_patterns": ["don't have", "no information"],
    },
    {
        "course_code": "ENG EC 401",
        "question": "Does ENG EC 401 include a lab?",
        "category": "description",
        "required_keywords": ["lab"],
        "forbidden_patterns": ["no lab", "don't have"],
    },

    # ── CAS BI 108 ─────────────────────────────────────────────────────────────
    {
        "course_code": "CAS BI 108",
        "question": "What prior knowledge is assumed for Biology 2?",
        "category": "prerequisites",
        "required_keywords": ["high school biology"],
        "forbidden_patterns": ["don't have", "no information"],
    },

    # ── Negative: questions the catalog cannot answer ──────────────────────────
    {
        "course_code": "CAS CS 330",
        "question": "What is the homework policy for this course?",
        "category": "negative",
        "required_keywords": [],
        "forbidden_patterns": ["homework policy is", "assignments are due"],
        "note": "Catalog has no homework policy — tutor should admit it doesn't know.",
    },
    {
        "course_code": "CAS MA 123",
        "question": "What is the grading breakdown for Calculus I?",
        "category": "negative",
        "required_keywords": [],
        "forbidden_patterns": ["exam is worth", "quiz is worth", "grading breakdown is"],
        "note": "Catalog has no grading info — should not hallucinate percentages.",
    },
    {
        "course_code": "CAS CS 111",
        "question": "What time does this course meet?",
        "category": "negative",
        "required_keywords": [],
        "forbidden_patterns": ["meets at", "class is at", "monday", "tuesday", "wednesday"],
        "note": "Catalog has no schedule times — should not hallucinate.",
    },
]


# ── Scoring helpers ────────────────────────────────────────────────────────────

def score_response(response: str, required_keywords: list[str], forbidden_patterns: list[str]) -> dict:
    resp_lower = response.lower()

    keyword_hits = [kw for kw in required_keywords if kw.lower() in resp_lower]
    forbidden_hits = [fp for fp in forbidden_patterns if fp.lower() in resp_lower]

    keyword_score = len(keyword_hits) / len(required_keywords) if required_keywords else 1.0
    forbidden_penalty = 1 if forbidden_hits else 0

    passed = keyword_score == 1.0 and forbidden_penalty == 0

    return {
        "passed": passed,
        "keyword_score": keyword_score,
        "keyword_hits": keyword_hits,
        "missing_keywords": [kw for kw in required_keywords if kw not in keyword_hits],
        "forbidden_hits": forbidden_hits,
    }


def _llm_prompt(course_code: str, catalog_text: str, question: str) -> str:
    return f"""You are a helpful university tutor. A student enrolled in {course_code} is asking:

COURSE CATALOG INFO (official BU course data):

{catalog_text}

STUDENT QUESTION:
{question}

Answer concisely based on the catalog data above."""


# ── Chunk-layer test (no LLM) ─────────────────────────────────────────────────

def run_chunk_tests(cases: list[dict]) -> dict:
    print("\n" + "=" * 60)
    print("LAYER 1 — CHUNK RETRIEVAL TESTS")
    print("=" * 60)

    results = {"passed": 0, "failed": 0, "by_course": {}}

    tested_codes = {}
    for case in cases:
        code = case["course_code"]
        if code in tested_codes:
            continue
        tested_codes[code] = True

        chunk = _get_catalog_chunk(code)
        passed = bool(chunk and len(chunk) > 50)
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {code:20s}  {len(chunk):>5} chars")

        results["by_course"][code] = passed
        if passed:
            results["passed"] += 1
        else:
            results["failed"] += 1

    total = results["passed"] + results["failed"]
    print(f"\n  Chunk retrieval: {results['passed']}/{total} courses returned data")
    return results


# ── LLM-layer test ────────────────────────────────────────────────────────────

def run_llm_tests(cases: list[dict], filter_course: str | None = None) -> dict:
    print("\n" + "=" * 60)
    print("LAYER 2 — END-TO-END LLM RESPONSE TESTS")
    print("=" * 60)

    by_category: dict[str, list[bool]] = {}
    all_results = []

    for i, case in enumerate(cases, 1):
        code = case["course_code"]
        if filter_course and code != filter_course:
            continue

        q = case["question"]
        category = case["category"]

        # Get the catalog chunk (what the real pipeline injects)
        catalog_text = _get_catalog_chunk(code)
        if not catalog_text:
            print(f"\n  [{i:02d}] SKIP — no chunk for {code}")
            continue

        # Call LLM with the same context the real pipeline uses
        prompt = _llm_prompt(code, catalog_text, q)
        try:
            response = call_gemini(prompt)
        except Exception as e:
            print(f"\n  [{i:02d}] ERROR — LLM call failed: {e}")
            continue

        result = score_response(response, case["required_keywords"], case["forbidden_patterns"])
        status = "PASS" if result["passed"] else "FAIL"

        # Track by category
        by_category.setdefault(category, []).append(result["passed"])
        all_results.append(result["passed"])

        print(f"\n  [{i:02d}] [{status}] [{category.upper():12s}] {code} — {q[:60]}")
        if result["missing_keywords"]:
            print(f"         Missing keywords : {result['missing_keywords']}")
        if result["forbidden_hits"]:
            print(f"         Forbidden hits   : {result['forbidden_hits']}")
        if not result["passed"]:
            print(f"         Response preview : {textwrap.shorten(response, 120)}")

    return {"all": all_results, "by_category": by_category}


# ── Accuracy report ───────────────────────────────────────────────────────────

def print_accuracy_report(llm_results: dict) -> None:
    print("\n" + "=" * 60)
    print("ACCURACY REPORT")
    print("=" * 60)

    by_cat = llm_results["by_category"]
    all_passed = llm_results["all"]

    # Per-category
    rows = []
    for cat, outcomes in sorted(by_cat.items()):
        passed = sum(outcomes)
        total = len(outcomes)
        pct = 100 * passed / total if total else 0
        rows.append((cat, passed, total, pct))

    col_w = max(len(r[0]) for r in rows) + 2 if rows else 15
    print(f"\n  {'Category':{col_w}} {'Pass':>5}  {'Total':>6}  {'Accuracy':>9}")
    print(f"  {'-'*col_w} {'-----':>5}  {'------':>6}  {'---------':>9}")
    for cat, passed, total, pct in rows:
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        print(f"  {cat:{col_w}} {passed:>5}  {total:>6}     {pct:>5.1f}%  {bar}")

    # Overall
    overall = 100 * sum(all_passed) / len(all_passed) if all_passed else 0
    print(f"\n  Overall: {sum(all_passed)}/{len(all_passed)} tests passed — {overall:.1f}% accuracy")

    # Threshold interpretation
    if overall >= 90:
        verdict = "EXCELLENT — RAG pipeline is working well."
    elif overall >= 75:
        verdict = "GOOD — minor gaps, check failed cases above."
    elif overall >= 50:
        verdict = "NEEDS WORK — significant retrieval or LLM issues."
    else:
        verdict = "BROKEN — catalog not being injected correctly."
    print(f"  Verdict: {verdict}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-only", action="store_true", help="Skip LLM tests")
    parser.add_argument("--course", type=str, default=None, help="Filter to one course code")
    args = parser.parse_args()

    filter_course = args.course

    cases = CASES
    if filter_course:
        cases = [c for c in cases if c["course_code"] == filter_course]
        if not cases:
            print(f"No test cases for course: {filter_course}")
            sys.exit(1)

    print(f"\nRAG Benchmark — {len(cases)} test cases")
    if filter_course:
        print(f"Filtered to: {filter_course}")

    run_chunk_tests(cases)

    if not args.chunks_only:
        llm_results = run_llm_tests(cases, filter_course=filter_course)
        print_accuracy_report(llm_results)
    else:
        print("\n(LLM tests skipped — pass without --chunks-only to run full benchmark)")


if __name__ == "__main__":
    main()
