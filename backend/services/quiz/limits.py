"""
backend/services/quiz/limits.py — moved from routes/quiz.py (#118).

Spend and rate-limit guards for quiz generation (#544 F1, #760).

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import logging
from datetime import datetime, timedelta, timezone

from db.connection import table
from db.scope import runs_as_service
from services.quiz.config import QUIZ_DAILY_SPEND_CAP_USD
from services.request_limits import refund_rate_limit

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


# supabase/config.toml sets PostgREST's max_rows = 1000, and an over-cap
# response is 206 Partial Content — a 2xx, so raise_for_status never fires
# and the truncation is silent. Same constant and same reasoning as
# achievement_service._daily_totals; page to completion or the sum is a lie.
_USAGE_PAGE = 1000


@runs_as_service  # #115: llm_usage is service-only (bucket E)
def _daily_spend_exceeded(user_id: str) -> bool:
    """True if this user is past the daily LLM spend ceiling (#544 F1).

    Reads the llm_usage ledger agents/usage.py already writes, PAGED: an
    unpaged read stops at max_rows, so a heavy user's sum plateaus below
    the cap and the guard never trips for exactly the runaway it targets.
    Stops early once the ceiling is crossed — the common case is a couple
    of rows, and a user past the cap doesn't need an exact total.

    Fails OPEN on any error: this is a cost control, not a correctness
    gate, and denying every student because a usage read blipped is worse
    than the spend it would save.
    """
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        spent = 0.0
        offset = 0
        while True:
            rows = table("llm_usage").select(
                "cost_usd",
                filters={"user_id": f"eq.{user_id}", "created_at": f"gte.{since}"},
                limit=_USAGE_PAGE,
                offset=offset,
            ) or []
            spent += sum(float(r.get("cost_usd") or 0.0) for r in rows)
            if spent >= QUIZ_DAILY_SPEND_CAP_USD:
                return True
            if len(rows) < _USAGE_PAGE:
                return False
            offset += _USAGE_PAGE
    except Exception:
        logger.exception("quiz: daily spend check failed user=%s; allowing", user_id)
        return False


def _refund_generate_slot(user_id: str, slot: float | None) -> None:
    """Hand back the rate-limit slot a failed generation consumed (#544 F1).

    The slot is claimed BEFORE the model runs (so a burst can't get past
    the gate concurrently), which means a backend failure would otherwise
    spend the student's quota: eight 502s in two minutes would lock them
    out for five with a message saying they'd generated too many quizzes,
    having received none. A failure the student didn't cause shouldn't
    cost them anything, and the 502 explicitly invites a retry.

    `slot` is the one THIS request claimed (#760) — refunding "the newest"
    would hand back a concurrent request's slot instead.
    """
    try:
        refund_rate_limit(f"quiz_generate:{user_id}", slot)
    except Exception:
        logger.exception("quiz: rate-limit refund failed user=%s", user_id)
