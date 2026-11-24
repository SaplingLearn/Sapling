"""W2.4 / W2.4b flag gate for the low-trust next-probe hint.

``learning.next_probe_hint`` is pure selection. This module is the only
request-path entry: flag off → ``None`` immediately (byte-identical picker);
flag on → open the latest step ``reasoning_encrypted`` under the session bind
(when plaintext was not already supplied) and run ``prefer`` over that prose
plus caller-supplied candidates. Never mastery / never a graph mutation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from learning import check_reason
from learning import next_probe_hint as hint
from services.feature_flags import flag_on

#: Plan W2.4 — optional low-trust next-check preference from reason /
#: self-explain prose. Server-only; off = ordinary activation unchanged.
NEXT_PROBE_HINT_FLAG = "next_probe_hint"


def _next_probe_hint_on(user_id: str | None) -> bool:
    """``next_probe_hint`` for this student; no student → off; fails closed."""
    return bool(user_id) and flag_on(NEXT_PROBE_HINT_FLAG, user_id)


def preferred_next_question_hash(
    user_id: str | None,
    text: str | None,
    candidates: Sequence[tuple[str, str]],
    *,
    session_id: str | None = None,
    state: Mapping | None = None,
) -> str | None:
    """Preferred next check hash, or ``None``.

    Flag off → ``None`` without scoring or decrypt (no-op). Flag on → open
    the latest free/teachback ``reasoning_encrypted`` under the session bind
    when ``text`` is None, then ``learning.next_probe_hint.prefer`` over that
    plaintext + candidates. Never writes mastery or evidence.
    """
    if not _next_probe_hint_on(user_id):
        return None
    prose = text
    if prose is None:
        prose = check_reason.latest_plaintext(state, session_id)
    return hint.prefer(prose, candidates)
