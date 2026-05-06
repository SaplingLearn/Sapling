# Refactor #3 — Chat Tutor: prompt pack

Reusable sub-agent prompts for converting `backend/routes/learn.py`'s
chat tutor onto a typed Pydantic AI agent per ADR 0001's migration plan.

## Files

| File | Purpose |
|---|---|
| `00-orchestrator-overview.md` | Read first. Sequencing, branch setup, constraints, dependencies on prior refactors. |
| `01-sub-agent-A-tools.md` | Build three new tools (`search_course_materials`, `read_session_history`, `read_user_progress`) in `agents/tools/chat_context.py`. |
| `02-sub-agent-B-agent.md` | Build `chat_tutor_agent` (three mode-specific instances) in `agents/chat_tutor.py`. |
| `03-sub-agent-C-route.md` | Refactor `routes/learn.py` to use the agent, with legacy fallback per ADR 0001. |
| `04-sub-agent-D-evals.md` | 15-case eval set (5 per mode) in `tests/evals/chat_tutor.py`. |
| `05-sub-agent-E-frontend.md` | (Optional, separate PR) Wire the new SSE events into `Learn.tsx`. |
| `06-adr-template.md` | Skeleton for `docs/decisions/0014-refactor-3-chat-tutor-shipped.md` to fill in after shipping. |

## How to dispatch

Phase 1 — run A, B, D in parallel (non-overlapping files):
- Spawn one `general-purpose` sub-agent per prompt.
- Wait for all three to finish.

Phase 2 — run C alone (depends on A + B):
- Spawn one sub-agent with the prompt from `03-sub-agent-C-route.md`.

Phase 3 — verify, ADR, commit, open PR.

Phase 4 (optional, separate PR) — sub-agent E for the frontend integration.

## When this is done

`services/gemini_service.py` becomes dead code on the happy path. A
follow-up small PR deletes it per ADR 0001's migration plan, and Sapling
is fully agentic.
