# Tutor course-scope: stop refusing off-syllabus questions

Date: 2026-08-10
Status: approved, not yet implemented
Scope: chat tutor only (`routes/learn.py`, `agents/chat_tutor.py`, one param on `services/rag_service.py`)

## Problem

A student in CAS CS 132 (geometric algorithms) asked "can we talk about markov
chains" and the tutor replied:

> I can only find information about geometric algorithms. Markov chains are not
> in the course description.

That is wrong twice over. It refuses to teach a legitimate academic topic, and it
volunteers course-scope commentary the student never asked for.

## Root cause

Not retrieval. `rag_service.retrieve_chunks` already filters at
`min_similarity=0.55` (rag_service.py:126), so for "markov chains" in a geometric
algorithms course it correctly returned **nothing** — the RAG block was empty and
never reached the model.

The trigger is the **unconditionally injected catalog block**.
`routes/learn.py::_prepare_chat_run` (learn.py:534-563) assembles:

```
COURSE CATALOG INFO (official BU course data):
  <CAS CS 132 — geometric algorithms description>

GRAPH CONTEXT: <geometric-algorithms concepts>

[STUDENT QUESTION]
can we talk about markov chains
```

Nothing in that assembly tells the model what the blocks are *for*, or what to do
when the question falls outside them. Given a wall of authoritatively-labelled
context and no guidance, a model defaults to closed-book RAG behaviour: answer
from the context, otherwise decline. The screenshot was on the "Fast" (Lite) tier,
which is the most literal about this.

The mode prompts in `agents/chat_tutor.py` contain **no** course restriction. The
refusal is emergent from framing, not from any instruction anyone wrote.

## The rule

Three tiers, in priority order:

1. **Relevant course material exists** → use it as teaching substance. This is
   RAG's purpose: course-specific exercises and problems, in preference to
   generic material.
2. **No course material, or not enough for the question** → behave as original
   Sapling did: a general expert tutor answering from full knowledge, using the
   rich formatting toolkit, still tracking the knowledge graph. No mention of the
   course.
3. **Course information** — catalog metadata: description, prerequisites,
   credits, what the course covers → surfaced **only** when the student asks
   about the course directly. Never volunteered; never used to judge whether a
   topic may be discussed.

### Course information vs course material

The distinction the whole spec turns on:

- **Course information** = administrative metadata *about* the course. The
  catalog entry. Silent unless directly asked.
- **Course material** = the academic substance *of* the course. Uploaded
  documents, lecture notes, problem sets, tracked concepts. Usable as teaching
  substance whenever relevant.

The screenshot failure was the tutor volunteering course *information*.

### What "original Sapling" means

`backend/prompts/preamble.txt` (the Gemini-era prompt) has no course catalog, no
RAG block, and no course scoping of any kind. It is a general tutor with a
knowledge graph and an extensive formatting toolkit, instructed to use those tools
"ambitiously". Tier 2 means exactly that behaviour.

## Non-goals

- **Quiz generation is untouched.** `routes/quiz.py` assembles the same blocks,
  but its agent is told "generate N questions about concept X" — it never refuses,
  and RAG there already does the intended job. Any change to shared code must
  leave quiz byte-identical.
- **No change to retrieval.** The 0.55 threshold, chunking, and embedding stay as
  they are. This is a framing fix.
- **No conditional catalog injection.** The catalog stays unconditional on
  purpose: it is what makes "what are the prerequisites for this class?" work
  without depending on the similarity threshold, which such questions do not
  clear. Silence is enforced by framing, not by withholding.

## Changes

### 1. `routes/learn.py::_prepare_chat_run`

Relabel the two injected blocks so each states its purpose and its fallback.

Catalog (learn.py:542) — replace `"COURSE CATALOG INFO (official BU course data):"`:

```
COURSE REFERENCE (administrative data about this course). Use ONLY if the
student directly asks about the course itself — what it covers, prerequisites,
credits, schedule. Never volunteer it. Never use it to decide whether a topic
may be discussed.
```

RAG (learn.py:547) — pass a chat-specific header (see change 3):

```
COURSE MATERIAL (excerpts from this course's documents). Use as teaching
substance when it is relevant to the question. If it does not cover the
question, ignore it silently and answer from your own knowledge.
```

### 2. `agents/chat_tutor.py::_SHARED_PREAMBLE`

Three edits:

**a. Broaden the opening.** Currently: "an AI tutor that helps a student build
mastery in their course material" — which quietly reinforces the self-restriction.
Replace with:

```
You are Sapling, an AI tutor. You help a student build mastery in whatever
they are studying — their coursework first, and any academic topic they bring
you. You have tools to fetch the student's progress, search their uploaded
course documents, and update their knowledge graph mastery scores. Use tools
when relevant — don't fabricate context.
```

**b. Add the scope rule:**

