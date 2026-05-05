# Sub-agent C — Refactor `routes/learn.py` to use chat_tutor_agent

Replace the legacy chat path with a typed agent run, preserve the legacy
fallback per ADR 0001, and stream tool-call events into SSE for the
frontend. WRITE the changes, run tests, report back.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/3-chat-tutor`

## Context already in place

- `backend/agents/chat_tutor.py` — exposes `agent_for_mode(mode)` which
  returns the right agent instance for the request. Output type is `str`.
- `backend/agents/tools/chat_context.py` — three context tools, all
  decryption-aware.
- `backend/agents/tools/graph.py::apply_graph_update_tool` — already
  registered on chat_tutor.
- `backend/agents/_providers.py` — `chat_tutor` task slot, default
  `gemini-2.5-pro`, override `SAPLING_MODEL_CHAT_TUTOR`.

## Why

`routes/learn.py` currently uses `services/gemini_service.py::call_gemini_multiturn`
inside a hand-built system prompt assembled by `build_system_prompt` (around
line 152). The agent path replaces that with `chat_tutor_agent.run_stream_events(...)`
so tool calls show up in Logfire, the streaming UX is observable per phase,
and the prompt is simpler.

## What to read first

- `backend/routes/learn.py` — entire file. Pay attention to:
  - `start_session`, `chat`, `end_session`, `action`, `mode_switch` — five
    routes that touch the tutor. `chat` is the main one.
  - `build_system_prompt` (~line 152): inventory what each piece of context
    becomes (tool call vs static prompt vs ignored).
  - The `messages` table reads/writes: encryption boundary at every read
    via `decrypt_if_present` and at every write via `encrypt_if_present`.
- `backend/routes/documents.py::upload_document_sync` — pattern for the
  agent-vs-fallback fallback decision (try/except UsageLimitExceeded /
  UnexpectedModelBehavior / Exception → legacy).
- `backend/routes/documents.py::upload_document` — pattern for streaming
  SSE with `agent.run_stream_events()` and the `map_to_sapling_event`
  helper.
- `backend/services/agent_events.py` — `SaplingEvent` shape + event
  mapping. The chat tutor's events should reuse `progress` / `result` /
  `status` types — frontend already consumes them.
- `backend/services/request_context.py::current_request_id` — for
  unifying SaplingDeps.request_id with the middleware ID.
- `backend/tests/test_learn_routes.py` — tests to keep green.
- `backend/services/encryption.py` — `encrypt_if_present`,
  `decrypt_if_present`. Use these at the boundary.

## What to change

### 1. Imports

Add to top of `routes/learn.py`:
```python
from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents.chat_tutor import agent_for_mode
from agents.deps import SaplingDeps
from services.request_context import current_request_id
from services.agent_events import SaplingEvent, sapling_event_to_sse, map_to_sapling_event
```

### 2. New helper: `_legacy_chat`

Rename the existing `chat` function body (the part that calls
`call_gemini_multiturn`) into `async def _legacy_chat(body, request) -> dict`.
Don't delete it — ADR 0001's contract preserves it as the fallback target.

### 3. New helper: `_chat_via_agent`

```python
async def _chat_via_agent(
    *,
    user_id: str,
    session_id: str,
    course_id: str | None,
    mode: str,
    user_message: str,
    message_history: list,    # Pydantic AI ModelMessage shape
    use_shared_context: bool,
    request_id: str,
    model_pref: str | None = None,
) -> dict:
    """Run chat_tutor_agent and return the same response shape the
    legacy path produced (so the route persistence code is unchanged).

    Returns: {"reply": str, "graph_update": dict, "mastery_changes": list}
    """
    agent = agent_for_mode(mode)
    deps = SaplingDeps(
        user_id=user_id, course_id=course_id,
        supabase=None, request_id=request_id,
    )
    model_override = _resolve_model_pref(model_pref)
    run_kwargs = {"deps": deps, "message_history": message_history}
    if model_override is not None:
        run_kwargs["model"] = model_override
    if use_shared_context is False:
        # When opted-out, instruct the agent inline not to call class-level
        # tools. (The tool is registered, but the prompt stops the LLM
        # from invoking it.)
        user_message += (
            "\n\n[Constraint: do not call read_misconceptions_for_course "
            "or any class-aggregate tool — student opted out of shared context.]"
        )

    result = await agent.run(user_message, **run_kwargs)
    reply = result.output  # str

    # graph_update / mastery_changes used to be parsed out of the legacy
    # JSON. With the agent path, the apply_graph_update_tool already
    # handled persistence directly — return empty dicts here so the
    # frontend's existing reducer doesn't break, but the data is already
    # in the DB.
    return {
        "reply": reply,
        "graph_update": {},
        "mastery_changes": [],
    }
