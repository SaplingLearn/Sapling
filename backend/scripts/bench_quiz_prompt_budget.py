"""Measure the quiz generation prompt, section by section (F6).

The audit estimated the quiz's request-path prompt at "~2–4k in" and said,
correctly, to verify it rather than inherit it — `llm_usage.prompt_tokens`
already records the truth per call, and a section-level breakdown is what
turns that number into a decision about what to trim.

This measures the SECTIONS. It counts tokens with Gemini's `count_tokens`
endpoint (no generation, so it is cheap and deterministic) over the real
strings the route and agent assemble:

  * `agents/quiz.py::_SYSTEM_PROMPT` — imported, not copied. A structural
    copy (the approach `bench_quiz_question_cap.py` takes, because it needs
    schema VARIANTS) would measure the wrong string the first time anyone
    edits the prompt, which is exactly the drift this is meant to catch.
  * the routing message, in both concrete and adaptive forms;
  * the tool returns, serialized at their real caps;
  * the COURSE MATERIAL block, measured per chunk across a realistic size
    range, so `k` can be priced rather than guessed;
  * E6's recently-asked block at RECENT_QUESTION_LIMIT stems.

Run from backend/ with GEMINI_API_KEY in .env:

    venv/bin/python -m scripts.bench_quiz_prompt_budget

Offline benchmark: outside the request path, and never imported BY
application code (same rule as scripts/_raw_gemini.py). It reads
application constants; nothing reads it.

`count_tokens` is not reachable through a pydantic-ai agent, so this is one
of the sanctioned raw-`genai.Client` sites (CLAUDE.md). It therefore holds
the same two invariants the seam requires: the model name comes from
`model_name_for("quiz")` — never a literal, or the benchmark prices a tier
the quiz no longer runs on — and the client is built lazily behind a
`model_mode()` gate (#439), so a non-real mode fails loudly instead of
counting tokens against a transport that isn't there.

RESULTS: see the block printed by the run, and the summary recorded in
docs/quiz-prompt-budget.md.
"""

from __future__ import annotations

import json
import statistics
import sys

from dotenv import load_dotenv

load_dotenv()

from google import genai  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from agents._providers import model_mode, model_name_for  # noqa: E402
from agents.quiz import _SYSTEM_PROMPT  # noqa: E402
from config import GEMINI_API_KEY  # noqa: E402
from services.quiz_config import QUIZ_MAX_QUESTIONS  # noqa: E402
from services.quiz_repetition import RECENT_QUESTION_LIMIT  # noqa: E402

# Resolved through the provider config, not hard-coded: the whole point of
# measuring "the quiz's prompt" is that it is measured on the model the quiz
# task actually runs on, and `_DEFAULTS["quiz"]` / SAPLING_MODEL_QUIZ is where
# that lives. A literal here silently prices the wrong tier the first time
# anyone re-slots the task — the same drift the imported `_SYSTEM_PROMPT`
# avoids for the prompt itself.
MODEL = model_name_for("quiz")

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """The raw `count_tokens` client, built lazily behind the #439 gate.

    Nothing below the `agents/_providers.py` seam may construct a
    `google.genai.Client` without a `model_mode()` gate (CLAUDE.md, #439), and
    this script is below it: it needs `count_tokens`, which is not reachable
    through a pydantic-ai agent. So it takes the same shape
    `services/rag_service.py` does — lazy, real-mode only — instead of
    building a live client at import time. In function/cassette mode there is
    no transport to count against, and a keyless run cannot count tokens at
    all; both fail loudly HERE rather than producing numbers nobody should
    trust, or dying later inside `count_tokens` on an opaque auth error.
    """
    global _client
    if model_mode() != "real":
        raise SystemExit(
            f"bench_quiz_prompt_budget: SAPLING_MODEL_MODE={model_mode()!r} — "
            "token counting needs the real Gemini transport. Unset the var "
            "(or set it to 'real') and re-run."
        )
    if not GEMINI_API_KEY:
        # No dummy-key fallback: rag_service needs one because it is imported
        # on the request path and must not explode at import. This is an
        # offline CLI whose only job is calling count_tokens, so a keyless
        # run has nothing to do but fail — and it should say why.
        raise SystemExit(
            "bench_quiz_prompt_budget: GEMINI_API_KEY is not set — "
            "count_tokens is a live API call. Export a real key and re-run."
        )
    if _client is None:
        _client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=genai_types.HttpOptions(timeout=60_000),
        )
    return _client


