# Load test (#117)

A [locust](https://locust.io) script for the measurement loop in
`docs/design/async-db-client.md` §1: p95 per route and the tutor's time to
first token, before and after each async-DB wave.

| Locust name | What it hits |
|---|---|
| `GET /api/health` | unauthenticated liveness |
| `GET /api/flags` | an authenticated read (session guard + flag snapshot) |
| `GET /api/quiz/attempts` | the quiz history list, the first read on the async DB seam |
| `chat_stream TTFT` | `POST /api/learn/chat/stream`: time from request to the first `token` SSE event |
| `chat_stream full` | the same turn, to the end of the stream |

There is **no default target**. The script refuses to start without `--host`,
and the GitHub workflow refuses to run without `target_url`.

## Local run (the deterministic stack)

```
make e2e-up    # function-mode LLM seam, rich seed (see docs/local-supabase.md)
uv venv .venv-loadtest && uv pip install --python .venv-loadtest --require-hashes -r loadtest/requirements.lock
.venv-loadtest/bin/locust -f loadtest/locustfile.py --host http://localhost:5000 \
    --headless -u 20 -r 5 -t 2m --csv loadtest/out/run --html loadtest/out/report.html
make e2e-down
```

Hold the stack lock for the whole cycle (CLAUDE.md, "The local E2E stack is a
machine singleton"). Sessions come from `POST /api/auth/test-login`, which
exists only on `APP_ENV=local|test`; elsewhere pass a pre-minted
`LOADTEST_SESSION_TOKEN`.

### One token = one student (single-user mode)

A `sapling_session` token authenticates exactly one `user_id`, and the
routes under test check that the session IS the user they are asked about
(`require_self`). So when `LOADTEST_SESSION_TOKEN` is set, every simulated
user acts as the token's own `user_id` (read from the token's payload) and
`LOADTEST_USER_IDS` is ignored; the script says so at start. Spreading load
over several students needs `/api/auth/test-login` (one session per user id).
Single-user mode concentrates every request on one student, so per-student
guards (rate limits, the LLM budget) see the whole run as one student; read
any `429`s in that light.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `LOADTEST_USER_IDS` | `rich-user-active` | comma list of seeded users; simulated users take them in turn (ignored with `LOADTEST_SESSION_TOKEN`) |
| `LOADTEST_TEST_LOGIN` | `1` | mint sessions through `/api/auth/test-login` |
| `LOADTEST_SESSION_TOKEN` | unset | a `sapling_session` token to use instead: single-user mode, every simulated user is the token's `user_id` |
| `LOADTEST_TUTOR_SESSION` | unset | an existing tutor session id; unset, each user starts one |
| `LOADTEST_CHAT` | `1` | `0` drops the chat task (reads only) |

The chat task writes tutor messages and, outside function mode, spends LLM
budget. Do not point this at staging or production without the owner's
say-so.

## CI

`.github/workflows/loadtest.yml` is `workflow_dispatch` only (never on push or
PR; the scheduled run is the separate nightly workflow below). It takes a required `target_url`, plus users, spawn
rate, duration, the user ids, and whether to include the chat task (off by
default). Results (CSV + HTML) are uploaded as the `loadtest-results`
artifact. An optional `LOADTEST_SESSION_TOKEN` repository secret signs the
users in on targets without `/api/auth/test-login`; with it set the run is
single-user (the `user_ids` input is ignored, see above).

### Nightly

`.github/workflows/loadtest-nightly.yml` runs the same mix every night at
07:17 UTC (and on demand), but ONLY when the repository variable
`LOADTEST_TARGET_URL` is set; unset, the job is skipped and nothing is sent.
Its other knobs are repository variables too: `LOADTEST_USERS` (20),
`LOADTEST_SPAWN_RATE` (5), `LOADTEST_DURATION` (3m), `LOADTEST_CHAT` (1:
include the chat task and require TTFT samples) and `LOADTEST_USER_IDS`; the
`LOADTEST_SESSION_TOKEN` secret works as above. The run FAILS when a target
below is missed, and uploads the CSVs, the HTML report and the threshold
report as the `loadtest-nightly-results` artifact. Point it only at a stack
whose owner agreed to a nightly load.

## Reading the numbers

The plan's targets: p95 under 300 ms for the non-LLM routes, and chat TTFT p95
under 3 s. `check_thresholds.py` checks them on locust's stats CSV (stdlib
only; the nightly job runs it, and so can you after a local run):

```
python loadtest/check_thresholds.py loadtest/out/run_stats.csv --require-chat
```

| Check | Rows | Default |
|---|---|---|
| p95 under `--max-p95-ms` | every route except the tutor's LLM calls (`chat_stream *`, `POST /api/learn/...`, `learn start-session`) and the `auth test-login` setup | 300 ms |
| p95 under `--max-ttft-p95-ms` | `chat_stream TTFT` (missing samples fail only with `--require-chat`) | 3000 ms |
| failure ratio at most `--max-failure-ratio` | every row (a run that bounces off a 401 in 5 ms is not fast) | 1% |

Exit 0 = every target met, 1 = a target missed (listed on stderr), 2 = the CSV
could not be read. The logic is unit-tested in
`backend/tests/test_loadtest_thresholds.py`. The per-route p95 comes straight
from locust's own percentile columns.

Compare against a stored baseline at the same concurrency, with the same
`async_db_client` / `stateless_rate_limit` / `stateless_locks` /
`stateless_tutor_sessions` flag values and replica count; a flag flip is a
different run.