```

Borrow `_resolve_model_pref` from `routes/quiz.py` — same shape, same
`_PREF_MODEL_NAMES` mapping. Either import it from `routes.quiz` or
duplicate the helper in `routes/learn.py` (small enough to duplicate,
but if you want a third callsite later you can extract to a
`services/model_pref.py`).

### 4. Refactor `chat` route

```python
@router.post("/chat")
async def chat(body: ChatBody, request: Request):
    require_self(body.user_id, request)

    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # Load message history (decrypt at the boundary).
    history = _load_message_history(body.session_id, decrypt=True)

    try:
        response = await _chat_via_agent(
            user_id=body.user_id,
            session_id=body.session_id,
            course_id=_get_session_course_id(body.session_id),
            mode=body.mode,
            user_message=body.message,
            message_history=history,
            use_shared_context=body.use_shared_context,
            request_id=request_id,
            model_pref=body.model_pref,
        )
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        logger.warning(
            "Chat agent guardrails tripped; falling back to legacy",
            exc_info=e,
        )
        response = await _legacy_chat(body, request)
    except HTTPException:
        raise  # legitimate 4xx/5xx — don't swallow into legacy
    except Exception:
        logger.exception("Unexpected chat-agent failure; falling back to legacy")
        response = await _legacy_chat(body, request)

    # Persist user + model messages (encrypt at the boundary).
    _save_message(body.session_id, role="user",
                  content=body.message, request_id=request_id)
    _save_message(body.session_id, role="model",
                  content=response["reply"], request_id=request_id)

    return response
```

### 5. Helpers for message history (encryption boundary)

```python
def _load_message_history(session_id: str, decrypt: bool = True) -> list:
    """Return the session's messages as Pydantic AI ModelMessage objects.
    Decrypts content at the boundary. Returns [] if session is new."""
    ...

def _save_message(session_id: str, role: str, content: str, request_id: str) -> None:
    """Persist a chat message; encrypt content at the insert boundary."""
    ...
```

`_load_message_history` should convert from the `messages` table shape
into Pydantic AI's `ModelMessage` (search Pydantic AI docs for the
exact constructors — likely `ModelRequest` / `ModelResponse` with
`UserPromptPart` / `TextPart`). If you're unsure, fall back to passing
a simpler shape and let the agent handle it; or convert via Pydantic
AI's helpers.

### 6. Tests

Update `backend/tests/test_learn_routes.py`:

- **Add an autouse fixture on the existing test class that forces the
  agent to fail**, so existing tests still exercise the legacy path
  (mirrors PR #71's `_force_legacy_pipeline` pattern).
- **Add new `TestChatViaAgent` class** with at least:
  - `test_returns_agent_reply` — mock `agent.run` to return a known
    string, assert the response dict shape.
  - `test_falls_back_to_legacy_on_usage_limit` — mock
    `agent.run` to raise `UsageLimitExceeded`, assert legacy fired.
  - `test_falls_back_to_legacy_on_unexpected_exception` — bare Exception.
  - `test_message_history_loaded_with_decryption` — assert
    `decrypt_if_present` was called for each historical message.
  - `test_user_and_model_messages_persisted_with_encryption` — assert
    `encrypt_if_present` was called for the new messages on insert.
  - `test_smart_pref_overrides_agent_model` — body `model_pref="smart"`
    → `agent.run` gets `model=GoogleModel("gemini-2.5-pro")`.

### 7. Same pattern for `start_session` and `action`

Both call into the legacy chat assembly. Migrate them the same way as
`chat` — agent first, legacy fallback on errors. `end_session` and
`mode_switch` don't generate text; they don't need migration.

## Verify
```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/test_learn_routes.py -q --no-header
python -m pytest tests/ -q --no-header --ignore=tests/evals
```

All previously-passing tests must still pass. Add at least 6 new tests.

## Constraints

- DO NOT modify `backend/agents/chat_tutor.py`, `backend/agents/tools/chat_context.py`,
  or `backend/agents/_providers.py` (sub-agents A and B's files).
- DO NOT delete the legacy code path. ADR 0001 contract.
- DO NOT change the response wire format. Frontend `Learn.tsx` reads
  `reply`, `graph_update`, `mastery_changes` from the response.
- DO NOT change the `messages` table schema.
- DO NOT commit. No ADRs.

## Report

- Files changed with line counts.
- New test count + total pass/fail summary.
- Whether `_resolve_model_pref` was imported from quiz or duplicated locally.
- Whether you streamed via `run_stream_events` (recommended for chat) or
  used non-streaming `run` for now (acceptable interim — frontend can be
  wired in sub-agent E).
- Anything that didn't fit (e.g. Pydantic AI's message_history shape
  required a custom adapter).
