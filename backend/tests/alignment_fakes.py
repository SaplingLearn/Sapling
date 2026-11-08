"""The A119 alignment check (spec §13 A119) as a pass-through, for tests about
drafting and storage.

Every generation write runs the alignment check (agents/check_items_verify.py)
before it stores anything, and an unavailable check drops the drafts (fail
closed). Tests that exercise drafting, the top-up, the redraft ledger or the
A23 re-checks are not about that check, so they install this: every valid
draft passes exactly as drafted — nothing dropped, nothing re-tagged — and is
stamped aligned, as a check that answered "every criterion asked, its own
concept" would leave it. The check itself is
tests/test_learning_item_alignment.py's.

`install_passthrough` also passes the A124 key check (tests/key_check_fakes.py),
which runs on the same write right after it: such tests are about neither.
"""

from __future__ import annotations


def aligned_as_drafted(screened, scope, *, deps, flex, course_id):
    """check_item_service._align_screened with every draft passing as is."""
    return {
        key: [e._replace(aligned=True) if e.draft is not None else e for e in rows]
        for key, rows in screened.items()
    }


def install_passthrough(monkeypatch) -> None:
    from services import check_item_service as svc
    from tests.key_check_fakes import install_key_passthrough

    monkeypatch.setattr(svc, "_align_screened", aligned_as_drafted)
    install_key_passthrough(monkeypatch)
