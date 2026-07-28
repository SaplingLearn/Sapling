# Chapter 2: exploratory testing

This is the runbook for Sapling's Chapter 2 — LLM-driven exploratory testing
of the running app. Read this before your first `make explore`.

## 1. What this is

Sapling has two E2E chapters, and they answer different questions.

| | Chapter 1 | Chapter 2 |
|---|---|---|
| What it is | Scripted, deterministic journeys | LLM-driven exploration |
| Where it lives | `frontend/e2e/*.spec.ts` (Playwright) | `scripts/explore.sh`, `.claude/skills/explore/`, `backend/e2e_oracles/` |
| Gates CI? | Yes — `.github/workflows/e2e.yml`, main-only | Never |
| Runs when | Every push to main | On demand, local-only (`make explore` / `/explore`) |
| Judge | Fixed assertions + `support/db.ts` raw SQL | The e2e oracles (`backend/e2e_oracles`) or a reproducible captured failure |

Chapter 2 exists because a scripted suite only ever re-checks what someone
already thought to assert. An LLM with a real browser will click things,
double-submit forms, hit Back mid-flow, and generally behave like a curious
student — surfacing bugs nobody wrote a journey for yet.

The core rule, verbatim from the epic (#403), governs everything below:

> The LLM explores; only oracles (or a reproducible captured failure) make
> something a finding.

That's why every exploration session ends with a deterministic oracle pass,
and why the triage protocol (§7) insists on reproduction before anything
becomes a GitHub issue. The explorer's own prose is a lead, not a verdict.

## 2. Prerequisites

Everything Chapter 1's local stack needs (see
[local-supabase.md](local-supabase.md)), plus two things specific to Chapter 2:

- Supabase CLI on `PATH`
- Rootless Podman (documented) or Docker (auto-detected fallback)
- `backend/venv` (`python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt`)
- `frontend/node_modules` (`cd frontend && npm ci`)
- `backend/.env` with `APP_ENV=local` (or `test`) — without it, `POST
  /api/auth/test-login` 404s and the harness can't mint a session
- The `claude` CLI on `PATH` (drives the headless explorer via `claude -p`)
- Network access for the first run — `npx` downloads and pins
  `@playwright/mcp@0.0.78` the first time it's invoked; afterward it's cached

You do **not** need to set a real `GEMINI_API_KEY` or `SEED_RICH` yourself —
`scripts/explore.sh` forces both. A real key in your shell is not
used and never billed by this harness.

## 3. Kick-off: headless

```bash
make explore
```

This runs the full pipeline: boot the stack, mint a session, hand the
explorer prompt to a Playwright-MCP-armed `claude -p`, run the oracle final
pass, then tear everything down. It takes the machine-singleton stack lock
for the whole run (see §10). With warm caches (a repo you've already run
`make e2e-up` or `make explore` on before), the whole thing typically
finishes in a few minutes end-to-end; the first-ever run on a machine can
take closer to ~10 minutes (see §9's cost note — it's the `npx
@playwright/mcp` download plus a cold test-profile Next build, not the
exploration itself).

Env knobs (all optional, read by `scripts/explore.sh`):

| Knob | Default | Meaning |
|---|---|---|
| `EXPLORE_MAX_TURNS` | `40` | Turn budget passed to `claude -p --max-turns`. Bounds both wall-clock and token cost. |
| `EXPLORE_MODEL` | `sonnet` | Model alias passed to `claude -p --model`. |
| `EXPLORE_HEADED` | `0` | `1` = watch the browser drive itself (non-headless); `0` = headless. |
| `EXPLORE_USER` | `rich-user-active` | Which seeded `rich-*` user to sign in as. One of `rich-user-active`, `rich-user-second`, `rich-user-new`, `rich-user-pending`, `rich-user-admin`. |

Example: a slower, watchable run as a different seeded user:

```bash
EXPLORE_HEADED=1 EXPLORE_USER=rich-user-admin EXPLORE_MAX_TURNS=60 make explore
```

Two things worth internalizing before your first run:

