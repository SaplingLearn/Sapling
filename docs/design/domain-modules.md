# Domain modules (architecture-hardening Phase 4)

As of 2026-11-08. Tracked in Trov ticket #118. Plan: `docs/architecture-hardening-plan.md`, Phase 4, which is done when **no route file is over 600 lines and no function is over complexity 25**.

This page sets the target layout, lists what misses the target today, and gives the order to split it in. The ratchet in this PR stops the numbers from growing while the splits wait. It does not move any code out of the large route files.

## The ratchet

| What | Limit | Enforced by | Baseline |
| --- | --- | --- | --- |
| Function complexity (ruff `C901`, McCabe) | 25 | `ruff check .` for files with no baselined function; `tests/test_code_size_ratchet.py` for every function | `backend/code_size_baseline.json` → `complexity` (`<file>::<qualname>`: ceiling) |
| Route file length (`backend/routes/**/*.py`) | 600 lines | `tests/test_code_size_ratchet.py` | `backend/code_size_baseline.json` → `route_file_lines` (`<file>`: ceiling) |

The logic lives in `backend/scripts/code_size_ratchet.py`. The rules:

- A new function over 25 or a new route file over 600 lines fails, wherever it is.
- A baselined function or file fails if it goes over its own ceiling. A file at 3,145 lines may not reach 3,146.
- Functions are keyed by file and qualname: `Class.method` for a method, `outer.<locals>.inner` for a nested function. Two functions with the same name are each held to their own ceiling. Only a true redefinition (the same qualname twice in one file) is numbered, `name#2`, in source order.
- Going down is always allowed and never fails. The test warns (it does not fail, so two PRs that each shrink a file cannot leave main red between them) and asks you to lock the gain in: `python scripts/code_size_ratchet.py --shrink` (from `backend/`) lowers each entry to today's number and deletes the ones back under the limit. It never adds or raises one, and it exits 1 and prints any violation still left after the write.
- `--shrink` cannot re-key. A move-only split that renames a file or function must move its baseline key (and the file's `ruff.toml` `C901` entry) by hand in the same PR. Otherwise the moved code fails as a new offender and the old key reads as slack.
- Raising a ceiling is a hand edit to the JSON. The reviewer sees it in the diff and must accept it. Prefer moving the new code into a service module instead (layout below).
- ruff can only exempt whole files, so `ruff.toml` lists `C901` in `per-file-ignores` for each file that still holds a baselined function. The test fails if that list and the JSON disagree, so a cleaned-up file loses its exemption.
- The per-function check runs `ruff --isolated` with only `C901` selected and `# noqa` switched off, so nothing in `ruff.toml` (excludes, includes, per-file-ignores, `extend-per-file-ignores`, ignore lists) and no inline or file-level noqa can hide a function. A second test fails if `ruff.toml` gains any such setting, so plain `ruff check .` cannot be fooled either.
- Test code (`backend/tests/`) is out of scope for the complexity limit. `ruff.toml` exempts it with a `"tests/**"` entry, and the script excludes it from its ruff run.

### Which complexity number

The ratchet uses ruff's McCabe count because ruff already runs in CI. McCabe counts branches (`if`, loops, `except`, `with`, comprehensions). It does **not** count `and`/`or`, so it reads lower than radon or lizard on the same code. The plan's "12 functions above complexity 30" was a branch-plus-boolean count. An ad hoc estimate of that kind still gives 13 functions above 30 and 21 above 25. Under ruff's McCabe count only 2 functions are above 25 (table below).

So the complexity half of Phase 4 is nearly met under the metric CI can enforce. The hard part of Phase 4 is file length. Once the splits below land, lower `[lint.mccabe] max-complexity` in steps (for example 20, then 15), re-baselining each time, to get the intent of the original target.

## Current offenders (recorded ceilings, top of the wave-2 stack, 2026-11-08)

These are the numbers in `code_size_baseline.json`, recorded with every wave-2 PR applied. Wave 2 grew several of these files, and moved `routes/admin_analytics.py` over the limit.

### Route files over 600 lines

| File | Lines | Endpoints | Open work touching it | Notes |
| --- | ---: | ---: | --- | --- |
| `routes/quiz.py` | 3,145 | 7 | #750, #752, #673, #735, #801, wave-2 W7 | 48 top-level functions; `services/quiz_*.py` already holds 10 quiz modules |
| `routes/learn.py` | 2,001 | 11 | #751, #752, #673, #735, #801 | Tutor routes; streaming already lives in `services/chat_stream.py` |
| `routes/documents.py` | 1,468 | 7 | #717, #752, #755, #673, #735, #801, wave-2 W4, W6a, W7 | Upload pipeline; indexing already lives in `services/document_indexing.py` |
| `routes/auth.py` | 1,173 | 8 | #752, #801, wave-2 W5a | OAuth callback, pending/waitlist, test login, local seed |
| `routes/social.py` | 1,122 | 24 | #752, #801 | Rooms, room messages, matching, friends |
| `routes/admin.py` | 1,005 | 38 | #752, #801 | Roles, achievements, cosmetics, XP rules, users/allowlist, feedback, audit, analytics |
| `routes/profile.py` | 933 | 15 | #673, #735, #752, #801, wave-2 W4 | Profile, settings, cosmetics, achievements, account delete/export |
| `routes/gradescope.py` | 826 | 9 | #752, #801, wave-2 W6c | Credentials, course links, sync |
| `routes/admin_analytics.py` | 660 | 6 | #799, wave-2 W5b, W7 | Usage/cost rollups, errors, db-scope shadow report; was 495 before wave 2 |
| `routes/gradebook.py` | 649 | 12 | none | Categories, assignments, scale/curve, GPA; `services/gradebook_service.py` exists |
| `routes/flashcards.py` | 658 | 9 | #673, #735, #752, #801, wave-2 W4 | Generate/rate plus the import flow (`services/flashcard_import_service.py` exists) |

### Functions over complexity 25 (ruff McCabe)

| Function | Score | Open work touching the file |
| --- | ---: | --- |
| `services/graph_service.py::apply_graph_update` | 28 | #673, #735, #752, #801 |
| `services/achievement_service.py::_get_user_stat` | 26 | #673, #735, #752, #801 |

This PR took `scripts/migration_drift_report.py::main` from 29 to 12 by moving its ALREADY EXISTS and DATA BLOCKERS sections into their own functions. Byte-exact characterization tests in `tests/test_migration_drift_report.py` pin the output.

The next-highest functions, all between 20 and 25, are on the watch list. They pass today but have little room: `promotion/runner.py::run` (24), `services/gradescope_service.py::login_via_bu_sso`, `services/course_context_service.py::update_course_context`, `services/account_bundle.py::import_account` and `routes/quiz.py::_quiz_via_agent` (23 each), `routes/auth.py::google_callback` and `services/chat_stream.py::stream_agent_turn` (22 each), `services/email_service.py::send_email` and `routes/documents.py::upload_document` (21 each), and `routes/quiz.py::submit_quiz` (20).

## Target layout

```
backend/
  routes/<area>.py            thin HTTP layer, 600 lines or fewer
  services/<domain>/
    __init__.py               the domain's public functions; routes import only these
    <topic>.py                logic and data access
```

A route handler does four things: it parses the request (Pydantic body and query params), checks the caller (`require_self` / `require_admin` / `require_flag`), calls one service function, and maps the result or domain error to a response or `HTTPException`. Everything else moves to the domain package: reading and writing rows, decrypting, assembling payloads, calling agents and emitting events.

Rules for the domain packages:

- **No `fastapi` imports in a domain package.** Raise a domain error (a small exception class in the package) and let the route map it to a status code. Nine flat `services/*.py` modules import `fastapi` today. They are moved over only when their domain is split, not in a separate pass.
- **The existing chokepoints still apply.** Use `table()` (or the `db/scope.py` user-scoped client when `db_user_scope` is on), `apply_graph_update`, `services/academics.py`, the encryption helpers and `report_empty_result`. A split moves code; it does not change how that code reaches the database or the models.
- **Domain packages do not import routes.** Cross-domain calls go through the other package's `__init__`.
- **Existing flat modules move into their package when the domain is split.** For example, `services/quiz_*.py` moves to `services/quiz/` in the quiz split. Keep no re-export shims. Update the imports and the test patch targets in the same PR.
- **Patch targets move with the code.** Route tests patch names on the route module (`patch("routes.gradebook.table", ...)`; the tests reference `routes.quiz.` about 400 times). A split must repoint each patch to where the name is now looked up, or the test silently stops intercepting. Moving a function without its patches is the most likely way for a split to break tests.

## Split order

Rule: **split a file only when no open PR touches it.** A split rewrites most of a file, so every open PR on that file would need a rebase. Check before starting:

```
gh pr list --state open --json number,files --jq '.[] | select(any(.files[]; .path == "backend/routes/<file>.py")) | .number'
```

(For PRs with more than 100 files, use `gh api --paginate repos/SaplingLearn/sapling/pulls/<n>/files`, because `gh pr list` truncates at 100.)

1. **`routes/gradebook.py` → `services/gradebook/`.** No open PR touches it. It is just over the limit (649), and `services/gradebook_service.py` already holds the grade math. Move the enrollment and ownership loaders (`_resolve_enrollment`, `_load_*`, `_owned_*`, `_enrollment_grade`) and the syllabus apply into the package. Good first split to prove the pattern and the patch-target migration.
2. **`routes/social.py` → `services/social/` (rooms, messages, friends, matching).** It has 24 endpoints in three clear groups. Today only #752 and #801 touch it. Split once those land.
3. **`routes/admin.py` → `services/admin/` (roles, achievements, cosmetics, users and allowlist).** It has 38 endpoints, all thin CRUD, so it splits mechanically. It waits on #752 and #801.
4. **`routes/gradescope.py` and `routes/flashcards.py`.** Both are just over the limit, and both have service modules already. They wait on #752, #801, wave-2 W6c (gradescope job) and W4 (flashcards).
5. **`routes/admin_analytics.py` → `services/admin/analytics/`.** Wave 2 took it from 495 to 660 lines (W5b's db-scope shadow report, W7's cost per active user). Its six endpoints are read-only rollups, so the aggregation helpers (`_scan_range`, the series builders, `_db_scope_key`) move out mechanically. It waits on #799 and on wave 2 landing; it can share a PR with the `routes/admin.py` split.
6. **`routes/profile.py`, then `routes/auth.py`.** Profile waits on #673, #735, #752, #801 and wave-2 W4. Auth waits on #752, #801 and wave-2 W5a. Keep `google_callback` (22) behaviour-pinned by the existing auth tests while splitting it.
7. **`routes/documents.py` → `services/documents/`.** The upload pipeline and scan-concepts move out. It waits on #673, #717, #735, #752, #755, #801 and wave-2 W4, W6a and W7.
8. **`routes/quiz.py` and `routes/learn.py`, last.** **These wait until #750, #751 and #752 and the learning-loop PRs (#673, #801, plus #735) have landed**, plus wave-2 W7 for quiz. They are the two largest files and the most actively edited, and each of those PRs edits one or both. Quiz becomes `services/quiz/` (absorbing the ten `services/quiz_*.py` modules). Learn becomes `services/tutor/` (next to `chat_stream.py`, `tutor_router.py` and `tutor_sessions.py`). Plan each as a series of PRs, one topic at a time, not one big move.

The two over-25 functions sit in `services/graph_service.py` and `services/achievement_service.py`. Four open PRs (#673, #735, #752, #801) touch both files, so leave them until those land. `apply_graph_update` is the graph-mutation chokepoint, so split it only with its full test file green and the E2E graph oracle run.

## Each split PR

- Move code only, with no behaviour change. If a bug turns up, fix it in a separate PR.
- Run `python scripts/code_size_ratchet.py --shrink` and commit the lower baseline. The ratchet test warns until you do.
- A move-only split must move the baseline key and the `ruff.toml` `C901` entry in the same PR. `--shrink` only lowers or deletes entries; it cannot re-key one. If a function over 25 moves from `services/graph_service.py` to `services/graph/update.py`, rename its `code_size_baseline.json` key to the new path and move the file's `C901` per-file-ignores line with it. A route file that is split below 600 lines just loses its entry (`--shrink` deletes it).
- Pass the hermetic suite, then the E2E lane and oracles for any file in E2E-covered territory (per `CLAUDE.md`).
- Move `CLAUDE.md` repo-map entries that name a moved function in the same PR.
