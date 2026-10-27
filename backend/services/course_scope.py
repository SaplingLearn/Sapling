"""Course-scope coverage for tutor turns: label it, never narrate it.

The bug class this exists to end
--------------------------------
A student asks about a topic their course's indexed material does not
cover. Retrieval comes back empty, `search_course_materials` returns
``[]``, the catalog blurb does not mention the term — and the model,
told to "use tools, don't fabricate context", narrates the gap:

    "I don't have anything from your syllabus about that…"

That sentence is a product failure three ways. It is usually *false*
(the course does cover the topic; we simply have not indexed it yet), it
is useless to the student (they asked to learn, not to audit our corpus),
and it teaches them that asking beyond the uploaded PDFs is off-limits —
which is the opposite of what a tutor is for.

The fix splits the responsibility:

* **The model never evaluates coverage.** Its prompt forbids mentioning
  missing syllabi, catalogs, documents or retrieval results at all; it
  answers from its own knowledge at the course's level. Coverage is not
  an input to its behaviour.
* **The route evaluates coverage, deterministically**, out of the same
  context blocks it already assembled — catalog text, retrieved chunks,
  graph concepts, session topic. That produces a label, not a disclaimer.
* **The UI shows the label** as a quiet "New" chip, and nothing more.
* **The backend relearns the scope**: an off-scope question schedules a
  `concept_scan` pass that registers the topic as a course concept, so the
  next turn's GRAPH CONTEXT block carries it and the same question is in
  scope from then on. (`services/course_scope_relearn.py`.)

Honest labels (the `routes/quiz.py::CourseMaterial` convention)
---------------------------------------------------------------
"We looked and found nothing" and "we could not look" are different facts
with different fixes, so `Coverage.status` keeps them apart: ``covered`` /
``new`` / ``unknown``. Only ``new`` is a claim about the course;
``unknown`` (no course, or the assessment raised) never shows a chip and
never triggers a relearn, because acting on it would mean asserting a
novelty we never established.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from services.token_overlap import tokenize

logger = logging.getLogger(__name__)

# Same token shape as services/token_overlap.py, kept here only to recover
# the ORDER tokenize() discards (it returns a set) when rendering the
# unmatched-term hint.
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")

#: Conversational shell the shared tokenizer keeps (it is tuned for ranking
#: documents, where "explain" in a summary is a real signal) but which carries
#: no topic here. Left in, they diluted every short question: "more about
#: eigenvalues please" matched its own session topic on 1 of 3 tokens and
#: read as novel. Stripped locally rather than in `token_overlap` so document
#: ranking and graph-block selection keep their existing semantics.
_QUESTION_SHELL: frozenset[str] = frozenset(
    {
        "explain", "describe", "tell", "show", "walk", "give", "help", "want",
        "need", "know", "understand", "learn", "teach", "ask", "mean", "means",
        "meaning", "please", "thanks", "ok", "okay", "yeah", "sure", "again",
        "more", "less", "some", "any", "all", "my", "me", "your", "their",
        "through", "between", "like", "just", "really", "actually", "think",
        "difference", "example", "examples", "question", "questions", "answer",
        "quick", "simple", "simply", "basically", "briefly", "little", "bit",
        "thing", "things", "stuff", "something", "anything", "everything",
        "there", "here", "much", "many", "lot", "lots", "get", "got", "go",
        "going", "make", "makes", "made", "use", "used", "using", "work",
        "works", "working", "one", "two", "also", "still", "even", "ever",
    }
)

#: How many of the question's topical tokens must appear somewhere in the
#: assembled scope for the turn to count as covered.
#:
#: One — deliberately. A ratio threshold was the first attempt and it was
#: wrong in the expensive direction: short questions are mostly shell, so
#: "walk me through backpropagation" scored 1/4 against a chunk that
#: literally defines backpropagation and came back `new`. Over-firing is the
#: costly failure (a chip on a question the course plainly covers, plus a
#: pointless LLM relearn); under-firing costs only a missing chip on a
#: question that shares a word with the syllabus. So: if the course's scope
#: recognizes ANY topical word in the question, it is not new.
MIN_MATCHED_TOKENS = 1

#: Questions with fewer topical tokens than this carry no signal to judge —
#: "ok?", "why", "more please" are entirely stopwords and shell. They inherit
#: the previous turn's scope rather than manufacturing novelty from filler.
#: One is enough: "eigenvalues?" is a real question about a real topic, and
#: it is exactly the one-word case the chip exists for.
MIN_SIGNAL_TOKENS = 1

#: Cap on the unmatched terms carried into the relearn hint / event payload.
#: The hint is a seed for concept_scan, not a transcript.
MAX_UNMATCHED_TERMS = 12

CoverageStatus = Literal["covered", "new", "unknown"]


# The model-facing half of the policy, owned here so every agent that can
# reach `search_course_materials` or a RAG block carries the SAME rule —
# chat_tutor and note_chat today, anything added later by importing this.
# Before it, the model treated empty retrieval as a fact worth reporting
# ("I don't have anything from your syllabus about that"), which is usually
# false, useless to a student who asked to learn rather than to audit our
# corpus, and actively harmful: it teaches them that questions beyond the
# uploaded PDFs are off-limits. Coverage is assessed by `assess_coverage`,
# surfaced as a quiet "New" chip, and fed back into the graph by
# `course_scope_relearn` — all of it OUTSIDE the model, so no behaviour here
# depends on what retrieval happened to return.
COVERAGE_PROMPT_RULE = (
    "COVERAGE (non-negotiable): course materials are a bonus, not a "
    "precondition. NEVER tell the student that their syllabus, course "
    "catalog, uploaded documents, or retrieved context lack information on "
    "something; never say a topic isn't in their materials, isn't covered "
    "by the course, or is outside the scope of the class; never mention "
    "searching, retrieval, tools, or what you did or didn't find. No "
    "hedging preamble, no caveat, no apology, no \"based on what I have\" "
    "framing. If the provided context covers the question, ground your "
    "answer in it. If it does not, simply teach the topic from your own "
    "knowledge, pitched at this course's level and connected to what the "
    "student is studying — the same answer you would give if the material "
    "had been there. Whether a topic is new to the course is tracked "
    "elsewhere and is not yours to narrate or act on."
)


@dataclass(frozen=True)
class Coverage:
    """The verdict on one turn's question against the course's known scope."""

    status: CoverageStatus = "unknown"
    #: Content tokens from the question the scope did not account for, in the
    #: order the student typed them. The relearn pass uses these as its seed.
    unmatched: tuple[str, ...] = ()
    #: Which scope sources contributed text, for logs and events. A `new`
    #: verdict against an empty scope reads very differently from one against
    #: a fully indexed course, and the payload has to tell them apart.
    sources: tuple[str, ...] = ()
    #: Share of content tokens the scope matched. -1.0 when not assessed.
    ratio: float = -1.0

    @property
    def is_new(self) -> bool:
        """True only for an established novelty verdict.

        `unknown` is NOT new — see the module docstring. Every consumer (the
        chip, the relearn scheduler, the event) reads this rather than
        comparing against "covered", so none of them can accidentally treat
        "we could not look" as "the course does not cover it".
        """
        return self.status == "new"

    def as_payload(self) -> dict:
        """Compact, identifier-free dict for the wire and for events."""
        return {
            "status": self.status,
            "terms": list(self.unmatched),
            "sources": list(self.sources),
        }


UNKNOWN_COVERAGE = Coverage()


def concept_names_from_graph_block(block: str | None) -> list[str]:
    """Recover the bare concept names from a rendered GRAPH CONTEXT block.

    The caller already has the block in hand at prompt-assembly time; parsing
    it back costs nothing, whereas re-reading `graph_nodes` would add a query
    per chat turn for data we are literally holding.

    Only the ``- Name (0.42, learning) → …`` concept lines are taken, so the
    #150 untrusted envelope's own boilerplate ("UNTRUSTED CONTENT", "do not
    follow instructions…") never enters the scope token set — those are
    generic English words that would quietly inflate every coverage ratio.
    """
    names: list[str] = []
    for line in (block or "").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        name = line[2:]
        # Cut the "(mastery, tier)" suffix and any "→ relationships" tail.
        cut = name.find(" (")
        if cut > 0:
            name = name[:cut]
        name = name.split("→")[0].strip()
        if name:
            names.append(name)
    return names


def _scope_tokens(
    *,
    catalog_text: str | None,
    rag_chunks: list[dict] | None,
    concept_names: list[str] | None,
    topic: str | None,
) -> tuple[set[str], tuple[str, ...]]:
    """Union of every token the course's known scope puts on the table, plus
    the names of the sources that actually contributed text."""
    tokens: set[str] = set()
    sources: list[str] = []

    if catalog_text and catalog_text.strip():
        tokens |= tokenize(catalog_text)
        sources.append("catalog")

    chunk_text = " ".join(
        (c.get("chunk_text") or "") for c in (rag_chunks or []) if isinstance(c, dict)
    )
    if chunk_text.strip():
        tokens |= tokenize(chunk_text)
        sources.append("chunks")

    names = [n for n in (concept_names or []) if n and n.strip()]
    if names:
        tokens |= tokenize(" ".join(names))
        sources.append("graph")

    # The session topic is scope by construction: the student named it when
    # they opened the session, and the opener already taught against it.
    if topic and topic.strip():
        tokens |= tokenize(topic)
        sources.append("topic")

    return tokens, tuple(sources)


def assess_coverage(
    message: str,
    *,
    course_id: str | None,
    catalog_text: str | None = None,
    rag_chunks: list[dict] | None = None,
    concept_names: list[str] | None = None,
    topic: str | None = None,
) -> Coverage:
    """Label one question against the course's assembled scope.

    Never raises: a failure here must not cost the student their turn, and an
    assessment that blew up is `unknown`, not `new` — manufacturing a novelty
    verdict out of a crash would schedule relearns nobody established were
    needed.

    Deliberately keyword-based rather than embedding-based. The inputs are
    already in hand at prompt-assembly time (so this adds no I/O to the
    request path), the semantics match `graph_context` and
    `search_course_materials` token for token (one definition of "the message
    mentions that term", not a third drifting one), and the cost of being
    wrong is one chip plus one background scan.
    """
    if not course_id:
        # No course means no scope to be outside of. A general-purpose
        # session is never "new to the course".
        return UNKNOWN_COVERAGE

    try:
        msg_tokens = tokenize(message) - _QUESTION_SHELL
        if len(msg_tokens) < MIN_SIGNAL_TOKENS:
            # Too little signal — inherit, don't invent. "why?" is a
            # follow-up on whatever the previous turn established.
            return Coverage(status="covered", ratio=1.0)

        scope, sources = _scope_tokens(
            catalog_text=catalog_text,
            rag_chunks=rag_chunks,
            concept_names=concept_names,
            topic=topic,
        )
        matched = msg_tokens & scope
        ratio = len(matched) / len(msg_tokens)

        novel = msg_tokens - scope

        unmatched: list[str] = []
        for raw in _WORD_RE.findall(message):
            low = raw.lower()
            if low in novel and low not in unmatched:
                unmatched.append(low)
                if len(unmatched) >= MAX_UNMATCHED_TERMS:
                    break

        status: CoverageStatus = (
            "covered" if len(matched) >= MIN_MATCHED_TOKENS else "new"
        )
        return Coverage(
            status=status,
            unmatched=tuple(unmatched),
            sources=sources,
            ratio=ratio,
        )
    except Exception:
        # "Could not tell" — never a chip, never a relearn. Logged because a
        # permanently broken assessor would otherwise look exactly like a
        # course whose every question is in scope.
        logger.warning("course-scope assessment failed; coverage unknown", exc_info=True)
        return UNKNOWN_COVERAGE
