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

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `LOADTEST_USER_IDS` | `rich-user-active` | comma list of seeded users; simulated users take them in turn |
| `LOADTEST_TEST_LOGIN` | `1` | mint sessions through `/api/auth/test-login` |
| `LOADTEST_SESSION_TOKEN` | unset | a `sapling_session` token to use instead |
| `LOADTEST_TUTOR_SESSION` | unset | an existing tutor session id; unset, each user starts one |
| `LOADTEST_CHAT` | `1` | `0` drops the chat task (reads only) |

The chat task writes tutor messages and, outside function mode, spends LLM
budget. Do not point this at staging or production without the owner's
say-so.

## CI

`.github/workflows/loadtest.yml` is `workflow_dispatch` only (never scheduled,
never on push or PR). It takes a required `target_url`, plus users, spawn
rate, duration, the user ids, and whether to include the chat task (off by
default). Results (CSV + HTML) are uploaded as the `loadtest-results`
artifact. An optional `LOADTEST_SESSION_TOKEN` repository secret signs the
users in on targets without `/api/auth/test-login`.

## Reading the numbers

The plan's targets: p95 under 300 ms for the non-LLM routes, and chat TTFT p95
under 3 s. Compare against a stored baseline at the same concurrency, with the
same `async_db_client` / `stateless_rate_limit` flag values; a flag flip is a
different run.
