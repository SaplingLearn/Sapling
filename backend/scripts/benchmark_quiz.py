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
# override=True so .env.staging wins over any Supabase creds already exported
# in the caller's shell — otherwise the benchmark can hit the wrong project.
load_dotenv(BASE / ".env.staging", override=True)

from services.rag_service import retrieve_chunks  # noqa: E402

import asyncio  # noqa: E402
from _raw_gemini import call_gemini_json  # noqa: E402  (benchmark-only helper, ADR 0024)
from routes.quiz import _quiz_via_agent  # noqa: E402
from seed_quiz_fixture import FIXTURE_COURSE_ID, seed_fixture_course  # noqa: E402

# Judge uses a DIFFERENT (stronger) model than the quiz generator to avoid
# self-preference bias. gemini-2.5-pro judges; the quiz agent runs on
# model_for("quiz") (gemini-2.5-flash-lite by default — see
# agents/_providers.py). call_gemini_json accepts a `model` override, so the
# two are guaranteed to differ; document the exact judge model in the run
# output.
JUDGE_MODEL = "gemini-2.5-pro"

FIX = Path(__file__).parent / "fixtures" / "quiz_grounding"
MANIFEST = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
BU_CODE = MANIFEST["bu_course_code"]


def score_retrieval(concept: dict, chunks: list[dict]) -> dict:
    """recall = fraction of expected substrings present in any returned chunk;
    precision = fraction of returned chunks that contain any expected substring."""
    expected = concept.get("relevant_chunk_substrings", [])
    texts = [c.get("chunk_text", "") for c in chunks]
    hits = sum(1 for sub in expected if any(sub in t for t in texts))
    relevant_returned = sum(1 for t in texts if any(sub in t for sub in expected))
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


def majority_vote(votes: list[dict], key: str) -> bool:
    trues = sum(1 for v in votes if v.get(key))
    return trues > len(votes) / 2


_JUDGE_PROMPT = (
    "You are grading ONE quiz question against the course material below.\n"
    "Return strict JSON: {{\"grounded\": bool, \"on_scope\": bool, "
    "\"answer_correct\": bool, \"evidence\": string}}.\n"
    "- grounded: true ONLY if the question's content is supported by the "
    "material. Put the exact supporting quote in `evidence`, or set evidence "
    "to \"NOT IN MATERIAL\" and grounded=false.\n"
    "- on_scope: false if the question tests a topic the course clearly does "
    "not cover (off-syllabus). Foundational, on-topic content counts as "
    "on_scope=true even if not verbatim in the material.\n"
    "- answer_correct: true only if the marked correct_answer is actually "
    "correct for the question.\n\n"
    "COURSE MATERIAL:\n{material}\n\n"
    "QUESTION: {question}\nOPTIONS: {options}\nMARKED CORRECT: {correct}\n"
)


def judge_question(question: dict, material: str, n_votes: int, model: str) -> dict:
    votes = []
    # Real wire questions (routes/quiz.py::_agent_question_to_wire) carry no
    # top-level correct_answer/answer key; correctness lives per-option as
    # options[i]["correct"] with the option text in options[i]["text"]. Fall
    # back to the legacy top-level keys for any non-wire-format callers.
    correct = next(
        (o.get("text", "") for o in question.get("options", [])
         if isinstance(o, dict) and o.get("correct")),
        question.get("correct_answer", question.get("answer", "")),
    )
    prompt = _JUDGE_PROMPT.format(
        material=material[:8000],
        question=question["question"],
        options=question.get("options", question.get("choices", [])),
        correct=correct,
    )
    for _ in range(n_votes):
        try:
            v = call_gemini_json(prompt, model=model)
        except Exception:
            v = {"grounded": False, "on_scope": True, "answer_correct": False,
                 "evidence": "JUDGE ERROR"}
        votes.append(v)
    return {
        "grounded": majority_vote(votes, "grounded"),
        "on_scope": majority_vote(votes, "on_scope"),
        "answer_correct": majority_vote(votes, "answer_correct"),
        "evidence": votes[0].get("evidence", ""),
    }


def aggregate(verdicts: list[dict]) -> dict:
    n = len(verdicts) or 1
    return {
        "grounded_ratio": sum(1 for v in verdicts if v["grounded"]) / n,
        "off_scope_count": sum(1 for v in verdicts if not v["on_scope"]),
        "correctness_rate": sum(1 for v in verdicts if v["answer_correct"]) / n,
    }


