# 0027: Course coverage is labelled by the route, never narrated by the model

- Status: accepted
- Date: 2026-10-27
- Relates to: ADR 0023 (tutor graph/retrieval seam), ADR 0024 (Pydantic AI is
  the only LLM seam), #149 (GRAPH CONTEXT seed block), #629/#630 (who may
  retrieve a chunk), `routes/quiz.py::CourseMaterial` (the honest-labels
  convention this reuses)
- Supersedes: none

## Context

The tutor answered questions it had no indexed material for by saying so:

> "I don't have anything from your syllabus about that…"

Nothing in the prompt asked for that sentence. It was emergent, from the
preamble's "use tools when relevant — don't fabricate context" meeting an
empty `search_course_materials` result and an empty RAG block. The model read
"retrieval returned nothing" as a fact about the course and reported it.

It is wrong three ways:

1. **Usually false.** The course almost always covers the topic; what is
   missing is our index of it. A student who uploaded three PDFs out of a
   semester's material got told their class doesn't cover week 9.
2. **Useless.** They asked to learn a topic, not to audit our corpus. The
   disclaimer answers a question nobody asked and delays the one they did.
3. **Actively harmful.** It teaches the student that questions beyond the
   uploaded PDFs are off-limits — the opposite of what a tutor is for, and a
   direct drag on the behaviour the product depends on (asking freely).

Underneath the product problem is a structural one: the model's behaviour was
a function of what retrieval happened to return. Every retrieval gap — a
keyspace mismatch, an unindexed upload, a course with no BU code — therefore
leaked into the student's experience as an assertion about their class. The
`search_course_materials` docstring already names this: "to the model an empty
result is indistinguishable from 'this course has no materials'."

## Decision

Split coverage into three jobs, none of them the model's.

**The model never evaluates coverage.** `services/course_scope.py::COVERAGE_PROMPT_RULE`
is carried by every agent that can reach `search_course_materials` or a RAG
block — chat_tutor's three modes and note_chat. It forbids mentioning
syllabi, catalogs, uploaded documents, retrieval, or what was or wasn't found,
and tells the model to teach the topic from its own knowledge at the course's
level instead. The reply to an off-scope question is now byte-for-byte the
reply it would have given had the material been there.

**The route labels the turn, deterministically.** `assess_coverage` runs in
`_prepare_chat_run` over the blocks it has just assembled — catalog text,
retrieved chunks, graph concept names, session topic — and nothing else. No
extra I/O, no second read that could drift from what the model saw, and no
influence on the prompt. Keyword overlap, using the same `token_overlap`
tokenizer the document ranking and graph-block selection already use, so there
is one definition of "the message mentions that term" rather than a third.

**The verdict keeps "we could not look" apart from "it isn't covered."**
`covered` / `new` / `unknown`, the same discipline `routes/quiz.py::CourseMaterial`
applies to question provenance. Only `new` is a claim about the course.
`unknown` — no course on the session, or the assessment raised — shows nothing
and triggers nothing, because acting on it would reintroduce the original bug
one layer down: asserting something about a student's class that we never
established.

**The UI shows the label and nothing else.** `topic_status` rides the chat
response and the stream's `done` event; the client renders the
`tutor-new-topic` chip in the top bar. Per-turn and self-clearing — the next
in-scope question removes it — so it reads as a note about this question, not
a standing warning about the session.

**An off-scope question corrects us, not the student.** A `new` verdict
schedules `course_scope_relearn.relearn_course_scope` after the response: the
existing `concept_scan` agent, seeded with the question instead of a document
summary, registers the inferred concept(s) through `apply_graph_update` at
mastery 0.0. The next turn's GRAPH CONTEXT block carries it and the same
question assesses as `covered` from then on. `tutor.scope_relearned` records
the verdict's provenance (which sources were consulted, which terms missed,
how many concepts landed), so a scope that never grows — or grows every turn —
is visible rather than inferred.

## Options considered

1. **Soften the prompt** ("don't apologise for missing material"). Rejected:
   it leaves behaviour a function of retrieval, so the disclaimer returns in a
   new phrasing on the next model revision. The whole problem is that the
   model was deciding something it has no evidence for.
2. **Inject the coverage verdict into the prompt** so the model can mention it
   "tastefully". Rejected for the same reason, plus it re-creates the failure
   mode deliberately: any verdict in the prompt is a verdict the model can
   narrate, and `unknown` would get narrated too.
3. **Embedding-based coverage.** Rejected for now: the inputs are already in
   hand at assembly time, keyword overlap costs nothing on the request path,
   and the cost of being wrong is one chip plus one background scan. Revisit
   if the chip's precision becomes a complaint.
4. **A separate `course_scope` table** rather than the knowledge graph.
   Rejected: the graph already *is* this codebase's model of what a course
   covers, it is already course-scoped and dedup-enforced, and a second scope
   store would need its own invalidation story for no behavioural gain.

## Consequences

- Prompt hashes changed for all three tutor modes and for note_chat; recorded
  eval cassettes keyed on those hashes need re-recording.
- `_prepare_chat_run` returns a 5-tuple. Every call site and test stub moved.
- Coverage is judged on keyword overlap, so a question sharing one topical
  word with the syllabus reads as covered even when its real subject is new.
  That is the chosen direction to be wrong in: a missing chip costs nothing,
  while a chip on a question the course plainly covers is noise plus a
  pointless LLM call. `MIN_MATCHED_TOKENS` is the dial.
- The relearn is an extra LLM call on off-scope turns. It is post-response,
  capped at `MAX_CONCEPTS_PER_RELEARN` concepts per question, and converges:
  once the concept is in the graph, the same question stops being `new`.
- Nothing here is enforceable by a lint. A future agent with retrieval tools
  that forgets `COVERAGE_PROMPT_RULE` will regress silently;
  `tests/test_course_scope.py` pins the two agents that have it today.