def count(text: str) -> int:
    """Exact prompt tokens for `text` on the quiz's model tier."""
    if not text:
        return 0
    resp = _get_client().models.count_tokens(model=MODEL, contents=text)
    return int(resp.total_tokens)


# ── Representative section content ──────────────────────────────────────────
#
# Shapes mirror what the route/tools actually emit; only the words are
# synthetic. Token counts are driven by length and structure, not by which
# particular concept names a real student has.

CONCEPT_NAMES = [
    "Recursion", "Dynamic programming", "Greedy algorithms", "Graph traversal",
    "Hash tables", "Binary search trees", "Sorting lower bounds", "Amortized analysis",
    "Union-find", "Shortest paths", "Minimum spanning trees", "Network flow",
    "NP-completeness", "Approximation algorithms", "Randomized algorithms",
    "String matching", "Computational geometry", "Linear programming",
    "Divide and conquer", "Backtracking", "Memoization", "Topological sort",
    "Heaps and priority queues", "Tries", "Bit manipulation",
]


def concepts_block(n: int = 25) -> str:
    """`read_concepts_for_user` return, at its 25-row wrapper cap."""
    return json.dumps([
        {
            "concept_name": name,
            "mastery": round(0.02 * i, 2),
            "last_reviewed_at": "2026-08-01T12:00:00+00:00",
        }
        for i, name in enumerate(CONCEPT_NAMES[:n])
    ])


def misconceptions_block(n: int = 20) -> str:
    """`read_misconceptions_for_course` return, at its 20-row cap."""
    return json.dumps([
        {
            "text": (
                "Students often believe the recursive case runs before the "
                "base case is checked, and expect the stack to unwind eagerly."
            ),
            "related_concept": CONCEPT_NAMES[i % len(CONCEPT_NAMES)],
        }
        for i in range(n)
    ])


