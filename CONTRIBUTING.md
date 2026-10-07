# Contributing to Sapling

## Branching strategy

- `main` is the integration branch and must always be green and deployable. **Never push directly to `main`.**
- `production` is what is live. It is only updated by the promotion process (see "Releases").
- Create one branch per issue, named by type:
  - `feature/<short-name>` for new functionality
  - `fix/<short-name>` for bug fixes
  - `docs/<short-name>` for documentation only
- Keep branches short-lived and rebase or merge `main` into them often.

## Pull request process

1. Open an issue (or pick one from the Notion backlog / GitHub project board) before starting work.
2. Branch from `main`, make small, scoped commits (one logical change per commit).
3. Open a PR into `main`. Fill in the PR template (`.github/pull_request_template.md`) and link the issue with `Closes #<number>`.
4. **At least one teammate must approve** before merge. You may not approve your own PR.
5. **CI must pass** before merge (backend pytest + ruff, frontend eslint + typecheck + vitest, plus any E2E/eval workflows that apply to your change).
6. Squash and merge, then delete the branch.

Branch protection on `main` enforces the PR, approval, and passing-check requirements.

## Before you open a PR

Backend (from `backend/`):

```
python -m pytest tests/ -q --ignore=tests/evals
ruff check .
```

Frontend (from `frontend/`):

```
npm run lint
npm run typecheck
npm test
```

## Conventions

- **Database:** all Supabase access goes through `backend/db/connection.py::table()`. Schema changes are new, append-only migrations in `backend/db/migrations/` with a UTC timestamp prefix (`date -u +%Y%m%d%H%M%S`). Never edit an applied migration or run DDL in the Supabase dashboard.
- **LLM calls:** every LLM call is a Pydantic AI agent under `backend/agents/`. Don't add other LLM entry points.
- **Secrets:** never commit `.env` files or real keys. Only the `*.example` files are tracked. Document any new variable in the matching `.env.example` and in the README's environment variable tables.
- **Tests:** bug fixes should come with a test that fails without the fix.
- **Architecture decisions:** record significant decisions as ADRs in `docs/decisions/`.

## Releases

Staging and production are separate environments. Production releases go through the promotion runner, which runs preflight checks, applies migrations, asks for confirmation, merges `main` into `production`, and verifies the live deploy:

```
make promote
```

See `backend/promotion/README.md` for the full runbook. The frontend deploys to Cloudflare Workers automatically on push.

## Getting set up

Follow "Local Setup" in the [README](README.md). If any step fails or is unclear, fix the README in your PR.