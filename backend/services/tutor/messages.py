"""The tutor transcript (#118, moved verbatim from routes/learn.py): load the
history as Pydantic AI messages, write rows (idempotent per client turn, #761),
and replay a turn that already persisted.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from db.connection import table
from models import ChatBody
from services.agent_events import SaplingEvent, sapling_event_to_sse
from services.encryption import decrypt_if_present, encrypt_if_present
from services.tutor_sessions import (
    araise_if_discarded,
    raise_if_discarded,
    raise_if_discarded_here,
)


async def _load_message_history(session_id: str, *, exclude_id: str | None = None) -> list:
    """Load the prior conversation as Pydantic AI `ModelMessage` objects.

    Reads the encrypted `messages` rows, decrypts at the boundary, and
    converts each turn into a `ModelRequest`/`ModelResponse` pair so
    chat_tutor_agent.run() can consume them via `message_history=` for
    multi-turn coherence.

    Roles are mapped:
      - user    -> ModelRequest(parts=[UserPromptPart(...)])
      - assistant / model -> ModelResponse(parts=[TextPart(...)])
      - anything else -> dropped (e.g. legacy 'system' rows).

    Empty/decrypt-failed content is skipped so we don't feed empty
    parts to the LLM.

    The history carries NO system/instructions text. The tutor's rules
    reach the model only because the chat tutor agents declare them as
    `instructions=` (re-sent on every request); a `system_prompt=` would
    be skipped whenever this history is non-empty, i.e. on every turn after
    the opener. Pinned by tests/test_chat_tutor_prompt_every_turn.py.

    ``exclude_id``: the current turn's own user row, left behind by an
    earlier attempt that persisted it and then failed (#761) — it is this
    turn's message, not prior history, so it must not be sent twice.
    """
    rows = await table("messages").aselect(
        "id,role,content",
        filters={"session_id": f"eq.{session_id}"},
        order="created_at.asc",
    )

    history: list = []
    for r in rows or []:
        if exclude_id and r.get("id") == exclude_id:
            continue
        raw_role = (r.get("role") or "").lower()
        content = decrypt_if_present(r.get("content"))
        if not content:
            continue
        if raw_role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=str(content))]))
        elif raw_role in ("assistant", "model"):
            history.append(ModelResponse(parts=[TextPart(content=str(content))]))
        # else: drop (legacy 'system' rows have no equivalent in
        # Pydantic AI's role taxonomy).
    return history


def _message_row(session_id: str, role: str, content: str, graph_update, message_id) -> dict:
    return {
        "id": message_id or str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": encrypt_if_present(content),
        "graph_update_json": graph_update if graph_update else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def save_message(
    session_id: str, role: str, content: str, graph_update: dict = None,
    *, message_id: str | None = None, store_check: bool = True,
):
    """Write one transcript row.

    Refuses (404/409) a session discarded since the turn started (#761), so a
    turn racing end/delete gets a clean answer instead of an FK failure.

    ``message_id`` (#761): a turn-derived id (``_turn_message_id``) makes the
    write idempotent — a retried turn re-writes the same id and the duplicate
    is ignored, so a retry after a partial persist never duplicates the row.

    ``store_check=False``: this turn's earlier write read the store; memory only.
    """
    if store_check:
        await araise_if_discarded(session_id)
    else:
        raise_if_discarded_here(session_id)
    row = _message_row(session_id, role, content, graph_update, message_id)
    if message_id:
        await table("messages").aupsert(row, on_conflict="id", ignore_duplicates=True)
    else:
        await table("messages").ainsert(row)


def save_message_sync(session_id: str, role: str, content: str, graph_update: dict = None) -> None:
    """`save_message` for `_consume_pending`, which runs in the threadpool."""
    raise_if_discarded(session_id)
    table("messages").insert(_message_row(session_id, role, content, graph_update, None))


#: Namespace for turn-derived message ids (#761). Any fixed UUID works; it
#: only has to never change, or a retry stops matching its first attempt.
_TURN_MESSAGE_NS = uuid.UUID("5f0c1d6e-7a3b-4c2e-9d41-0b6e2a7c9f13")


def _turn_message_id(session_id: str, turn_id: str, role: str) -> str:
    """The deterministic ``messages.id`` of ``role``'s row for one client turn.

    Session-scoped (the session id is hashed in), so a client-chosen turn id
    can never address another session's rows.
    """
    return str(uuid.uuid5(_TURN_MESSAGE_NS, f"{session_id}:{turn_id}:{role}"))


async def _persisted_turn(session_id: str, turn_id: str | None) -> dict | None:
    """The stored result of a turn that already persisted, or None (#761).

    A client that lost a turn's `done` (cancel, idle timeout, dropped
    connection) after the server had persisted it re-sends the SAME
    ``turn_id`` on its fallback/retry. Re-running would answer the same
    message twice and re-apply the turn's tool writes; replaying the stored
    assistant row does neither. ``mastery_changes`` is not stored per
    message, so a replay reports none (the writes themselves did land).
    """
    if not turn_id:
        return None
    rows = await table("messages").aselect(
        "content,graph_update_json",
        filters={"id": f"eq.{_turn_message_id(session_id, turn_id, 'assistant')}"},
        limit=1,
    )
    if not rows:
        return None
    graph_update = rows[0].get("graph_update_json") or {}
    if isinstance(graph_update, str):
        try:
            graph_update = json.loads(graph_update)
        except ValueError:
            graph_update = {}
    return {
        "reply": decrypt_if_present(rows[0].get("content")) or "",
        "graph_update": graph_update,
        "mastery_changes": [],
        "replayed": True,
    }


async def _replay_events(replay: dict):
    """A persisted turn re-sent on /chat/stream, in the ordinary event
    vocabulary — status:start, ONE token with the whole reply, done — the
    same shape the Rung-1 fallback already produces."""
    for ev in (
        SaplingEvent(type="status", step="start", message="Starting."),
        SaplingEvent(type="token", step="reply", message="",
                     data={"delta": replay["reply"]}),
        SaplingEvent(type="done", step="reply", message="Complete.", data=replay),
    ):
        yield sapling_event_to_sse(ev)


def _turn_row_ids(body: ChatBody) -> tuple[str | None, str | None]:
    """(user row id, assistant row id) for this turn: deterministic when the
    client sent a ``turn_id``, else (None, None) — fresh random ids."""
    if not body.turn_id:
        return None, None
    return (
        _turn_message_id(body.session_id, body.turn_id, "user"),
        _turn_message_id(body.session_id, body.turn_id, "assistant"),
    )


async def _save_turn_rows(
    body: ChatBody, reply: str, graph_update: dict | None,
    *, user_row_id: str | None, assistant_row_id: str | None,
) -> None:
    """Persist one chat turn: the user row, then the assistant row.

    Partial persistence (#761): the two rows are two writes, so the second
    can fail after the first landed. With a ``turn_id`` both writes are
    idempotent (turn-derived ids, duplicates ignored), so a retry re-writes
    nothing it already has — and the retry's history load skips the orphan
    user row. WITHOUT one a retry would duplicate the user row, so the
    failure is stamped ``sapling_wrote`` — the same flag the agent helpers
    use for tool writes — and the stream reports ``retryable: False``.
    """
    await save_message(body.session_id, "user", body.message, message_id=user_row_id)
    try:
        await save_message(body.session_id, "assistant", reply, graph_update,
                           message_id=assistant_row_id, store_check=False)
    except Exception as exc:
        if not body.turn_id:
            exc.sapling_wrote = True
        raise