- **`.explore/` is wiped at `up`, but only after the lock is acquired.** If
  you want to keep a previous run's findings, triage them (§7) before
  re-running — a second `make explore` deletes the prior artifacts (except
  the in-flight `lock.ok`, which is bookkeeping, not a finding).
- **A crashed run is recoverable.** If a prior `make explore` died mid-run
  (killed session, machine sleep, whatever), `make explore-down` (same as
  `scripts/explore.sh down`) runs the oracle final pass against whatever is
  still up, appends it to `findings.md`, tears the stack down, and releases
  the lock — safe to run even with nothing up.

## 4. Kick-off: interactive

```
/explore
```

Run this as a slash command in a Claude Code session opened on this repo.
Unlike `make explore`, you watch (and can steer) the exploration live:

1. The skill runs `scripts/explore.sh up` itself (this takes minutes —
   Supabase, migrations, seed, backend, a test-profile Next build — and takes
   the same stack lock `make explore` does; if another session holds it, the
   skill stops and tells you).
2. It opens a real browser tab (Playwright MCP if configured for the session,
   else the Claude-in-Chrome tools) at `http://localhost:3000` and signs in as
   `rich-user-active` by minting a session directly from the page.
3. It reads `scripts/explore/explorer-prompt.md` as its own mission briefing
   and starts exploring — narrating what it's trying so you can redirect it
   at any point. Same persona, same break-things mandate, same
   report-never-fix rule, same oracle cadence, same findings format as the
   headless run.
4. It finishes with `scripts/explore.sh down` — same oracle final pass,
   same teardown, same lock release.

The output is identical in shape to a headless run: `.explore/findings.md`
with explorer-written entries plus the harness-appended oracle pass. The only
difference is you're in the loop instead of reading a transcript after the
fact.

## 5. Outputs

Everything lands in `.explore/` at the repo root (gitignored in full):

| Path | What it is |
|---|---|
| `findings.md` | The running human-readable findings log — explorer-written `### F<N>:` entries plus a harness-appended `## Oracle final pass` section at teardown. Pre-created by the harness with a header so the explorer always has an existing file to append to. |
| `session.log` | The full headless-run transcript: `claude -p --output-format stream-json --verbose`, reformatted by `jq` into readable `[assistant]` / `[tool_use]` / `[tool_result]` / `[result]` lines (each truncated to 500 chars). |
| `session.stderr.log` | `claude -p`'s stderr, kept in its own file so it can never interleave with (and corrupt) the JSON stream `session.log` is parsed from. |
| `oracle-final.txt` / `oracle-final.json` | The final `python -m e2e_oracles` pass, run at teardown while the stack is still up, in both text and JSON form. |
| `traces/` | `@playwright/mcp` session-recording artifacts (page snapshots plus an MCP session directory) — these are MCP session recordings, not Playwright Trace Viewer `.zip` files. |
| `storageState.json`, `mcp.json` | Plumbing, not findings: the minted Playwright storage state and the `--mcp-config` fed to `claude -p`. Useful for debugging why the explorer couldn't reach a page, otherwise ignorable. |
| `lock.ok` | Internal lock-holder bookkeeping (holder-written, self-identifying — its content is the holder process's own PID). Not a finding artifact. |

## 6. The oracles, standalone

The explorer runs the oracles as it goes, and the harness runs one final pass
at teardown — but you can also run them yourself against a stack that's
already up (e.g. mid-`/explore`, or after driving the app by hand):

```bash
cd backend && venv/bin/python -m e2e_oracles [--json] [--check ciphertext|counts|graph|logscan|orphans] [--user ID]
```

- `--check` is repeatable; omit it to run all five (default, sorted order).
- `--json` emits structured `Finding` records instead of the text report —
  useful when quoting evidence into a GitHub issue.
- `--user` selects which seeded user's data to check (default
  `rich-user-active`).
- Exit codes: `0` clean, `1` findings, `2` infra error (a check crashed, or
  itself returned an `oracle-error` finding — treat the whole run's other
  results as untrustworthy when this happens, not just the failing check).
- Needs the stack up (`make e2e-up` or `scripts/explore.sh up`) — it hits the
  local Postgres directly and the backend's `/api/health`-adjacent surface.
