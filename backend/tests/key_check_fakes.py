"""The A124 key check (spec §13 A124) as a pass-through, for tests about
drafting, storage and the A119 alignment check.

Every generation write runs the key check (a blind solve of each valid draft,
agents/check_items_solve.py) after the alignment check and before it stores
anything, and an unavailable check drops the drafts (fail closed). Tests that
exercise drafting, the top-up, the redraft ledger, the A23 re-checks or the
alignment check are not about the key check, so they install this: every valid
draft passes as a solve that agreed with its key would leave it — kept, marked
key-checked and verified. The check itself is tests/test_learning_item_keys.py's.
"""

from __future__ import annotations


def keys_verified_as_drafted(screened, passages, *, deps, flex, course_id):
    """check_item_service._solve_screened with every valid draft agreeing."""
    return {
        key: [
            e._replace(verified=True, key_checked=True) if e.draft is not None else e
            for e in rows
        ]
        for key, rows in screened.items()
    }


def install_key_passthrough(monkeypatch) -> None:
    from services import check_item_service as svc

    monkeypatch.setattr(svc, "_solve_screened", keys_verified_as_drafted)
