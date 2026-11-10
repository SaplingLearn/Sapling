<!--
PR title must follow Conventional Commits, e.g. `feat(quiz): add a question pager`.
Allowed types: feat, fix, docs, refactor, perf, test, ci, chore, build, revert.
The `PR hygiene` check needs a type (title or `type/` branch) and, once the PR is ready, a filled-in Acceptance criteria (or How to test) section. It adds a matching label.
-->

## Summary

What this PR does and why, in two or three sentences.

Closes #

## User story

<!-- Required for feat and fix PRs. Delete for docs/chore/ci/test/refactor. -->

As a **<type of student/user>**, I want **<goal>** so that **<benefit>**.

## Acceptance criteria

<!-- Required for every PR that is ready for review: concrete, checkable outcomes. -->

- [ ] 
- [ ] 

## Changes

- 

## Design / screenshots

<!-- UI changes: before/after screenshots or a short clip, plus the Figma frame if there is one. -->

## How to test

1. 

## Checklist

- [ ] Tests added or updated (bug fixes include a test that fails without the fix)
- [ ] `pytest` + `ruff check .` pass (backend) / `npm run lint && npm run typecheck && npm test` pass (frontend)
- [ ] New env vars documented in the matching `.env.example` and the README
- [ ] Schema changes are a new migration (no edits to applied ones)
- [ ] At least one teammate has reviewed and approved
