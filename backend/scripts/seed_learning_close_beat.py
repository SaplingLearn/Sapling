"""Opt-in, LOCAL E2E assets for the W1.3 generative-core close-beat journey.

The rich seed keeps one practice reserve per concept after the diagnostic
(services/loop/probe.py), so a default walk can grade only one Check me before
activation advances. This script adds one fresh free and one teachback item per
loop concept (difficulty 1), cloned from the concept's rich free-d1 row, so the
close beat (concept_checks == LOOP_CHECKS_PER_CONCEPT - 1) still has a
generative item to prefer. Run AFTER the probe (like seed_learning_teach_prompts);
writes no learner rows.

Usage: `python -m scripts.seed_learning_close_beat` (from backend/).
Frontend: `frontend/e2e/support/db.ts::seedCloseBeatItems`.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from db import seed_helpers as h
from db.connection import table
from db.seed_local_rich import COURSE_CS, LOOP_NODES
from learning.checks import question_hash
from services.encryption import bind, decrypt_if_present, encrypt_if_present


def _require_local() -> None:
    host = urlsplit(os.getenv("SUPABASE_URL", "")).hostname
    if host not in {"127.0.0.1", "localhost", "::1"} or os.getenv("APP_ENV") not in {
        "local",
        "test",
    }:
        raise RuntimeError("Close-beat fixtures require a local/test loopback database")


def close_beat_item(template: dict, *, slug: str, concept: str, fmt: str) -> dict:
    """Clone rich free-d1 into a fresh free/teachback asset for the close beat."""
    from services.check_item_service import reseal_row_for_id

    row = {key: value for key, value in template.items() if key != "created_at"}
    rid = f"rich-check-{slug}-close-{fmt}-d1"
    reseal_row_for_id(row, template["id"], rid)
    stem = decrypt_if_present(template["prompt"], bind=bind("check_items", "prompt", template))
    prompt = f"{stem} [close-beat {fmt}]"
    row.update(
        id=rid,
        format=fmt,
        difficulty=1,
        prompt=encrypt_if_present(prompt, bind=bind("check_items", "prompt", row)),
        question_hash=question_hash(prompt),
        graded=False,
    )
    return row


def seed_close_beat_items() -> None:
    _require_local()
    for slug, concept, _ in LOOP_NODES:
        rows = table("check_items").select("*", filters={"id": f"eq.rich-check-{slug}-free-d1"}, limit=1)
        if not rows or rows[0]["course_id"] != COURSE_CS:
            raise RuntimeError(f"Missing rich loop item for {slug}: run db.seed_local_rich first")
        for fmt in ("free", "teachback"):
            h.upsert(
                "check_items",
                close_beat_item(rows[0], slug=slug, concept=concept, fmt=fmt),
                on_conflict="course_id,concept_key,question_hash",
            )


if __name__ == "__main__":
    from services.encryption_canary import abort_unless_key_verified

    abort_unless_key_verified("scripts.seed_learning_close_beat")
    seed_close_beat_items()
