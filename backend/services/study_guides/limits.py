"""The hourly limits on what one student may ask for, and a charge against
one of them.

Writing a guide or a block is a model call behind a button, and creating a
guide is a row behind one. Each has its own limit, so a student who has made
many guides can still have them written.

The limits can be raised from the environment. The window is counted per
process, so an E2E lane that runs every journey against one backend spends a
single budget; `scripts/e2e-up.sh` raises all three. Production sets none.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from services.request_limits import RateLimitClaim, aclaim_rate_limit, refund_rate_limit
from services.study_guides.errors import GuideRateLimited

logger = logging.getLogger(__name__)

RATE_WINDOW_S = 3600
RATE_LIMITED_DETAIL = "You have asked for a lot of writing this hour. Try again later."


def _limit(name: str, default: int) -> int:
    """`default`, or the positive whole number the environment gives under
    `name`. Read once, at import. Any other value is ignored with a warning:
    a stray variable must not switch a limit off."""
    raw = (os.getenv(name) or "").strip()
    if raw.isdecimal() and int(raw) > 0:
        return int(raw)
    if raw:
        logger.warning(
            "study guide: %s=%r is not a positive whole number; using %d", name, raw, default,
        )
    return default


#: Generation runs one student may start in an hour.
STUDY_GUIDE_GENERATE_LIMIT = _limit("STUDY_GUIDE_GENERATE_RATE_LIMIT", 20)
#: Block rewrites one student may ask for in an hour.
STUDY_GUIDE_BLOCK_LIMIT = _limit("STUDY_GUIDE_BLOCK_RATE_LIMIT", 40)
#: Guides one student may create in an hour.
STUDY_GUIDE_CREATE_LIMIT = _limit("STUDY_GUIDE_CREATE_RATE_LIMIT", 60)


@dataclass(frozen=True)
class Charge:
    """One action counted against a student's hourly limit."""

    key: str
    hit: RateLimitClaim

    def refund(self) -> None:
        refund_rate_limit(self.key, self.hit.slot)


async def acharge(user_id: str, *, action: str, limit: int) -> Charge:
    """Count one `action` against the student's hourly limit.
    `GuideRateLimited` past it."""
    key = f"study-guide-{action}:{user_id}"
    hit = await aclaim_rate_limit(key, limit=limit, window_sec=RATE_WINDOW_S)
    if hit.retry_after is not None:
        raise GuideRateLimited(RATE_LIMITED_DETAIL)
    return Charge(key=key, hit=hit)
