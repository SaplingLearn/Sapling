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
   - Every ready PR needs filled-in **acceptance criteria** (copy them from the issue). `feat` and `fix` PRs also include a **user story**. UI changes include before/after screenshots.
   - The `PR hygiene` workflow (`.github/workflows/pr-hygiene.yml`) fails a PR with no type (neither a Conventional Commits title nor a `type/` branch) or, once it is ready for review, no filled-in acceptance criteria / test plan section. It warns when a `feat`/`fix` PR has no user story, and adds a type label (`enhancement`, `bug`, `documentation`, `tech-debt`, ...).
   - Open the PR as a **draft** while it is in progress; mark it ready when it meets its acceptance criteria.
4. **Request a review from at least one teammate, and wait for their approval** before merging. Do not merge your own unreviewed PR. Reviewers check the acceptance criteria, not just the diff.
5. **CI must pass** before merge (backend pytest + ruff, frontend eslint + typecheck + vitest, PR hygiene, plus any E2E/eval workflows that apply to your change).
6. Merge with a merge commit or squash, then delete the branch. A merge commit keeps every branch commit on `main`, so branch commits must follow the commit-message format below too; a squash uses the PR title.

`main` is covered by a GitHub ruleset ("Require PR review before merge"): no direct pushes, no force-pushes, no deletion, and one approving review before a PR can merge. Organization admins can bypass it; don't, except to recover from an emergency, and say so in the PR.

### Commit messages

Commits follow Conventional Commits too: `type(scope): imperative summary` under ~72 characters, with a body explaining *why* when it isn't obvious. Types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `ci`, `chore`, `build`, `revert`. Scopes are the area touched (`quiz`, `graph`, `rag`, `db`, `frontend`, ...). Add `!` after the scope for a breaking change. Examples from `main`:

```
fix(quiz): a written type outside the known formats is plain text again
refactor(frontend): share courseSelectOptions between flashcard import and study guide pickers
docs(complexity): Onboarding (51) from main stays baselined as a follow-up
```

Git's own merge commits (`Merge origin/main into ...`, `Merge pull request #N ...`) are fine as they are. Nothing lints commit messages automatically; reviewers check them, and the `PR hygiene` check covers the PR title.

### Issues

Use the issue templates: **Feature / user story** (story, acceptance criteria, design) or **Bug report** (steps to reproduce, environment, request ID). Label with area (`frontend`, `backend`, `agents`, ...) and priority (`P0`-`P3`).

## Before you open a PR

Backend (from `backend/`):

```
python -m pytest tests/ -q --ignore=tests/evals \
  --ignore=tests/test_docling_integration.py \
  --ignore=tests/test_ocr_pipeline.py \
  --ignore=tests/test_extraction_backends.py
ruff check .
python scripts/lint_ratchet.py   # fails on a NEW blind except / bugbear / async-blocking violation in any file
lint-imports
python scripts/type_ratchet.py   # needs node; fails on a NEW pyright error
```

Frontend (from `frontend/`):

```
npm run lint        # CI runs it with --max-warnings=0; every rule is an error, old violations are baselined
npm run typecheck
npm test            # includes the complexity and file-size ratchets
```

A source file over 800 lines fails lint, and a file already over it (listed in
`frontend/max-lines-baseline.json`) may not grow: move new code into its own
module. After shrinking one, run `npm run max-lines:shrink` and commit the
baseline.

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