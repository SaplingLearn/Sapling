# Contributing to Sapling

## Branching strategy

- `main` is the integration branch and must always be green and deployable. **Never push directly to `main`.**
- `production` is what is live. It is only updated by the promotion process (see "Releases").
- Create one branch per issue, named `<type>/<short-kebab-name>`, using the same type as the PR title (see below): `feat/quiz-pager`, `fix/graph-link-overlap`, `docs/readme-setup`, `refactor/...`, `perf/...`, `test/...`, `ci/...`, `chore/...`.
- Keep branches short-lived and rebase or merge `main` into them often.

## Pull request process

1. Open an issue (or pick one from the Notion backlog / GitHub project board) before starting work.
2. Branch from `main`, make small, scoped commits (one logical change per commit).
3. Open a PR into `main` with a [Conventional Commits](https://www.conventionalcommits.org/) title: `type(scope): subject`, e.g. `fix(quiz): keep the selected exam on reopen`. Fill in the PR template (`.github/pull_request_template.md`) and link the issue with `Closes #<number>`.
   - `feat` and `fix` PRs must include a **user story** and **acceptance criteria** (copy them from the issue). UI changes include before/after screenshots.
   - The `PR hygiene` workflow checks the title and the spec sections and adds a type label (`enhancement`, `bug`, `documentation`, `tech-debt`, ...).
   - Open the PR as a **draft** while it is in progress; mark it ready when it meets its acceptance criteria.
4. **Request a review from at least one teammate, and wait for their approval** before merging. Do not merge your own unreviewed PR. Reviewers check the acceptance criteria, not just the diff.
5. **CI must pass** before merge (backend pytest + ruff, frontend eslint + typecheck + vitest, PR hygiene, plus any E2E/eval workflows that apply to your change).
6. **Squash and merge** (the PR title becomes the commit on `main`), then delete the branch.

The repository is private on GitHub's free plan, which does not offer branch protection, so these rules are a team agreement rather than something GitHub enforces. Reviewers and authors are both responsible for holding to them.

### Commit messages

Commits follow Conventional Commits too: `type(scope): imperative summary` under ~72 characters, with a body explaining *why* when it isn't obvious. Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `ci`, `chore`, `build`, `revert`. Scopes are the area touched (`quiz`, `graph`, `rag`, `db`, `frontend`, ...).

### Issues

Use the issue templates: **Feature / user story** (story, acceptance criteria, design) or **Bug report** (steps to reproduce, environment, request ID). Label with area (`frontend`, `backend`, `agents`, ...) and priority (`P0`-`P3`).

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