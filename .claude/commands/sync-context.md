Load the most relevant dev-context vault state for a fresh session and emit a short digest. Read-only.

Steps:

1. Read `docs/architecture.md`. If it's missing or empty, note that explicitly in the digest.
2. List `docs/decisions/`, sort filenames descending (the `NNNN-` prefix means lexical sort = newest first), and read the **3 most recent** files. Skip `.gitkeep`. If fewer than 3 exist, read what's there and note the count.
3. List `docs/attempts/`, sort filenames descending (the `YYYY-MM-DD-` prefix means lexical sort = newest first), and read the **3 most recent** files. Skip `.gitkeep`. If fewer than 3 exist, read what's there and note the count.
4. If `CLAUDE.md` is not already in the active context, read it.
5. Emit a digest of 5-10 bullets summarizing the constraints, conventions, and recent decisions/attempts most relevant to the work ahead. Cap the digest at roughly 2000 tokens. For each non-trivial claim, cite the source file (e.g. `docs/decisions/0003-foo.md`).

Rules:
- Do NOT read every file in `docs/decisions/` — only the 3 most recent. The point is to stay under budget.
- Do NOT invent. If a file is empty or missing, say so verbatim instead of guessing.
- Do NOT modify any files (this is a read-only command).
- Do NOT include content from `frontend/`, `backend/`, or other code paths — vault only.
