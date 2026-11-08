# Sapling docs

- `decisions/` — Architectural decision records (ADRs). Append-only.
  Numbered sequentially. New decisions get a new file; old decisions get
  superseded by a new ADR that links back. Never edit an accepted ADR
  in place.
- `attempts/` — Things tried that did not work. Dated `YYYY-MM-DD-slug.md`.
  Always include a "What I'd try next" section.
- `architecture.md` — Short, current overview of the system. Updated when
  it gets wrong, not on a schedule.
- `frontend-testids.md` — `data-testid` naming convention for the surfaces
  the browser suite drives, plus the ESLint rule that enforces it.
- `security/` — Security hardening and remediation plans (RLS lockdown,
  storage hardening, realtime JWT bridge).
- `staging/` — Staging environment setup notes.
- `design/` — Design docs for cross-cutting backend changes before they are
  built (e.g. `async-db-client.md`, #117).
- `releases/` — Prod release plans: merge order, migrations with reverse SQL,
  flags, promote + rollback steps (e.g. `2026-11-architecture-hardening.md`).

If you are Claude Code, run `/sync-context` to load the most recent
decisions before working.
