# Quiz prompt budget — measured

**Measured 2026-08-14** on `gemini-2.5-flash-lite` (the quiz task's model slot,
ADR 0008) via Gemini's `count_tokens` endpoint. Reproduce with:

```sh
cd backend && venv/bin/python -m scripts.bench_quiz_prompt_budget
```

This exists because the #537 audit estimated the quiz's request-path prompt at
"~2–4k in" and explicitly said to verify rather than inherit that number
(F6). Verified: **the estimate was low, and it was low in a place nobody was
looking.**

## Sections

| Section | Tokens | Audit's estimate |
|---|---:|---:|
| System prompt (`agents/quiz.py`) | **1,317** | ~800 |
| Routing message (concrete difficulty) | 124 | — |
| Routing message (adaptive) | 161 | — |
| `read_concepts_for_user` @ 25-row cap | **1,340** | ~250 |
| `read_concepts_for_user` @ 13 rows (seeded graph) | 699 | — |
| `read_misconceptions_for_course` @ 20-row cap | 716 | ~200 |
| `read_recent_quiz_attempts` (5 attempts + digest) | 393 | ~200 |
| Recently-asked block, 15 stems (E6, new) | 290 | — |
| Catalog chunk (typical) | 217 | — |
| RAG chunk | 61 (50 w) → 481 (400 w) | 50–400 w |

## Totals

| Scenario | Tokens |
|---|---:|
| Floor — system + routing, no tools, no grounding | 1,478 |
| **Today**, grounded (k=5 median), 13-concept graph | **3,992** |
| …plus E6's recently-asked block | 4,282 |
| …plus `#553`'s misconceptions once that filter is fixed | 4,998 |
| Worst case — every block, every cap | 6,839 |

## What the measurement changes

1. **The system prompt is the single largest fixed cost** — 1,317 tokens, 65%
   above the estimate, and paid on every generation whether or not anything
   else is present. It is the first thing to look at, and nothing in the audit
   pointed there.
2. **`read_concepts_for_user` is not a rounding error.** At its 25-row cap it
   costs 1,340 tokens — more than five times the estimate, and more than a
   five-chunk RAG block at typical chunk sizes. The audit named COURSE
   MATERIAL "today's dominant variable cost"; that is only true for long
   chunks. For a student with a large graph, the concepts tool rivals it.
3. **The audit's proposed ~4–5k redesign budget is roughly where the prompt
   already is** (3,992 today, 4,282 with E6). The budget is not headroom to
   spend — it is approximately the current bill.
4. **Fixing `#553` adds ~716 tokens**, not zero. Worth knowing before it lands,
   since the misconceptions tool currently returns nothing for everyone and its
   cost is therefore invisible today.

## Caveats — read these before acting on the numbers

- Tool returns are counted as **raw JSON**. The wire adds tool-call/response
  framing per call, so live prompts run somewhat above these figures.
- The per-section split is what this script is for. **`llm_usage.prompt_tokens`
  remains the authority on totals** — it records what was actually sent:

  ```sql
  SELECT feature, task, avg(prompt_tokens), max(prompt_tokens)
  FROM llm_usage WHERE feature = 'quiz' GROUP BY 1, 2;
  ```

- Attribution to sections comes from the F6 dimensions on the `quiz.started`
  event (`blocks`, `k_chunks`, `material_chars`, `recent_asked`,
  `routing_chars`, `adaptive`), which shares a `request_id` with the
  `llm_usage` row for the same generation. Join on that to price a real
  population rather than this synthetic one. `blocks` is the list of section
  names actually assembled, so `misconceptions_requested` (whether the
  misconceptions tool was offered at all) lives inside it rather than as a
  dimension of its own.
  The agent's tools contribute a few more when the model actually calls them
  — `digest_present`/`digest_chars`/`recent_attempts` from
  `read_recent_quiz_attempts`, `misconceptions` from
  `read_misconceptions_for_course` — so treat those as present-when-called,
  not guaranteed, in a rollup.

## If trimming becomes necessary

In measured order of return, not guessed order:

1. The system prompt (1,317 fixed).
2. The concepts tool's 25-row cap — the audit's own redesign proposal already
   suggests a top-12 snapshot, which would roughly halve it.
3. RAG `k`, currently 5 (`routes/quiz.py::_RAG_K`); the audit proposes 4. Worth
   the least of the three at typical chunk sizes, and it is the one block whose
   removal directly costs question quality.
