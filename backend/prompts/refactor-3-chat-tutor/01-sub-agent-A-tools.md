# Sub-agent A — Build chat-tutor tools

Build three new Pydantic AI tools the upcoming `chat_tutor_agent` will use.
WRITE the changes, run tests, report back.

Repo: `/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling`
Branch: `refactor/3-chat-tutor` (already checked out)

## Why

Per `docs/decisions/0001-adopt-pydantic-ai.md` and `0005-refactor-2-quiz-generation.md`,
refactor #3 replaces the chat tutor's hand-built system prompt with a typed agent
that uses tools to fetch context on demand. Today's `routes/learn.py::build_system_prompt`
stuffs course context, recent sessions, and graph state into one giant string. Each
piece becomes a tool the agent calls only when it needs that data.

## Tools to build

`backend/agents/tools/chat_context.py` (new file). Three pure-async functions
plus thin Pydantic AI tool wrappers:

### 1. `search_course_materials(course_id, query)`

Returns relevant document summaries + concept notes for the course, scored by
keyword match against the query. The chat tutor uses this to ground answers in
the user's uploaded materials instead of hallucinating from general knowledge.

Schema:
```python
class CourseMaterial(BaseModel):
    document_id: str
    file_name: str
    summary: str | None
    concept_notes: list[dict]  # {name, description}

async def search_course_materials(
    course_id: str | None, query: str, limit: int = 5,
) -> list[CourseMaterial]:
    ...
```

Implementation: read from `documents` table filtered by `course_id`. Decrypt
`summary` and `concept_notes` (they're encrypted at rest per CLAUDE.md).
Score by simple keyword overlap with `query` (no embeddings yet — keep it
simple). Return top `limit`.

### 2. `read_session_history(session_id, last_n)`

Returns the last N messages from the current session so the agent can
self-reference earlier in the conversation without reloading the entire
multi-turn payload every time. (Pydantic AI's `message_history` arg
already covers full multi-turn — this tool exists for cases where the
agent wants a quick lookup mid-response, e.g., "what did the student
just say their major was?")

Schema:
```python
class SessionMessage(BaseModel):
    role: Literal["user", "model"]
    content: str
    created_at: str

async def read_session_history(
    session_id: str, last_n: int = 10,
) -> list[SessionMessage]:
    ...
```

Implementation: read from `messages` table filtered by `session_id`,
ordered by `created_at` DESC, limit `last_n`. **Decrypt `content`** before
returning (encryption is at rest, decrypt at the boundary).

### 3. `read_user_progress(course_id)`

Returns the student's overall progress in a course: total concepts, mastered,
weak. The agent uses this to decide whether to introduce new material or
reinforce existing.

Schema:
```python
class CourseProgress(BaseModel):
    total_concepts: int
    mastered_count: int      # mastery >= 0.7
    weak_count: int          # mastery < 0.4
    in_progress_count: int   # 0.4 <= mastery < 0.7
    avg_mastery: float

async def read_user_progress(
    user_id: str, course_id: str | None,
) -> CourseProgress:
    ...
```

Implementation: read from `graph_nodes` filtered by user+course, aggregate
in Python (the dataset is small per user-course). Return zeros if no rows.

## Tool wrapper pattern (for all three)

Mirror the shape from `backend/agents/tools/graph_read.py`:

```python
async def search_course_materials_tool(
    ctx: RunContext[SaplingDeps], query: str,
) -> list[CourseMaterial]:
    """Pydantic AI tool wrapper. Reads course_id from ctx.deps."""
    return await search_course_materials(ctx.deps.course_id, query)
```

Tools should accept arguments from the LLM (the `query`) and resolve user/course
context from `ctx.deps` (security boundary — never let the LLM specify user_id).

## Tests

`backend/tests/test_chat_context_tools.py` — 6-8 tests covering:
- Decryption boundary (mock `decrypt_if_present` and assert it was called)
- `search_course_materials` returns top-N by score, drops empty entries
- `read_session_history` returns most-recent first, decrypts content
- `read_user_progress` aggregates correctly, handles empty graph (zeros)
- Tool wrapper extracts user_id/course_id from `ctx.deps`

Use the `MagicMock` factory pattern from `backend/tests/test_quiz_routes.py::_make_table`.

## Verify
```bash
cd "/Users/josegaelcruzlopez/Documents/Startup_Projects /Sapling/backend"
python -m pytest tests/test_chat_context_tools.py -q --no-header
python -c "from agents.tools.chat_context import search_course_materials, read_session_history, read_user_progress; print('OK')"
```

## Constraints

- DO NOT modify `backend/agents/chat_tutor.py` (sub-agent B is creating it).
- DO NOT modify `backend/routes/learn.py` (sub-agent C will).
- DO NOT modify `backend/tests/evals/` (sub-agent D).
- DO NOT commit. No ADRs.
- Encryption: every read from `messages.content`, `documents.summary`, or
  `documents.concept_notes` MUST go through `decrypt_if_present` /
  `decrypt_json` before returning to the agent. Don't ship plaintext-leak.

## Report

- Files created with line counts.
- Test counts (must all pass).
- Whether the search uses keyword overlap (acceptable) or you found a reason
  to add embeddings (probably out of scope; flag if so).
- Anything that didn't fit.
