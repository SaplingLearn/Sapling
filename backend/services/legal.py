"""The current Terms of Service and Privacy Policy versions, and the record of
which ones a student accepted.

A version is the "Last updated" date on the public /terms and /privacy pages.
The frontend keeps the same two constants in ``frontend/src/lib/legal/versions.ts``
(the module the pages and onboarding read the documents and their dates from);
``tests/test_legal_versions.py`` fails when the two disagree, so bump both
together when a document changes.

Onboarding (``POST /api/onboarding/profile``) refuses a submit that accepted
anything but these versions (422 ``legal_outdated``) and records the two it did
accept in ``legal_acceptances`` before the account is marked onboarded.
"""
from __future__ import annotations

from db.connection import table
from db.scope import service_scope

TERMS_VERSION = "2026-10-22"
PRIVACY_VERSION = "2026-11-03"

#: `legal_acceptances.document` values (the table's CHECK constraint).
TERMS = "terms"
PRIVACY = "privacy"


def accepted_current(terms_version: str, privacy_version: str) -> bool:
    """Whether a student accepted the documents as they stand now."""
    return terms_version == TERMS_VERSION and privacy_version == PRIVACY_VERSION


def record_acceptances(user_id: str, *, terms_version: str, privacy_version: str) -> None:
    """Append the two acceptances (`legal_acceptances`, append-only).

    One row per (student, document, version), stamped by the database clock.
    A retried or concurrent onboarding submit re-sends the same rows; ON
    CONFLICT DO NOTHING keeps the first one, so its `accepted_at` stays the
    time the student first accepted that version and nothing is ever updated.

    The table is service-only (RLS bucket E): acceptance is account state the
    backend records, like `users.onboarding_completed`, not a row the
    student's own token may write."""
    rows = [
        {"user_id": user_id, "document": TERMS, "version": terms_version},
        {"user_id": user_id, "document": PRIVACY, "version": privacy_version},
    ]
    with service_scope():
        table("legal_acceptances").upsert(
            rows, on_conflict="user_id,document,version", ignore_duplicates=True,
        )