- The `logscan` check allowlists known #439 RAG-indexing log noise — an
  allowlisted hit still counts toward "N suppressed" in the summary line, but
  doesn't produce a `Finding`.

## 7. Triage protocol

For each entry in `findings.md` (explorer-written or oracle-appended):

1. **Reproduce it.** By hand in a browser, or by re-running the relevant
   oracle `--check`. Not reproducible → drop it, with a one-line note in your
   triage record of why. Part of reproducing it is asking whether the
   "wrong" output is actually the function-mode seam working as designed
   (see the worked example below) — that's a drop too, just a different
   reason than "couldn't reproduce."
2. **Reproducible and real** → `gh issue create` with the finding block
   (steps/expected/actual), the oracle JSON if there is any, and the
   `.explore/traces/` path attached. Label it as sourced from exploration so
   it's traceable back to a session.
3. **Already-known** (currently: #355, #430, #435, #436, #439, #441) → don't
   file a new issue. Add the new evidence as a comment on the existing issue
   only if it's actually new evidence (a different surface, a clearer repro,
   fresh oracle output) — otherwise it's just noise on an already-tracked bug.
4. **Noise the oracle wrongly flagged** → that's a bug in the oracle itself
   (a missing allowlist entry, or a judge that's too strict/wrong). Fix it as
   a normal PR against `backend/e2e_oracles/` — don't just delete the finding
   from `findings.md` and move on.

Two worked examples from this harness's own acceptance testing show the
difference between a genuine finding and noise the *harness itself*
(not the oracle) produced:

**Genuine, promotable (category 2).** Resuming a tutor session in one
acceptance run produced a real `500` on `POST
/api/graph/<user>/concept-description`, traced through the browser console →
network tab → backend log to `LookupError: SAPLING_MODEL_MODE=function but
no handler is registered for task 'concept_describe'` — `concept_describe`
genuinely has no handler in `backend/agents/function_handlers_e2e.py`. The
`logscan` oracle independently caught the same `500` and traceback in the
backend log, so this has both a UI-observed repro and oracle corroboration.
It isn't on the known-bugs list — exactly the kind of thing this chapter
exists to surface, and a strong promotion candidate (§8).

**Seam artifact — drop it, then improve the harness, not the app (still
category 1).** A different run's explorer flagged what looked like a
"wrong-data" bug: uploading a real syllabus PDF came back with a summary
about gradient descent, category "Lecture notes", and concepts "Gradient
Descent"/"Learning Rate" — content belonging to an entirely different,
already-uploaded document. Alarming-looking, but not a product bug: Chapter
2 always runs the document pipeline in function mode
(`SAPLING_MODEL_MODE=function` /
`SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e`, forced by
`scripts/explore.sh`), and
`agents/function_handlers_e2e.py`'s classifier/summary/concepts handlers are
*designed* to return the same fixed constants
(`E2E_DOC_CATEGORY`/`E2E_DOC_ABSTRACT`/`E2E_DOC_CONCEPTS`) for every upload
regardless of the file's real content — the module's own docstring says so
("Fixed output... Echoing request content back would couple the constant to
route-side prompt assembly"). The pipeline was working exactly as designed;
the explorer just didn't know that. **The tell:** the "wrong" text is a
byte-for-byte match to one of `function_handlers_e2e.py`'s `E2E_DOC_*` (or
`E2E_TUTOR_REPLY`, `E2E_QUIZ_*`) constants — here, `E2E_DOC_ABSTRACT`'s
"gradient descent... loss surface... learning rate" wording and the fixed
`lecture_notes` category. If a finding's "wrong" content matches one of
those constants verbatim, it's the seam, not the app — drop it, and if it
recurs, improve `scripts/explore/explorer-prompt.md`'s ground rules to name
the pattern explicitly so a future explorer recognizes it before writing the
stub, rather than filing an issue against the harness's own known-fixed
output.

By contrast, #355 (the graph's duplicated CS subject-root hub) shows up in
the graph oracle on essentially every run against the rich seed data —
that's the known-not-new case category 3 above exists for.

## 8. Promotion pipeline

Triage produces GitHub issues; the pipeline that actually matters is turning
the *right* ones into permanent regression coverage. The epic bar (#403):
**at least 3 findings promoted into Chapter 1 regressions in the first
month.**

Promotion path: issue → a scripted journey in `frontend/e2e/*.spec.ts`,
written in the existing specs' style —

- Fixtures-based `test` (see `frontend/e2e/support/fixtures.ts`), not raw
  Playwright boilerplate.
- Assertions against the database go through `support/db.ts` (raw SQL over a
  direct Postgres connection) — journeys never hand-roll DB plumbing.
- Any new `data-testid` follows `docs/frontend-testids.md`'s naming
  convention; see that doc's "Adding a surface" section for the doc-row +
  `eslint.config.mjs` `files`-array update a new surface needs.
  `npm run lint:baseline` is only for clearing legacy debt in
  `eslint-suppressions.json`, not something a new surface should lean on.

If the promoted journey documents a bug that's still open and must stay red,
ride it in on `test.fixme` with the bug number — exactly how
`frontend/e2e/graph.spec.ts` carries its `#355` assertion today (marked
`fixme`, not relaxed, with companion tests asserting everything #355 does
*not* corrupt).

## 9. Cadence + cost

Suggested cadence: one bounded headless run a week, plus one after any merge
you'd call risky (auth, graph, upload/extraction, or anything touching the
Gemini/function-handler seam).

Cost is bounded but real: each run spends actual Claude tokens (bounded by
`EXPLORE_MAX_TURNS` — the default 40-turn budget is the knob to shrink if
you're cost-conscious). Wall-clock is warm-cache-dependent: observed full
runs (boot → explore → oracle → teardown) land in the 2-4 minute range with
a warm Next build and an already-cached `@playwright/mcp`; budget closer to
~10 minutes for the very first run on a machine, which additionally pays for
the `npx @playwright/mcp` download and a cold test-profile Next build (see
§3).

## 10. Lock protocol & hygiene

The local E2E stack is a **machine singleton** — one Postgres, one backend,
one frontend, bound to fixed local ports. `scripts/explore.sh` enforces this
by holding an `flock` on `/tmp/claude-<uid>/sapling-e2e-stack.lock` for the
entire session (both the headless full pipeline and the interactive
`up`/`down` pair).

Rules that follow from that:

- **Never run two explorations at once** on the same machine — the second
  one fails fast with "stack lock busy" and touches nothing (no wipe, no
  teardown of the first session's stack).
- **Never run an exploration alongside the Chapter 1 Playwright suite** —
  both want the same stack and the same ports.
- **Always end a session via `down`.** For `make explore` this happens
  automatically. For `/explore` or a manual `scripts/explore.sh up`, that
  means `make explore-down` (or `scripts/explore.sh down`) — every time,
  even after an error. Skipping it leaks both the running stack and the
  lock, which then blocks every future exploration until someone runs
  `explore-down` by hand.

## 11. Troubleshooting

- **"e2e stack lock busy"** — another session (yours or someone else's on
  the same machine) is already exploring or mid-`up`. Find and finish it, or
  run `make explore-down` if you're sure it's actually a stale/crashed run.
- **`POST /api/auth/test-login` 404s** — `backend/.env`'s `APP_ENV` is not
  `local` or `test`. This route is hard-gated on that check; fix `.env` and
  restart the backend.
- **The explorer never seemed to drive the browser** (`session.log` has no
  `[tool_use] mcp__playwright__*` lines) — check `.explore/mcp.json`'s flags
  against `npx -y @playwright/mcp@0.0.78 --help`; in particular confirm
  `--isolated` is present (without it, the MCP server reuses one persistent
  Chrome profile per repo path and silently ignores `--storage-state` on a
  reused context — the historical #399 follow-up bug this harness had to
  fix).
- **Oracle exits 2** — either the stack isn't actually up (`make e2e-up`
  first, or check `.e2e/*.log`), or the DB URL the oracle resolved isn't
  pointed at the local stack. Re-run with `--json` to see which check raised.
- **Stale `.explore/` from a previous run** — don't worry about manually
  cleaning it; the next `up` wipes everything except `lock.ok` before
  writing fresh artifacts. Triage anything you care about first (§7).
