# Claude Code's Supabase MCP (`.mcp.json`)

JSON has no comments, so the reasons for the repo-root `.mcp.json` live here.

`.mcp.json` is checked in and loads for everyone who opens the repo in
Claude Code. It used to point the Supabase MCP server at
`project_ref=jxqcmjqtjlpuxfrxmrdv`, the project the release runbook
(`docs/releases/2026-11-architecture-hardening.md`) curls as production,
with the server's default full access: `execute_sql`, `apply_migration`,
branch and project management. One agent session, or one prompt injected
through a document it read, could then run DDL or delete student rows in
production, outside the append-only migration path (`python -m db.migrate`)
and outside every review this repo has.

Now (2026-11-16):

- **`read_only=true`.** The server runs SQL as a read-only Postgres user and
  hides the mutating tools. Schema changes still go through
  `backend/db/migrations/` only.
- **No `project_ref`.** The staging project ref is not documented anywhere in
  this repo, and production is the wrong default. Without a ref the server
  works across the projects the signed-in account can see, so the project is
  named explicitly per session. Once the staging ref is written down (for
  example in `docs/staging/setup-checklist.md`), pinning it here
  (`?project_ref=<staging-ref>&read_only=true`) is the better default.

Read-only still reads. Encrypted columns stay ciphertext, but the plaintext
ones (ids, concept names, scores, events) are visible to the session. Point it
at production only when the task needs production, and never paste row data
into prompts, issues or PRs.

To write (rare, deliberate), use a personal, uncommitted MCP config
(`claude mcp add --scope local ...`) against staging or a local stack. Do not
edit this file to do it.
