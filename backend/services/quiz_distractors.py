"""Per-concept mistake profile from what the student actually picked (#554).

`quiz_attempts.answers_json` has recorded the chosen option on every submit
since the column existed, and nothing ever read it back. The post-submit
digest agent was handed `results`, which carries LABELS only — "question 3,
picked B, the answer was C". A model cannot name a misconception from that;
it can only guess one. The option TEXT is what makes a wrong answer mean
something, and it lives in `questions_json`, one join away.

This module does that join and hands the digest agent the wrong answers in
words. Deliberately dumb: no model call, no I/O, pure data. It runs in the
post-submit BackgroundTask, after the attempt is graded and written, so it
must never raise — a crash here would cost the student their digest for a
quiz they already finished.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Bumped whenever the shape written into `quiz_context.context_json`
#: changes. #554 asks for this because the last drift — the reader looking
#: for `common_errors` while the agent wrote `common_mistakes` — was invisible
#: until #548 went looking. A version lets a reader say "I don't know this
#: shape" instead of silently finding nothing.
#:
#: 1 = the original free-form QuizContext (weak_areas, common_mistakes,
#:     questions_seen_summary, recommended_difficulty, notes)
#: 2 = adds `schema_version` itself, written by every digest from #554 on.
DIGEST_SCHEMA_VERSION = 2

#: The profile rides a prompt. An attempt caps at 10 questions today, so this
#: is not currently reachable — it is here so a longer attempt later cannot
#: quietly inflate the digest prompt.
MAX_PROFILE_ENTRIES = 10


def build_distractor_profile(
    questions: Any, results: Any
) -> list[dict[str, str]]:
    """Wrong answers, in words: what the student chose and what was right.

    Only WRONG answers: a correct answer says nothing about what the student
    misunderstands, and padding the prompt with correct ones spends tokens to
    report the absence of a problem.
    """
    try:
        return _build(questions, results)
    except Exception:  # pragma: no cover - defensive; see module docstring
        logger.warning("build_distractor_profile failed; digest loses the profile",
                       exc_info=True)
        return []


def _build(questions: Any, results: Any) -> list[dict[str, str]]:
    if not isinstance(questions, list) or not isinstance(results, list):
        return []

    by_id: dict[str, dict] = {}
    for q in questions:
        if isinstance(q, dict) and q.get("id") is not None:
            by_id[str(q["id"])] = q

    profile: list[dict[str, str]] = []
    for r in results:
        if not isinstance(r, dict) or r.get("correct"):
            continue
        chosen_label = r.get("selected") or ""
        if not chosen_label:
            # Skipped is not wrong. A blank selection says nothing about what
            # the student believes, and recording it as a distractor choice
            # would invent a misconception out of silence.
            continue
        q = by_id.get(str(r.get("question_id")))
        if not q:
            continue
        options = q.get("options")
        if not isinstance(options, list):
            continue

        chosen = _text_for_label(options, chosen_label)
        correct = next(
            (o.get("text") for o in options
             if isinstance(o, dict) and o.get("correct")),
            None,
        )
        # #129's shape: an item with NO correct option grades as wrong for
        # everyone. Reporting "the correct answer was <nothing>" would teach
        # the digest a misconception that does not exist.
        if not chosen or not correct:
            continue

        profile.append({
            "question": str(q.get("question") or ""),
            "concept": str(q.get("concept_tested") or ""),
            "difficulty": str(q.get("difficulty") or ""),
            "chose": str(chosen),
            "correct_answer": str(correct),
        })
        if len(profile) >= MAX_PROFILE_ENTRIES:
            break
    return profile


def _text_for_label(options: list, label: str) -> str | None:
    for o in options:
        if isinstance(o, dict) and o.get("label") == label:
            text = o.get("text")
            return str(text) if text else None
    return None
