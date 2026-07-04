"""Quiz-grounding benchmark (two layers).

Layer 1: retrieval precision/recall@k for each fixture concept.
Layer 2 (Task 4): judged grounding/scope/correctness of generated quizzes.

Run from backend/ (reads .env.staging):
    python scripts/benchmark_quiz.py --chunks-only   # Layer 1 only
    python scripts/benchmark_quiz.py                 # both layers
"""
import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 guard

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(BASE / ".env.staging")

from services.rag_service import retrieve_chunks  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "quiz_grounding"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
BU_CODE = MANIFEST["bu_course_code"]


def score_retrieval(concept: dict, chunks: list[dict]) -> dict:
    """recall = fraction of expected substrings present in any returned chunk;
    precision = fraction of returned chunks that contain any expected substring."""
    expected = concept.get("relevant_chunk_substrings", [])
    texts = [c.get("chunk_text", "") for c in chunks]
    hits = sum(1 for sub in expected if any(sub.lower() in t.lower() for t in texts))
    relevant_returned = sum(1 for t in texts if any(sub.lower() in t.lower() for sub in expected))
    recall = hits / len(expected) if expected else 0.0
    precision = relevant_returned / len(texts) if texts else 0.0
    return {"recall": recall, "precision": precision,
            "hits": hits, "expected": len(expected)}


def run_layer1() -> list[dict]:
    print("=" * 60)
    print("LAYER 1 — RETRIEVAL PRECISION/RECALL@k")
    print("=" * 60)
    results = []
    for concept in MANIFEST["concepts"]:
        name = concept["concept_name"]
        chunks = retrieve_chunks(name, course_id=BU_CODE, k=5)
        s = score_retrieval(concept, chunks)
        results.append({"concept": name, **s})
        print(f"  [{concept['kind']:11}] {name:28} "
              f"recall={s['recall']:.2f} precision={s['precision']:.2f}")
    mean_r = sum(r["recall"] for r in results) / len(results)
    mean_p = sum(r["precision"] for r in results) / len(results)
    print(f"\n  Mean recall={mean_r:.2f}  mean precision={mean_p:.2f}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-only", action="store_true")
    parser.add_argument("--runs-per-concept", type=int, default=1)  # used by Layer 2
    args = parser.parse_args()
    run_layer1()
    if args.chunks_only:
        print("\n(Layer 2 skipped — remove --chunks-only to run it)")
        return
    # Layer 2 wired in Task 4.


if __name__ == "__main__":
    main()