async def _generate_quiz_for_async(concept_name: str) -> list[dict]:
    """Drive the real quiz agent against staging for a fixture concept.

    Uses fixed fixture ids; the agent's history/mastery tools tolerate an
    unseeded node (they return empty). `course_id=FIXTURE_COURSE_ID` is the
    fixture `courses` row seeded by `seed_quiz_fixture.py` — this is what
    lets `_resolve_bu_code`/`_course_material_block` in routes/quiz.py
    resolve to `BU_CODE` and actually inject the seeded course material,
    so this exercises the real production grounding path rather than
    generating an ungrounded quiz.
    """
    # `.questions`: _quiz_via_agent returns a GeneratedQuiz (#555) so the
    # exam-proximity value it resolved can reach the attempt row. This bench
    # only wants the questions.
    generated = await _quiz_via_agent(
        user_id="quizfix-user-0001",
        course_id=FIXTURE_COURSE_ID,
        concept_node_id="quizfix-node-0001",
        concept_name=concept_name,
        num_questions=4,
        difficulty="medium",
        use_shared_context=False,
        request_id="quizfix-bench",
    )
    return generated.questions


def generate_quiz_for(concept_name: str) -> list[dict]:
    """Sync wrapper for one-off/interactive use (e.g. a REPL check).

    main()'s Layer 2 loop calls `_generate_quiz_for_async` directly under
    one shared event loop instead of this wrapper — calling `asyncio.run`
    once per concept here breaks on the 2nd+ call ("RuntimeError: Event
    loop is closed"), because the Gemini SDK's async http client is a
    persistent object bound to the first loop asyncio.run() creates and
    tears down.
    """
    return asyncio.run(_generate_quiz_for_async(concept_name))


async def _run_layer2(args: argparse.Namespace) -> None:
    """Runs entirely inside one event loop — see `generate_quiz_for`'s
    docstring for why per-concept `asyncio.run()` calls break on the 2nd+
    concept (the Gemini SDK's async http client is bound to the loop that
    created it).

    Each concept's generation is isolated in a try/except: a generation
    failure (e.g. a provider-side structured-output rejection) is reported
    as a FAIL for that concept with the error surfaced, rather than
    crashing the whole Layer 2 run and losing every other concept's
    result.
    """
    material = "\n\n".join(
        p.read_text(encoding="utf-8") for p in sorted((FIX / "docs").glob("*"))
    )
    print("\n" + "=" * 60)
    print(f"LAYER 2 — QUIZ GROUNDING/SCOPE/CORRECTNESS (judge={JUDGE_MODEL})")
    print("=" * 60)
    for concept in MANIFEST["concepts"]:
        name = concept["concept_name"]
        all_verdicts = []
        gen_errors: list[str] = []
        for _ in range(args.runs_per_concept):
            try:
                questions = await _generate_quiz_for_async(name)
            except Exception as e:
                gen_errors.append(f"{type(e).__name__}: {e}")
                continue
            for q in questions:
                all_verdicts.append(judge_question(q, material, n_votes=3, model=JUDGE_MODEL))
        if not all_verdicts:
            print(f"  [FAIL] {name:28} quiz generation failed for all "
                  f"{args.runs_per_concept} run(s) — {gen_errors[0][:160]}")
            continue
        a = aggregate(all_verdicts)
        gate = "PASS" if (a["grounded_ratio"] >= 0.6 and a["off_scope_count"] == 0
                          and a["correctness_rate"] >= 0.95) else "FAIL"
        note = f" ({len(gen_errors)} generation error(s))" if gen_errors else ""
        print(f"  [{gate}] {name:28} grounded={a['grounded_ratio']:.2f} "
              f"off_scope={a['off_scope_count']} correct={a['correctness_rate']:.2f}{note}")


def calibration_agreement(judge: list[dict], gold: list[dict]) -> dict:
    """Fraction of items where judge verdict matches the human label, per dimension."""
    n = len(gold) or 1
    dims = ["grounded", "on_scope", "answer_correct"]
    return {d: sum(1 for j, g in zip(judge, gold) if j[d] == g[d]) / n for d in dims}


def run_calibrate() -> None:
    gold = json.loads((FIX / "gold_labels.json").read_text(encoding="utf-8"))["labels"]
    if not gold:
        print("gold_labels.json is empty — label ~20 questions first (see README).")
        return
    material = "\n\n".join(
        p.read_text(encoding="utf-8") for p in sorted((FIX / "docs").glob("*"))
    )
    judge = [judge_question(item["question_obj"], material, n_votes=3, model=JUDGE_MODEL)
             for item in gold]
    human = [{k: item[k] for k in ("grounded", "on_scope", "answer_correct")} for item in gold]
    agree = calibration_agreement(judge, human)
    print(f"Judge agreement vs human ({len(gold)} labels): {agree}")
    for d, v in agree.items():
        flag = "OK" if v >= 0.8 else "LOW — judge unreliable on this dimension"
        print(f"  {d}: {v:.2f}  [{flag}]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-only", action="store_true")
    parser.add_argument("--runs-per-concept", type=int, default=1)  # used by Layer 2
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()
    if args.calibrate:
        run_calibrate()
        return
    run_layer1()
    if args.chunks_only:
        print("\n(Layer 2 skipped — remove --chunks-only to run it)")
        return

    # Fixture `courses` row must exist for grounding to resolve — idempotent.
    seed_fixture_course()

    # ---- Layer 2 ----
    asyncio.run(_run_layer2(args))


if __name__ == "__main__":
    main()
