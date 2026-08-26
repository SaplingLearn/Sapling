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

- The H4 student signals (`services/quiz_signals.py`, #556) each ride their own
  dimension, which is the whole reason they were landed together: the routing
  message gains at most one short sentence from all of them combined, so the
  question "is this worth its tokens?" has to be answered per signal, not for
  the block. They are, with the scope each one actually measures:

  | Dimension | Measures | Scope |
  | --- | --- | --- |
  | `signal_times_studied` | `graph_nodes.times_studied` | this concept |
  | `signal_velocity` | mastery gained per day over 14 days | this concept |
  | `signal_in_flight` | unfinished, un-abandoned attempts | this concept |
  | `signal_flashcards_course_cards` | cards the student has | **this course** |
  | `signal_flashcards_course_reviewed` | of those, how many reviewed at least once | **this course** |
  | `signal_flashcards_course_last_review_days` | days since the most recent card review | **this course** |
  | `signal_tutor_course_sessions_14d` | tutor sessions started in the last 14 days **or still open** | **this course** |
  | `signal_tutor_concept_days_since` | days since a tutor turn touched the concept | this concept |

  The three flashcard dimensions are course-level because `flashcards` has no
  concept link at all. "For this course" means matched by either key the
  writers use: an `offering_id` belonging to any offering of the course
  (imported cards), or a `topic` that CONTAINS the course name — the substring
  rule `Study.tsx` files cards under, and the only key that reaches an
  AI-generated card, since that insert carries no `offering_id`. The offering
  side spans every offering of the abstract course rather than the student's
  enrollments, because that is the keyspace the writers stamp; see the module
  docstring in `services/quiz_signals.py`.

  **Pricing these needs two rules, and neither is the obvious one:**

  - **`NULL` does not uniformly mean "the read could not answer".** For the
    counts (`…_cards`, `…_reviewed`, `…_sessions_14d`, `…_in_flight`) it does:
    a failed query, an unresolvable scope, or a scan that hit its cap. But
    `signal_flashcards_course_last_review_days` is `NULL` after a completely
    successful read whenever no card has ever been reviewed — "never reviewed"
    has no recency, and `0` would claim "reviewed today". Same for
    `signal_tutor_concept_days_since`, where `NULL` means the bounded scan did
    not find the concept. On those two, `NULL` is a fact about the student,
    not a missing read.
  - **A dimension's value does not tell you whether it reached the prompt.**
    `prompt_block` skips falsy counts, so a `0` costs exactly what a `NULL`
    does: nothing. Only non-zero counts render. Two exceptions, both
    deliberate: `signal_times_studied` renders its `0` (never having studied
    the concept is precisely what a generator should know), and
    `signal_tutor_concept_days_since` renders its `0` as the STRONGEST form of
    that signal (tutored on this concept today). So the population to price a
    signal against is "runs where its line rendered" — for most of these
    `dim IS NOT NULL AND dim <> 0`, not `dim IS NOT NULL`.

  The ceiling for the whole block — every signal known and rendered — is the
  `student signals (H4 …)` row the benchmark prints. It is generated by
  `services.quiz_signals.prompt_block` itself, so it cannot drift from the
  sentence the prompt actually carries.

## If trimming becomes necessary

In measured order of return, not guessed order:

1. The system prompt (1,317 fixed).
2. The concepts tool's 25-row cap — the audit's own redesign proposal already
   suggests a top-12 snapshot, which would roughly halve it.
3. RAG `k`, currently 5 (`routes/quiz.py::_RAG_K`); the audit proposes 4. Worth
   the least of the three at typical chunk sizes, and it is the one block whose
   removal directly costs question quality.
