import logging
from datetime import datetime, timezone

from db.connection import table
from services.encryption import encrypt_json, decrypt_json_column
from services.quiz_distractors import DIGEST_SCHEMA_VERSION

logger = logging.getLogger(__name__)


def get_quiz_context(user_id: str, concept_node_id: str):
    rows = table("quiz_context").select(
        "context_json",
        filters={"user_id": f"eq.{user_id}", "concept_node_id": f"eq.{concept_node_id}"},
    )
    if rows:
        try:
            return decrypt_json_column(rows[0]["context_json"])
        except Exception:
            logger.warning(
                "get_quiz_context: context_json decrypt failed user=%s concept=%s; degrading to None",
                user_id, concept_node_id,
            )
            return None
    return None


def save_quiz_context(user_id: str, concept_node_id: str, context: dict):
    # No client-generated id: PostgREST's merge-duplicates upsert updates
    # every column in the payload on conflict, so an id here would rewrite
    # the existing row's PRIMARY KEY on each refresh. Fresh inserts get the
    # column's DB default (gen_random_uuid).
    # Version stamped HERE, server-side, and deliberately NOT a field on the
    # agent's output schema (#554 review). As an agent field the model owned
    # it — and the digest prompt feeds the previous context back in under
    # "update your notes", so a model that helpfully bumped a field named
    # "version" would trip the reader's unknown-shape warning on every
    # subsequent read for that (user, concept), forever, with no real drift.
    # A model that lowered it would kill the guard just as quietly.
    versioned = {**(context or {}), "schema_version": DIGEST_SCHEMA_VERSION}
    table("quiz_context").upsert(
        {
            "user_id": user_id,
            "concept_node_id": concept_node_id,
            "context_json": encrypt_json(versioned),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,concept_node_id",
    )
