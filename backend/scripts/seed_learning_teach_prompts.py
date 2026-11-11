"""Opt-in, LOCAL E2E assets for the spec §13 A138 prequestion journey.

The rich seed's loop items are free text (SEED_LOOP_FORMATS), and the real
diagnostic spends most of a concept's fresh items, so a segment opening right
after it has too few left for a prequestion beside its checks (the A138 pool
rule). Run AFTER the journey's diagnostic (it reads no learner data), this adds
three multiple-choice items per loop concept — the format a prequestion
prefers — cloned from the concept's rich free item (its source passage and
rubric), with options A–D and B correct:

    rich-check-<slug>-mc-pq1   difficulty 1   (the prequestion the journey sees)
    rich-check-<slug>-mc-pq2   difficulty 1
    rich-check-<slug>-mc-pq3   difficulty 2

B's text — and the items' reference and final answer — is the prequestion
items' OWN sentinel, E2E_LOOP_PREQUESTION_ANSWER, never the checks'
E2E_LOOP_FINAL_ANSWER: the e2e learn_loop oracle then judges each by its own
release (a check's answer before a check released it; a prequestion's before
its guess was answered), and the first answered prequestion no longer counts
as a release of every check's answer (review fix). No attempt, evidence,
release, help, goal or session metadata is written here. Usage:
`python -m scripts.seed_learning_teach_prompts` (from backend/; an ops CLI beside
the other seeds that write through the app's services, so it lives in scripts/,
not db/: spec §13 A149)
(frontend/e2e/support/db.ts::seedTeachPromptItems)."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from db import seed_helpers as h
from db.connection import table
from db.seed_local_rich import COURSE_CS, LOOP_NODES
from learning.checks import question_hash
from services.encryption import encrypt_if_present, encrypt_json

#: (n, difficulty) of the cloned items.
VARIANTS = ((1, 1), (2, 1), (3, 2))
#: The correct option's letter.
CORRECT = "B"


def _require_local() -> None:
    host = urlsplit(os.getenv("SUPABASE_URL", "")).hostname
    if host not in {"127.0.0.1", "localhost", "::1"} or os.getenv("APP_ENV") not in {"local", "test"}:
        raise RuntimeError("Teach-prompt fixtures require a local/test loopback database")


def options(final_answer: str) -> list[tuple[str, str, str | None]]:
    """(letter, text, wrong_key) — B is the prequestion items' sentinel."""
    return [
        ("A", "the alpha sentinel phrase", "alpha_sentinel"),
        ("B", final_answer, None),
        ("C", "the zulu sentinel phrase", "zulu_sentinel"),
        ("D", "the echo sentinel phrase", "echo_sentinel"),
    ]


def prequestion_item(template: dict, *, slug: str, concept: str, n: int, difficulty: int, final_answer: str) -> dict:
    """One multiple-choice clone of a rich free item: hash the NEW plaintext
    prompt before encrypting it (ADR 0025's order, as the rich seed does)."""
    row = {key: value for key, value in template.items() if key != "created_at"}
    prompt = (
        f"[e2e-loop] Prequestion item {n}: which option is the seeded sentinel phrase? "
        f"[{concept}, mc_reason, difficulty {difficulty}]"
    )
    opts = options(final_answer)
    row.update(
        id=f"rich-check-{slug}-mc-pq{n}",
        format="mc_reason",
        difficulty=difficulty,
        prompt=encrypt_if_present(prompt),
        question_hash=question_hash(prompt),
        options_json=encrypt_json([{"letter": letter, "text": text, "wrong_key": key} for letter, text, key in opts]),
        correct_option=encrypt_if_present(CORRECT),
        # A34: the correct option's text, stated as the item's final answer
        final_answer=encrypt_if_present(final_answer),
        reference_answer=encrypt_if_present(f"The option that names it is B. Final answer: {final_answer}."),
        canonical_answer=None,
        common_wrong_json=encrypt_json([{"key": key, "text": f"Picks {text}."} for _, text, key in opts if key]),
        graded=False,
    )
    return row


def seed_teach_prompt_items() -> None:
    from db.e2e_handler_constants import read_constants

    _require_local()
    (final_answer,) = read_constants("E2E_LOOP_PREQUESTION_ANSWER")
    for slug, concept, _ in LOOP_NODES:
        rows = table("check_items").select("*", filters={"id": f"eq.rich-check-{slug}-free-d1"}, limit=1)
        if not rows or rows[0]["course_id"] != COURSE_CS:
            raise RuntimeError(f"Missing rich loop item for {slug}: run db.seed_local_rich first")
        for n, difficulty in VARIANTS:
            h.upsert(
                "check_items",
                prequestion_item(rows[0], slug=slug, concept=concept, n=n, difficulty=difficulty,
                                 final_answer=item_sentinel(final_answer, slug, n)),
                on_conflict="course_id,concept_key,question_hash",
            )


def item_sentinel(base: str, slug: str, n: int) -> str:
    """One prequestion item's OWN key (second review): the base sentinel and
    the item's `<slug>-pq<n>` — the e2e learn_loop oracle reads the token back
    off the posed record's check_item_id (`rich-check-<slug>-mc-pq<n>`), so the
    first answered prequestion releases its own item's key only."""
    return f"{base} {slug}-pq{n}"


if __name__ == "__main__":
    seed_teach_prompt_items()
