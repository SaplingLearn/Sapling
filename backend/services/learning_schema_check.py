"""Boot-time check that the wave-4 learning schema the code reads is there
(learning-loop spec §13 A138 review, item 1). WARN ONLY: it never blocks boot,
like `agents/_providers.py::check_slot_guards`.

Why not refuse boot, as `encryption_canary.verify_encryption_key` does on a
key mismatch? That fence exists because a wrong key corrupts data that can
never be read back. A missing wave-4 table or column corrupts nothing. Every
reader of these tables on the request path reads "no rows" when the table is
missing, which is exactly true because nothing can be stored without it
(`loop_state_store.revealed_hashes`, A76's `prequestion_store.releases`). The
admin reports degrade to an empty section. Every writer sits behind a flag that
ships off, and a writer whose table is missing answers 503 and records nothing.
Staging deploys `main` on merge while its migrations are applied by hand, so
code ahead of its migration is that environment's normal order. Refusing boot
would turn that correct state into a full outage of every feature. So this check
makes the gap loud instead: one ERROR naming what is missing, at every boot,
until `python -m db.migrate` runs. The full release audit stays
`scripts/learning_release_verify.py --db-audit`."""

from __future__ import annotations

import logging

from db.connection import is_missing_relation, table

logger = logging.getLogger("sapling.learning.schema_check")

#: The wave-4 schema (migrations 20261108184825 teach prompts, 20261108185101 +
#: 20261108205812 varied practice): table → the columns the code names.
WAVE4_SCHEMA: dict[str, str] = {
    "learning_prequestions": "id,question_hash,format,difficulty,answered_at",
    "learning_self_explanations": "id,juncture,status,reply_chars",
    "node_mastery_events": "id,multi_concept",
    "check_items": "id,surface_representation,surface_context,apex_key,component_keys",
}
#: Postgres' undefined_column and PostgREST's "column not in the schema cache".
_MISSING_COLUMN_CODES = frozenset({"42703", "PGRST204"})


def _missing_column(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    try:
        body = response.json() if response is not None else None
    except Exception:
        return False
    return isinstance(body, dict) and body.get("code") in _MISSING_COLUMN_CODES


def check_learning_schema() -> list[str]:
    """The wave-4 tables or column sets this database lacks: one ERROR naming
    them, and the list. Empty when all is there, and when the database could
    not be asked (an unreachable database, any other error: a WARNING, as the
    key canary skips). Never raises."""
    missing: list[str] = []
    for name, columns in WAVE4_SCHEMA.items():
        try:
            table(name).select(columns, limit=1)
        except Exception as exc:
            if is_missing_relation(exc):
                missing.append(name)
            elif _missing_column(exc):
                missing.append(f"{name}({columns})")
            else:
                logger.warning("learning schema check skipped (%s)", type(exc).__name__)
                return []
    if missing:
        logger.error(
            "learning schema is behind the code: %s missing — apply the pending migrations "
            "(python -m db.migrate); until then their readers read no rows and their flags must stay off",
            ", ".join(missing),
        )
    return missing