```
SCOPE: answer any academic question the student asks, fully, from your own
knowledge. Never say or imply that a topic is outside the course, not in the
syllabus, or not in the course description. Never say you can "only" discuss
some subject. Do not comment on what the course does or does not cover unless
the student asks about the course itself. Context blocks in the message are
optional background, never a limit on what you may teach.
```

**c. Restore the formatting toolkit** from `prompts/preamble.txt` lines 11-66 —
the "use these ambitiously" instruction covering LaTeX (inline/display, the
predefined KaTeX macros), headings, tables, task lists, fenced code, blockquotes,
strikethrough for corrections, Mermaid (including the label-quoting escape rule),
`plot` fences, GeoGebra directives, mhchem, commutative diagrams, and the
`:::theorem` / `:::proof` container directives. Keep the closing "be deliberate,
not decorative" balance so short conversational turns stay plain.

**Restore the formatting half only.** The legacy `<graph_update>` JSON block
(preamble.txt lines 68-100) is obsolete — `apply_graph_update_tool` and
`update_mastery_tool` do that job now. Reintroducing it would produce a model that
both calls tools and emits parseable JSON at the student.

Every capability above still renders: `frontend/src/components/chat/MarkdownChat.tsx`
retains `rehype-katex` with the `KATEX_MACROS` table (`\norm`, `\Var`, …), mhchem,
`remark-directive`, the `sap-mermaid` / `sap-plot` fence extraction, and GeoGebra.
The renderer kept the capability; only the prompt guidance was lost.

`_PROMPT_HASHES` recomputes automatically, so these edits surface as a clean hash
delta in Logfire spans.

### 3. `services/rag_service.py::format_rag_context`

Add an optional header parameter, defaulting to the current string:

```python
def format_rag_context(chunks: list[dict], *, header: str | None = None) -> str:
```

`learn.py` passes the tier-1/tier-2 header from change 1. `quiz.py` passes
nothing and keeps `"RETRIEVED COURSE CONTEXT (semantically relevant to this
question):"` verbatim.

This is the minimal way to keep quiz byte-identical: the catalog labels are
already per-caller (learn.py:542 and quiz.py:189 hold separate strings), so
`format_rag_context` is the only shared surface. The untrusted-content envelope
(`wrap_untrusted`) is unchanged — the header stays trusted framing, chunk text
stays wrapped.

## Testing

Three regression tests pinning both halves of the rule, so a future prompt edit
cannot silently restore the refusal:

1. **Off-syllabus question answered.** Course context present, question unrelated
   ("markov chains" in a geometric-algorithms course). Assert the reply is
   substantive and contains no syllabus commentary — no "not in the course",
   "only", "course description".
2. **Direct course question still works.** "What are the prerequisites for this
   class?" still surfaces catalog facts. Guards against over-correcting into a
   tutor that refuses to discuss the course at all.
3. **Relevant material still used.** A question matching indexed material still
   draws on it, rather than being answered generically. Guards tier 1 against the
   tier-2 fallback swallowing it.

Test 1 is the regression for the reported bug and should be written first.

These split into two kinds, and the split should be explicit rather than blurred:

- **Deterministic (unit).** That `_prepare_chat_run` emits the new block labels,
  that `format_rag_context` honours the `header` param, and that quiz's call site
  still produces the old string byte-for-byte. These need no model and belong in
  the standard `pytest` suite. The quiz-unchanged assertion is the one that
  enforces the non-goal.
- **Behavioural.** That the model actually answers an off-syllabus question. This
  cannot be asserted under `SAPLING_MODEL_MODE=function`, where handlers return
  fixed constants regardless of prompt — a function-mode "pass" would prove
  nothing about the fix. It needs either a real-mode run or a small eval, and it
  should be run against the **Fast/Lite tier specifically**, since that is where
  the failure was reported and the strongest tier would mask it.

Implementation should not claim the bug is fixed on the strength of the
deterministic tests alone; they verify the framing changed, not that behaviour
did.

## Risks

**Instruction-following on the Lite tier.** The reported failure was on "Fast",
which is weakest at following negative instructions. The fix removes the *cause*
— once the labels stop reading as boundaries there is no wall to refuse from — so
this should hold, but it is the residual risk.

If Fast still drifts after this change, the escalation is to gate the catalog
block on a direct-question signal (course-deictic phrases: "this class", "the
midterm", a course code) and drop it otherwise. That is deliberately **not** in
this spec: it costs a relevance decision per turn and sacrifices the
catalog-always property, and it should be justified by evidence rather than
adopted speculatively.

## Files

- `backend/routes/learn.py` — block labels in `_prepare_chat_run`
- `backend/agents/chat_tutor.py` — `_SHARED_PREAMBLE` opening, scope rule, formatting toolkit
- `backend/services/rag_service.py` — optional `header` param on `format_rag_context`
- `backend/tests/` — three regression tests
- unchanged: `backend/routes/quiz.py`, retrieval, chunking, embeddings
