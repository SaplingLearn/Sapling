# MCP knowledge server trial

- Date: 2026-05-03
- Related: docs/decisions/0002-vault-structure.md

## What I tried

Stood up a JSONL-based MCP knowledge graph server (basic-memory style)
to back the dev-context vault before Day 1 was complete.

## Why it didn't work

Schema overhead dominated. With only 2 ADRs and 0 attempts, the
knowledge graph was almost entirely empty fixtures. Search via the
graph was no faster than `rg` over markdown. Synchronization between
the graph and the source markdown introduced a second source of truth.

## What I'd try next

Revisit at ~50 ADRs. At that point, `basic-memory` over the same
markdown files (no separate JSONL store) is the path to try first —
keep one source of truth, layer indexing on top.
