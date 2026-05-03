# Sapling docs

- `decisions/` — Architectural decision records (ADRs). Append-only.
  Numbered sequentially. New decisions get a new file; old decisions get
  superseded by a new ADR that links back. Never edit an accepted ADR
  in place.
- `attempts/` — Things tried that did not work. Dated `YYYY-MM-DD-slug.md`.
  Always include a "What I'd try next" section.
- `architecture.md` — Short, current overview of the system. Updated when
  it gets wrong, not on a schedule.

If you are Claude Code, run `/sync-context` to load the most recent
decisions before working.
