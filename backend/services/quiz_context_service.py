import logging
import uuid
from datetime import datetime, timezone

from db.connection import table
from services.encryption import encrypt_json, decrypt_json_column

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
    table("quiz_context").upsert(
        {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "concept_node_id": concept_node_id,
            "context_json": encrypt_json(context),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,concept_node_id",
    )
