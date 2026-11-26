"""How long a grade may run under its claim (spec §13 A52, C2).

Every grading surface — the loop's check and probe, the daily review, the
post-test — grades under a claim that every OTHER path treats as dead once it
is older than LOOP_GRADING_CLAIM_STALE_S: /check/next moves past it, /close
and /goal stop waiting for it, a review serve or a post-test claim takes the
item over. A grade still running then would save or write under a claim the
rest of the session has already given up. So the claimed run — the grader,
the help floor's re-read, everything before the grade is saved — is bounded
below that age by GRADE_DEADLINE_S, and a grade that runs out of time is
cancelled with nothing saved: the caller releases its claim and the student
submits again.

Pure asyncio: no I/O, no model, no clock of its own (the caller says how long
ago it claimed).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from learning.params import LOOP_GRADING_CLAIM_STALE_S

#: † engineering bound: what a claimed run may take, leaving the save that
#: follows it this many seconds inside the claim's live window
GRADE_DEADLINE_MARGIN_S = 15
GRADE_DEADLINE_S = LOOP_GRADING_CLAIM_STALE_S - GRADE_DEADLINE_MARGIN_S


class GradeDeadlineExceeded(RuntimeError):
    """The claimed run outlived GRADE_DEADLINE_S and was cancelled before
    anything was saved: release the claim and ask for the answer again."""


@asynccontextmanager
async def within_grade_deadline(elapsed_s: float = 0.0) -> AsyncIterator[None]:
    """Run the body only while the claim is inside GRADE_DEADLINE_S, counted
    from the claim (`elapsed_s` seconds ago). Past it the body is cancelled
    and GradeDeadlineExceeded raised; any other error passes through as is."""
    remaining = GRADE_DEADLINE_S - max(0.0, float(elapsed_s))
    deadline = asyncio.timeout(max(0.0, remaining))
    try:
        async with deadline:
            yield
    except TimeoutError:
        if deadline.expired():  # ours; a TimeoutError of the body's own passes through
            raise GradeDeadlineExceeded("the grade outlived its claim") from None
        raise
