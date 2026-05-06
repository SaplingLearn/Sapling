# 0002: Persistent dev-context vault structure

- Status: accepted
- Date: 2026-05-03
- Supersedes: none

## Context

Solo developer working with Claude Code. Sessions don't share state by default; restating architectural decisions every time costs tokens and risks drift between what was decided and what gets built next. Existing options were surveyed: MCP knowledge servers (rejected — JSONL knowledge graphs add overhead without payoff for engineering context at this scale), the Anthropic memory tool (rejected — not engineering-shaped), custom solutions (rejected — premature). Plain markdown in the repo, plus thin tooling, is the chosen baseline.

## Decision

Use a markdown-based vault: `CLAUDE.md` at root for stable project context, `docs/decisions/` for ADRs (MADR-minimal, append-only, never edited in place), `docs/attempts/` for failed approaches (always with a "What I'd try next" section), `docs/architecture.md` for the current-state overview. Tooling: four slash commands in `.claude/commands/` (`/log-decision`, `/log-attempt`, `/recall`, `/sync-context`) plus one read-only subagent (`context-curator`) that auto-loads vault context on relevant tasks. Re-evaluate the option of MCP knowledge servers (e.g. `basic-memory`) once the ADR count exceeds 50.

## Consequences

- (+) Zero infra cost, fully version-controlled, plain text.
- (+) Subagent and slash command pattern matches Claude Code's native primitives.
- (+) ADRs are append-only, so reverting/superseding is explicit.
- (−) Search is `rg` over markdown; no semantic search until/unless `basic-memory` adopted.
- (−) Discipline-dependent — if `/log-decision` isn't used, the vault decays.
- (−) The subagent's auto-invocation depends on description quality; needs tuning over time.
