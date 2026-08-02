# 0023: Graph-grounded tutor — hybrid seed block + read tools, and the TutorRetrieval seam

- Status: accepted
- Date: 2026-07-30
- Relates to: #149 (graph-grounded tutoring); supersedes ADR 0021 decision 4;
  extends 0015 (chat-tutor agent), 0004 (graph tool surface), 0021 (eval harness)

## Context

The agent chat path (`routes.learn._prepare_chat_run`) inlined NO knowledge-graph
context: the tutor knew the student's graph only if it happened to call
`read_user_progress` (aggregate counts, no names). Meanwhile the legacy prompt
(`build_system_prompt`) stuffed `json.dumps(get_graph(user_id), indent=2)` —
user-wide, so it leaked every OTHER course's concepts, plus row ids and mastery
event history the model has no use for. And `chat_tutor` was the one agent
excluded from the offline eval harness (ADR 0021 decision 4) because its read
tools bottomed out in live Supabase.

## Decision

1. **Hybrid grounding: deterministic seed block + read tools.** Every agent
   chat turn gets a compact `GRAPH CONTEXT` block (`services/graph_context.py`)
   prefixed onto the user message after the catalog/RAG blocks: up to 12
   course-scoped concepts (message token-overlap first — the shared
   `services/token_overlap.py` tokenizer — then weakest-mastery fill), the
   depth-1 edges among them, one line per concept
   (`- Derivatives (0.42, learning) → related: Limits, Chain Rule`), ≤1.5k
   chars, no ids, no event history. The assembled prefix is never persisted —
   `save_message` keeps writing the raw `body.message`. For anything beyond the
   block, the tutor has two read-only tools (registered under prompt-facing
   names, 5 → 7 tools): `read_graph_neighborhood` (seed-match via
   `_normalize_concept`, depth-1 expansion, names only, `truncated` flag) and
   `read_concepts_for_user` (weakest-first list incl. `last_reviewed_at`),
   with a prompt-stated hard cap of two graph reads per turn. Reads degrade to
   empty on DB error and never touch `deps.graph_updates`/`mastery_changes`.

2. **Legacy de-dump.** The three legacy call sites (`_start_session_legacy`,
   `_legacy_chat`, `action`) now pass `compact_graph_context(get_graph(...),
   course_id)` — the SAME serializer, course-scoped — instead of the raw JSON
   dump. This ends the cross-course concept leak in the legacy prompt.
   `build_system_prompt` itself is unchanged.

3. **TUTOR_LIMITS.** The tutor runs under its own
   `UsageLimits(request_limit=12, tool_calls_limit=12, total_tokens_limit=100_000)`
   (`agents/__init__.py`), used by `_prepare_chat_run` only — the 7-tool
   surface legitimately needs more request/tool headroom than
   `ORCHESTRATOR_LIMITS`; the token ceiling stays the cost backstop.

4. **The TutorRetrieval seam** (`agents/tools/retrieval.py`): a Protocol with
   one method per tutor read (`course_materials`, `graph_neighborhood`,
   `concept_mastery`, `progress`, `session_history`). `SupabaseRetrieval`
   delegates verbatim to the existing pure functions; each tool wrapper
   resolves `ctx.deps.retrieval or SupabaseRetrieval` — production passes
   `None` and is byte-identical. Evals inject `FixtureRetrieval`
   (`tests/evals/_retrieval_fixture.py`) over a committed synthetic course
   (`tests/evals/fixtures/tutor_course.json`), so `chat_tutor` record/live runs
   are Supabase-free. **This supersedes ADR 0021 decision 4**: `chat_tutor` now
   runs in `run_all.py` + CI with committed cassettes and baselines. Cassettes
   additionally freeze the model's `tool_calls`, scored by three new
   evaluators (GraphToolUsed, MasteryUpdateEmitted with the ±band from the
   tool schema, GroundedConcept). Record-mode also stubs the graph WRITE seam
   (`apply_graph_update`) in-memory — an eval box has no database to write to.

5. **`read_misconceptions_for_course` stays unregistered** on the tutor —
   deferred until shared-context consent enforcement is real (the
   `use_shared_context=False` guard is an in-band prompt constraint today, not
   an enforcement boundary; a class-aggregate read tool must not ship behind a
   soft guard).

## Eval evidence (record 2026-07-30, gemini-2.5-pro, 16 cases)

Per-evaluator mean, before (pre-#149 prompt/tools, no seed block) → after:

| Evaluator | before | after |
|---|---|---|
| ExpositoryHasStructure | 0.812 | **1.000** |
| GraphToolUsed | 0.938 | **1.000** |
| GroundedConcept | 0.812 | **0.875** |
| MasteryUpdateEmitted | 0.688 | **1.000** |
| NonEmpty / Socratic? / TeachBack? / NoToolMisuse | 1.000 | 1.000 |

Known quirk surfaced by recording: with the "call update_mastery at the END of
the turn" guidance, gemini-2.5-pro occasionally follows the tool return with a
bare-newline final text (observed 2/3 rolls on one expository case) — a
degenerate `reply` production would also see on the JSON path. Tracked as a
follow-up prompt-shape fix; not addressed here to keep the diff scoped.
*(Since shipped: the stream-layer safety net landed with #153/PR #470,
and the root-cause prompt-shape fix — never end the turn on a tool
call — landed with #150/PR #471's re-record.)*

## Consequences

- (+) Every tutor turn is graph-grounded deterministically (AC 1), with tools
  for on-demand expansion (AC 3); mid-turn writes were already live (#127).
- (+) The legacy prompt no longer leaks other courses' concepts.
- (+) `chat_tutor` accuracy is finally measured and gated in CI like every
  other agent; the retrieval seam also gives future notebook/quiz agents an
  offline-injectable read surface.
- (−) The seed block adds ~0.3–1.5k chars to every course-scoped turn's input
  tokens — bounded by design, and cheaper than the model calling
  `read_concepts_for_user` every turn.
- (−) Cassettes bind loosely to prompt text (ADR 0021's standing trade):
  re-record + re-baseline whenever the preamble or tool descriptions change.
