"""Silent-empty detection for agent tool results (F5, #544 addendum Part 2).

The bug class this exists to end
--------------------------------
Three of the quiz's personalization inputs returned zero rows for months
and nobody noticed:

* `quiz_context` writes 42P10'd into a swallowed `except: pass` from
  migration 0025 onward (#529) — the digest was always empty;
* `read_misconceptions_for_course` filtered
  `offering_concept_stats.offering_id` with the ABSTRACT course id, an id
  from a different keyspace — near-certainly zero rows;
* the digest coercer looked for `misconceptions`/`common_errors` while the
  writer wrote `common_mistakes` — the rows that did exist read as empty.

Every one of them failed the same way: **an empty list is exactly what
"this student has nothing yet" looks like.** A first-week student really
does have no attempts, no digest and no class misconceptions, so no caller
could treat empty as an error, and none did. The failures were therefore
indistinguishable from correct behaviour at every layer — logs, metrics,
tests and the prompt itself.

What this adds
--------------
The missing half of the signal: *did this student plausibly have data?*
Zero rows from a student who has enrollments / completed attempts / a
populated graph is a discrepancy worth a warning and a countable event.
Zero rows from a student with none of those is silence.

It is deliberately generic (`feature=` distinguishes callers) so the tutor's
read tools can route through the same seam — the fourth instance of this bug
class is as likely to land there as in the quiz.

Contract, matching every other observability path in this codebase: **never
raises, never blocks the tool it observes.** A probe that fails means
"can't tell", which is silence — a broken probe must not manufacture
findings any more than it should hide them.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

from db.connection import table
from services.events_service import log_event

logger = logging.getLogger(__name__)


class Expect(str, Enum):
    """Why this tool's caller believes the student might have data.

    The probe is per-expectation on purpose. "Should there be misconceptions
    for this course?" and "should there be past attempts?" are different
    questions, and answering them with one generic has-any-data check would
    reintroduce exactly the wrong-source mismatch that made the misconception
    tool silently empty in the first place.
    """

    #: Enrolled in at least one offering — so a class-scoped aggregate could exist.
    ENROLLED = "enrolled"
    #: Has completed at least one quiz attempt — so history/digest could exist.
    HAS_ATTEMPTS = "has_attempts"
    #: Has at least one knowledge-graph node — so concept reads could return rows.
    HAS_GRAPH = "has_graph"


# (table, extra filters). Each probe is a single owner-scoped, indexed read
# capped at one row: this runs on the request path, and "does any row exist"
# never needs a count.
_PROBES: dict[Expect, tuple[str, dict]] = {
    Expect.ENROLLED: ("enrollments", {}),
    # Completed only — an in-flight attempt is not evidence of history worth
    # digesting, and counting one would flag every student mid-first-quiz.
    Expect.HAS_ATTEMPTS: ("quiz_attempts", {"completed_at": "not.is.null"}),
    Expect.HAS_GRAPH: ("graph_nodes", {}),
}


def _user_plausibly_has_data(
    user_id: str, expect: Expect, scope: dict | None = None,
) -> bool | None:
    """True/False, or None when the probe could not answer.

    `scope` narrows the probe to the SAME slice the tool just read. Without
    it the probe answers a broader question than the tool asked, and the
    mismatch manufactures discrepancies out of ordinary situations — a
    student with attempts on one concept starting their first quiz on
    another, or a student with a graph in one course working in a second.
    Those are the routine cases, so getting this wrong would make the
    signal fire constantly and train everyone to ignore it.
    """
    probe = _PROBES.get(expect)
    if probe is None:
        return None
    table_name, extra = probe
    try:
        rows = table(table_name).select(
            "id",
            filters={"user_id": f"eq.{user_id}", **extra, **(scope or {})},
            limit=1,
        )
    except Exception:
        logger.debug(
            "tool_signals: %s probe failed for user=%s", expect, user_id,
            exc_info=True,
        )
        return None
    return bool(rows)


def report_empty_result(
    tool: str,
    *,
    user_id: str | None,
    count: int,
    expect: Expect,
    feature: str = "unknown",
    scope: dict | None = None,
    payload: dict | None = None,
) -> bool:
    """Flag a tool result that is empty when it probably shouldn't be.

    Returns True when the discrepancy was reported, so a caller can branch
    on it (and so tests can assert on it) — but the return value is
    advisory. Nothing here changes what the tool hands the model: an empty
    personalization input is still a legitimate prompt, just now an
    observable one.

    `count` is the number of rows/items the tool is about to return.
    Anything non-zero short-circuits before the probe, so the common case
    costs nothing.

    `scope` MUST narrow the probe to the same slice the tool read (see
    `_user_plausibly_has_data`). `feature` names the calling agent — it
    defaults to "unknown" rather than to any particular feature, because a
    tool registered on more than one agent (`read_concepts_for_user` is on
    both the quiz and the tutor) would otherwise attribute every caller's
    empties to whichever feature the default happened to name.

    NOTE: this is SYNCHRONOUS and does a Supabase read. Async callers must
    use `report_empty_result_async`, or they block the event loop.
    """
    try:
        if count or not user_id:
            return False
        if not isinstance(expect, Expect):
            try:
                expect = Expect(expect)
            except ValueError:
                logger.debug("tool_signals: unknown expectation %r", expect)
                return False

        plausible = _user_plausibly_has_data(user_id, expect, scope)
        if plausible is not True:
            return False

        logger.warning(
            "%s returned no rows for user=%s despite %s — a personalization "
            "input may be silently broken (F5)",
            tool, user_id, expect.value,
        )
        log_event(
            "quiz.tool_empty",
            category="error",
            user_id=user_id,
            payload={
                "tool": tool,
                "feature": feature,
                "expect": expect.value,
                **(payload or {}),
            },
        )
        return True
    except Exception:
        # Observability must never break the thing being observed.
        logger.debug("tool_signals: report_empty_result slipped", exc_info=True)
        return False


async def report_empty_result_async(tool: str, **kwargs) -> bool:
    """Async-safe `report_empty_result` for agent tool bodies.

    The probe is a blocking Supabase read (httpx, 30s client timeout). Called
    inline from an async tool it would stall the event loop — and therefore
    every other in-flight request on that worker — for the duration, which is
    exactly why every other Supabase read in those tools already goes through
    `asyncio.to_thread`. The probe runs on the EMPTY path, which today is the
    common one (a first quiz on a concept; and every misconceptions read until
    #553 is fixed), so this is not a rare corner.
    """
    try:
        return await asyncio.to_thread(report_empty_result, tool, **kwargs)
    except Exception:  # pragma: no cover - defensive; the sync form can't raise
        logger.debug("tool_signals: async report slipped", exc_info=True)
        return False