def history_block(digest_chars: int = 600) -> str:
    """`read_recent_quiz_attempts` return: 5 attempts plus the digest."""
    return json.dumps({
        "summary": "The student " + ("confuses base and recursive cases. " * (digest_chars // 40)),
        "recent_attempts": [
            {"score": 3, "total": 5, "difficulty": "medium",
             "completed_at": "2026-08-0%dT12:00:00+00:00" % (i + 1),
             "accuracy": 0.6}
            for i in range(5)
        ],
    })


_CHUNK_SENTENCE = (
    "Memoization stores the result of each subproblem so that repeated "
    "calls return in constant time instead of recomputing the recursion."
).split()


def chunk_text(words: int) -> str:
    """A `words`-long stand-in for one retrieved course chunk."""
    reps = -(-words // len(_CHUNK_SENTENCE))  # ceil
    return " ".join((_CHUNK_SENTENCE * reps)[:words])


def recently_asked_block(n: int = RECENT_QUESTION_LIMIT) -> str:
    lines = "\n".join(
        f"- Which of the following best describes the base case in example {i}?"
        for i in range(n)
    )
    return (
        "\n\n[RECENTLY ASKED] This student has already been served the "
        "questions below on this concept. Do NOT repeat them or trivially "
        "reword them — write new questions, on the same concept, that probe "
        "it differently:\n" + lines
    )


def routing_msg(adaptive: bool) -> str:
    n = QUIZ_MAX_QUESTIONS
    if adaptive:
        clause = (
            f"Generate {n} questions in ADAPTIVE MODE: you choose each "
            f"question's difficulty (easy, medium, or hard) from the student's "
            f"mastery and recent accuracy, per the adaptive-mode rules in your "
            f"system prompt."
        )
    else:
        clause = f"Generate {n} medium questions for the student."
    return (
        f"{clause} The target concept is 'Recursion' "
        f"(concept_node_id=00000000-0000-0000-0000-000000000000). Follow the "
        f"workflow in your system prompt; pass "
        f"concept_node_id='00000000-0000-0000-0000-000000000000' to "
        f"read_recent_quiz_attempts."
    )


def main() -> int:
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set — this benchmark needs a live key.")
        return 2

    print(f"Quiz prompt budget — {MODEL}\n" + "=" * 62)

    fixed = [
        ("system prompt (agents/quiz.py)", count(_SYSTEM_PROMPT)),
        ("routing message (concrete difficulty)", count(routing_msg(False))),
        ("routing message (adaptive)", count(routing_msg(True))),
    ]
    concepts_cap = count(concepts_block(25))
    # 13 = the rich seed's node count for the primary student, and a plausible
    # mid-semester graph. The 25-row cap is what a heavy user hits, not what a
    # median one costs — reporting only the cap would overstate the typical
    # prompt as badly as the estimate this replaces understated it.
    concepts_typical = count(concepts_block(13))
    misconceptions_cap = count(misconceptions_block(20))
    history_typical = count(history_block())
    tools = [
        ("read_concepts_for_user (25 rows, cap)", concepts_cap),
        ("read_concepts_for_user (13 rows, seeded graph)", concepts_typical),
        ("read_misconceptions_for_course (20 rows, cap)", misconceptions_cap),
        ("read_recent_quiz_attempts (5 + digest)", history_typical),
    ]
    variable = [
        (f"recently asked ({RECENT_QUESTION_LIMIT} stems, E6)",
         count(recently_asked_block())),
        ("catalog chunk (typical)", count(chunk_text(180))),
    ]

    per_chunk = []
    print("\nPER-CHUNK COST (COURSE MATERIAL, the dominant variable)")
    for words in (50, 150, 250, 400):
        t = count(chunk_text(words))
        per_chunk.append(t)
        print(f"  {words:>4} words -> {t:>5} tokens")

    for label, rows in (
        ("\nFIXED", fixed), ("\nTOOL RETURNS (at cap)", tools),
        ("\nVARIABLE BLOCKS", variable),
    ):
        print(label)
        for name, tokens in rows:
            print(f"  {name:<46} {tokens:>6}")

    sys_t = fixed[0][1]
    routing_t = max(fixed[1][1], fixed[2][1])
    recent_t = variable[0][1]
    catalog_t = variable[1][1]
    rag_median = int(statistics.median(per_chunk)) * 5
    rag_max = 5 * max(per_chunk)

    floor = sys_t + routing_t
    # Today: the misconceptions tool returns zero rows for everyone (#553),
    # so the honest "today" figure excludes it — and its 716-token cap is
    # what fixing #553 will ADD, which is worth knowing before it lands.
    today = floor + concepts_typical + history_typical + catalog_t + rag_median
    with_e6 = today + recent_t
    worst = (
        floor + concepts_cap + misconceptions_cap + history_typical
        + recent_t + catalog_t + rag_max
    )

    print("\n" + "=" * 62)
    print(f"  floor (system + routing, no tools, no grounding)   {floor:>6}")
    print(f"  RAG k=5 @ {min(per_chunk)}-{max(per_chunk)} tok/chunk"
          f"{'':<19}{5 * min(per_chunk):>6}-{rag_max}")
    print("-" * 62)
    print(f"  TODAY, grounded, 13-concept graph                 {today:>6}")
    print(f"  ...+ E6's recently-asked block                    {with_e6:>6}")
    print(f"  ...+ #553's misconceptions once fixed             "
          f"{with_e6 + misconceptions_cap:>6}")
    print(f"  WORST CASE (every block, every cap)               {worst:>6}")
    print("\nCompare: the audit estimated ~2-4k in (docs/audits/"
          "student-data-inventory.md §5.4) with the system prompt at ~800 and "
          f"the concepts tool at ~250; measured, they are {sys_t} and "
          f"{concepts_cap} at cap.")
    print("NB: tool returns are counted as raw JSON. The wire adds "
          "tool-call/response framing per call, so live numbers run above "
          "these — which is why llm_usage, not this script, is the "
          "authority. This prices the SECTIONS.")
    print("Verify against reality with:")
    print("  SELECT feature, task, avg(prompt_tokens), max(prompt_tokens)")
    print("  FROM llm_usage WHERE feature='quiz' GROUP BY 1,2;")
    return 0


if __name__ == "__main__":
    sys.exit(main())
