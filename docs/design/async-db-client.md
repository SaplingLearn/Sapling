# Async DB client and how it composes with the user-scoped client

Status: design, not implemented. Trov #117 (phase 3 of `docs/architecture-hardening-plan.md`).
Depends on: the user-scoped client from `docs/security/rls-step2-plan.md` §4 (`db/scope.py`, flag
`db_user_scope`), which is being built in parallel. Nothing here changes that design; this doc says
how the async path plugs into it.

## 1. Problem and how we measure it

### Today's model

- `db/connection.py` holds one module-level `httpx.Client` (`_client`, `connection.py:21`), with the
  service-role key baked into its default headers and one flat 30 s timeout (connect, read, write and
  pool wait all 30 s). No retries. Errors surface as `httpx.HTTPStatusError` from
  `raise_for_status()`; nothing maps them.
- `routes/` declares 233 handlers: **201 sync `def`, 32 `async def`** (AST count of decorated route
  functions on `stack/base`; the plan's "~410" counts every top-level `def` in `routes/`, helpers
  included). In the #117 first wave: `graph.py` 10 sync / 0 async, `quiz.py` 6 / 1, `learn.py` 6 / 5,
  `documents.py` 5 / 2. There are 655 `table(`/`rpc(`/`page_all(` call sites under
  `routes/ services/ agents/`.
- FastAPI runs every sync handler and every sync dependency through `run_in_threadpool`
  (`fastapi/routing.py:346`, `fastapi/dependencies/utils.py:680`), which is
  `anyio.to_thread.run_sync` (`starlette/concurrency.py:32-34`). AnyIO's default limiter is
  `CapacityLimiter(40)` (`anyio/_backends/_asyncio.py:3034`). Sync `BackgroundTasks` share it
  (`starlette/background.py:19-23`). Installed and locked: fastapi 0.138.0, starlette 1.3.1,
  anyio 4.14.0, httpx 0.28.1.

### What saturates first

1. **The 40 threadpool tokens.** A sync handler holds its token for its whole run, including any
   LLM call it makes through `run_agent_sync` (11 sites in `routes/`: quiz, graph, documents,
   social, study_guide). 40 concurrent slow requests queue every other sync request on the
   replica, including cheap reads, and the auth guards that hop through `run_in_threadpool`.
2. **The event loop itself.** Some `async def` handlers call sync `table()` directly, which blocks
   the loop for a full PostgREST round trip: `quiz.generate_quiz` (`quiz.py:1986`),
   `admin_documents.reindex`, `careers.apply`, `gradescope.save_credentials_via_bu_sso`,
   `profile.upload_user_avatar`. Others reach sync DB code through service chains (`agents/_run.py`
   documents `_legacy_chat -> apply_graph_update -> update_course_context`). While the loop is
   blocked, every SSE tutor stream on the replica stalls.
3. **The asyncio default executor**, a separate pool of `min(32, cpus + 4)` threads used by
   `asyncio.to_thread` in the agent read tools (`agents/tools/*`) and `chat_stream.py:500`.
4. **PostgREST's own DB pool**, downstream. Once the API stops queuing in front of it, this becomes
   the real limit, and Section 2.3 sizes the client pool against it.

### Measurement, before and after

Take a baseline on staging before the first router converts, and repeat after each wave.

- **Latency:** the plan's targets. p95 under 300 ms for non-LLM endpoints and chat time to first
  token p95 under 3 s, both from the Logfire request spans `instrument_fastapi` already emits.
- **New DB spans:** one span per PostgREST call from the shared send path (2.2), with table, verb,
  status, duration, `sync|async` and `scoped|service`. **No URL or query string**, because filters
  carry user ids and search text. Do not use `logfire.instrument_httpx` for the same reason.
- **Saturation gauges** from a lifespan task every 10 s: threadpool tokens in use
  (`current_default_thread_limiter().borrowed_tokens`), and event-loop lag (how late a 0.5 s
  `asyncio.sleep` wakes up). Loop lag above 100 ms means something is blocking the loop.
- **Nightly load test:** run against the local stack in function mode (deterministic, no LLM cost).
  Use a fixed mix: graph and notes reads, quiz create and answer, and tutor streams. Record p95
  per route template and the saturation gauges. The gate is the plan's target at a fixed
  concurrency, compared to the stored baseline.

## 2. Design

### 2.1 One async client per event loop

- **The app's loop** gets an `httpx.AsyncClient` that the lifespan creates. Its `aclose` is
  registered on the lifespan's `AsyncExitStack` (the #771 pattern in `main.py`), and the client is
  recorded with the loop it belongs to.
- **Any other running loop** gets a lazily built client cached in a
  `weakref.WeakKeyDictionary[loop, AsyncClient]` behind a `threading.Lock`. Other loops are tests
  that call `asyncio.run`, `TestClient` without its context manager (no lifespan), and
  `run_agent_sync`'s throwaway loops. This is the same mechanism as
  `agents/_providers.py::_LoopSafeProviderMixin`, and it exists for the same reason. An
  `httpx.AsyncClient`'s pool binds asyncio primitives to the loop that first used it, and reusing
  it from another loop fails with "Event loop is closed". That is the #354/#436 failure. #453 fixed
  it by resolving the per-loop instance **at the moment of use**, never by caching a pointer on a
  shared object (fix-round-1 lesson). `_async_client()` follows the same rule: call
  `asyncio.get_running_loop()`, look the loop up, and return. Nothing awaits between resolving
  and using the client.
- **The client holds no identity.** Default headers are only `Content-Type` and `Prefer`.
  `apikey` and `Authorization` are set on every request (2.4). Whichever request happens to build
  a loop's client first must not leave its scope baked into that client.

### 2.2 The API: `a*` methods on the same handle

**Chosen:** the handle `table(name)` returns also gets coroutine twins: `aselect`,
`aselect_with_count`, `ainsert`, `aupdate`, `aupsert` and `adelete`, plus module-level `arpc()`
and `apage_all()` (an async generator).

```python
rows = await table("graph_nodes").aselect("*", filters={"user_id": f"eq.{uid}"})
```

Reasons:

- **`table()` stays the single chokepoint and the single patch point** (CLAUDE.md). Tests patch
  `<module>.table` 1,167 times (`routes.quiz.table` alone 160 times). A separate `atable()` would
  be a second import that escapes all of those patches, just as §6.5 of the RLS plan rejected a
  separate `service_table()`.
- **One class, one request builder.** Each verb builds `(method, url, params, headers, json)` in
  one private function, and both paths finish with one private `_finish(response)`
  (`raise_for_status`, JSON, `Content-Range` parsing). The sync and async paths cannot drift on
  paging, `Prefer` handling or errors, because none of that logic is duplicated.
- **Fakes stay cheap.** `MagicMock(spec=SupabaseTable)` turns `async def` methods into
  `AsyncMock`s on its own (checked on the venv's Python 3.14). So a converted router's tests change
  only how the fake is built (4.3).
- **Rejected:** `table(...).aexecute()`. The API is not a builder (`select(...)` executes at once),
  so `aexecute` would mean redesigning the query API, which "What not to do" rules out. An `a`
  prefix is the convention Django's async ORM uses (`aget`, `acreate`).

### 2.3 Pool, timeouts, retries, errors

- **Pool.** Set `httpx.Limits(max_connections=N, max_keepalive_connections=N)` explicitly, with
  N = 40 per replica to start: today's effective concurrency, since the threadpool caps it. Raise
  N only when the PostgREST pool (Supabase compute size) has headroom. More HTTP concurrency than
  PostgREST has DB connections only moves the queue.
- **Timeouts.** `httpx.Timeout(30.0, connect=5.0, pool=5.0)` on **both** clients. Read and write
  keep today's 30 s, and the per-call `timeout=` override in `select` keeps working. Waiting on the
  pool becomes a fast, visible failure (`httpx.PoolTimeout` raises a 503 and is counted on the DB
  span) instead of 30 silent seconds.
- **Retries.**
  - **Connection retries:** set `retries=1` on the transport. httpcore retries only on
    `ConnectError`/`ConnectTimeout` (`httpcore/_async/connection.py`), before anything was sent,
    so this is safe for any verb.
  - **Application retries:** one retry with jitter, **GETs only** (`select`, `select_with_count`,
    each `page_all` page), on 502/503/504 and on `ReadTimeout`.
  - **Never retried:** POST, PATCH, DELETE and every `rpc` (`apply_mastery_delta` and
    `claim_documents_for_indexing` write).
  - **Rollout:** the retry policy lives in the shared send path, so both clients get it in the
    same PR, on its own, before any router converts.
- **Errors.** Both paths raise the same exceptions. `_finish` is shared, so
  `httpx.HTTPStatusError` and the RLS plan's `ScopedAccessDenied`/`UnscopedQueryError` (§4.4)
  surface identically, and the existing exception handlers need no async variant.

### 2.4 Composition with the user scope (W3a, RLS plan §4)

There is **one function in `db/connection.py`** that turns the current scope into headers. Both
`_send` (sync) and `_asend` (async) call it right before the request:

```
_scope_headers() -> {"apikey": ..., "Authorization": "Bearer <service key | minted user JWT>"}
```

It applies §4.2's precedence unchanged: a `service_scope()` block, then the router-level
`db_scope`, then `db_user_scope` from `flag_variant`, then the no-subject rule, then the
outside-a-request rule. It never awaits, so the async path can call it inline. Minting is pure CPU
(about tens of µs).

**The JWT is minted once per request and reused by both clients.** The token is memoized on the
request's shared state dict (`scope["state"]`, reached through `services/request_context.py`'s
`RequestView`), next to the memoized flag variant. The ~4 min per-user cache from §2.1 backs it,
behind a `threading.Lock` that is never held across an `await`. A threadpool hop and the
async handler then see the same token, because they share the **dict object**, not a ContextVar
value.

**How context propagates.** Verified against the installed source and by a FastAPI probe (scratch
script, not committed):

| Where the code runs | Sees ContextVars set before it? | Source |
|---|---|---|
| `async def` handler or dependency | Yes, same task | `fastapi/routing.py:343-344` |
| Sync handler or dependency (threadpool) | Yes, a **copy** | anyio copies the context per call (`anyio/_backends/_asyncio.py:2584`) and runs the function inside it (`:1029`) |
| Downstream of `BaseHTTPMiddleware.call_next` | Yes, a copy at spawn | `starlette/middleware/base.py:148` (`task_group.start_soon`) |
| `BackgroundTasks` (sync or async) | Yes. They run in the request task after the response, so they also see what the handler's **async** dependencies set | `starlette/background.py:19-23` |
| `asyncio.create_task`, `asyncio.to_thread` | Yes, a copy | stdlib |
| `threading.Thread`, `ThreadPoolExecutor.submit` | **No** | stdlib |

Consequences that bind both W3a and this work:

1. **A ContextVar set inside a sync dependency or threadpool code is invisible to everything
   else.** The probe showed this: a sync `Depends` that sets a var, then an async handler that
   reads `None`. This is why §4.1 keeps the subject on `scope["state"]` and not in a var a
   dependency sets. Set identity ContextVars only in ASGI middleware or `async` dependencies, and
   write per-request facts (subject, memoized flag variants, minted token) into the state dict.
2. **`service_scope()` is a ContextVar set and reset inside one `with` block**, and it reads the
   same in sync and async code. Two async hazards:
   - **The decorator must wrap coroutines correctly.** `@runs_as_service` on an `async def` has to
     set the var **inside** the coroutine (an `async def` wrapper). A sync wrapper resets it
     before the body ever runs, which silently runs the body under the user scope.
   - **Never hold a `service_scope()` across a `yield`** in a generator or an SSE stream: the next
     step can run in a different context, and the reset then raises (`Token was created in a
     different Context`). Wrap the inner DB call instead.
3. **Tasks inherit the scope at spawn.** This is right for post-roll work and `BackgroundTasks`:
   they keep the user scope unless wrapped, which is why §3.2 lists `update_course_context`,
   `index_document` and `chunk_visibility.*` as `service_scope()`. It is wrong for anything a
   request spawns that outlives it and serves other users (a lazily started cache refresher or
   worker). Start those in the lifespan, never from a request.
4. **Raw threads lose everything** and fall to step 5 (service). The ruff ban or grep test that §6.5
   proposes covers the async work too. `asyncio.to_thread` and `run_in_threadpool` stay the
   sanctioned hops.
5. **Shadow mode.** The sampled scoped re-run of a SELECT runs the same way on both paths, one
   query after the other on the async path, so shadow does not double peak pool use.

## 3. Rollout switch

- **Flag `async_db_client`.** `("off", "on")`, server-only (`client_visible=False`), declared in
  `REGISTRY`. Kill switch: `SAPLING_FLAG_ASYNC_DB_CLIENT=off`.
- **`off`.** Every `a*` method runs the sync method through `anyio.to_thread.run_sync`: the same
  client, the same 40-token limiter and the same behavior as today, only reached from an
  `async def`.
- **`on`.** The native `AsyncClient`.
- **Resolution.** Once per request, memoized on `scope["state"]` beside `db_user_scope`, through
  the same single resolution. A cache miss on the flag snapshot is a sync read, so it hops off the
  loop the way `guard_off_loop` does. Outside a request: `off` until graduation.
- **Why a flag.** Converting a router's handlers to `async def` is the code change. The flag
  separates "the handler is async" from "the transport is async", so a loop-affinity or pool bug
  can be turned off without a deploy. Graduate it (delete the flag; `on` becomes unconditional)
  after one release at 100%.

## 4. Migration plan

### 4.1 Order

| Wave | Contents | Why here |
|---|---|---|
| 0 | Shared send path (request builder, `_finish`, `_scope_headers`), retry policy, timeouts, DB spans, saturation gauges, `a*` methods, the flag. No handler changes. | Lands the seams with nothing depending on them; take the baseline after it. |
| 1 | `routes/graph.py` (10 sync handlers) + `services/graph_service.py` reads | Small, read-heavy, well tested. Proves the conversion recipe. |
| 2 | `routes/quiz.py` + `quiz_*` services, starting with `generate_quiz`'s on-loop read | Largest test surface (160 patches); fixes a live loop block. |
| 3 | `routes/learn.py` + `tutor_sessions.py`; `chat_stream.py`'s `on_complete` and the agent read tools drop `asyncio.to_thread` for `a*` calls | Highest value for time to first token; the tutor stream is already async. |
| 4 | `routes/documents.py` CRUD (the upload pipeline is moving to the worker in #116, so convert only what stays in the API) | Coordinate with #116 to avoid converting code that is about to move. |
| then | The remaining routers, one PR each, by traffic | Admin and auth last; they run as service anyway. |

- **Per router:** convert a handler to `async def` only once everything it calls on the request
  path has an async form. Sync service functions that a converted handler still needs are wrapped
  in `await run_in_threadpool(...)` at the call site, never called inline.
- **Run sync and async side by side throughout.** Workers, scripts, seeds and the sweeper stay
  sync. Nothing forces them over, and `table()`'s sync methods are permanent.

### 4.2 Guard against sync DB calls on the loop

- **Static check.** `tests/test_no_sync_db_in_async_handlers.py` walks the AST of `routes/*.py`
  and fails when an `async def` route handler calls `table(...).<sync verb>`, `rpc(` or `page_all(`
  directly. Same ratchet style as `test_migration_naming.py`: the 5 offenders above are a
  checked-in allowlist that may only shrink.
- **Runtime check for indirect calls.** In the sync `_send`, if `asyncio.get_running_loop()`
  succeeds, the caller is on an event-loop thread and is blocking it. AnyIO and `to_thread` worker
  threads have no running loop, so legitimate hops pass. It logs `db.sync_on_loop` at WARN with
  the route template, rate-limited, everywhere. A pytest fixture turns it into a raise, and every
  converted router's test module opts in, so a regression in a converted router fails CI.
  `run_agent_sync`'s throwaway loops would trip it too. That is correct (it blocks that loop), but
  the agent tools already hop through `to_thread`, so none do today.

### 4.3 Tests

- **Hermetic net.** `tests/conftest.py::_hermetic_supabase_client` already replaces
  `db.connection._client`. It also patches `db.connection._async_client` to return a fake whose
  `get`/`post`/`patch`/`delete`/`request` are `AsyncMock`s returning the same `_empty_response`, so
  an async call that escapes a test's `table` patch is caught exactly as a sync one is. Both clients
  must share `_finish`, which is what makes one fake response shape serve both.
- **Route fakes.** Add one helper, `tests/db_fakes.py::fake_table()`. It returns
  `MagicMock(spec=SupabaseTable)` and points each `a*` method at its sync sibling
  (`m.aselect.side_effect = lambda *a, **k: m.select(*a, **k)`). Existing setups
  (`mock_table.return_value.select.return_value = [...]`) and assertions on `.select` keep working
  unchanged. A converted router's tests switch `patch("routes.graph.table")` to
  `patch("routes.graph.table", return_value=fake_table())` and nothing else.
- **Unit tests for the client:** both paths against `httpx.MockTransport`. Check the same request
  for the same call, the same errors, the retry policy (GET retried once; POST, PATCH, DELETE and
  rpc never retried), and that `_scope_headers` is called per request. Also check per-loop client
  identity: two `asyncio.run` calls give two clients, and one loop gives one.
- **Integration lane.** Extend the cross-user matrix (§5 of the RLS plan) to run each converted
  route with the flag on and off. Real PostgREST is the only place pool and timeout behavior is
  real.
- **E2E.** The Chapter 1 journeys already cover graph, quiz, tutor and upload. Run the flock'd
  cycle once per wave, with the flag forced on in that lane.

## 5. Prerequisites for 2 replicas (dependencies, not designed here)

- **Rate limiter into Postgres.** `services/request_limits.py::_rate_state` (and the older copy in
  `flashcard_import_service`) is per-process. With 2 replicas each user gets 2× the limit. Replace
  it with a `rate_limit_hits` table and a `claim_rate_limit(key, limit, window)` SQL function: an
  atomic insert-if-under-limit that returns the hit id, which is the refund handle. EXECUTE goes to
  service_role only, and it is called via `rpc`/`arpc` (one round trip). Callers: `extract`,
  `flashcards`, `gradescope`, `quiz`, `topic_checklist`, `flashcard_import_service`.
- **Flag-cache invalidation.** `clear_feature_flags_cache()` clears only the local process, so the
  other replica serves stale flags for up to `FEATURE_FLAGS_SNAPSHOT_TTL_S` (30 s). A kill switch
  needs better than that. Add a `feature_flags_version` row bumped by a trigger on
  `feature_flags`/`feature_flag_targets`. A lifespan task reads it every few seconds and clears
  the snapshot when it moves. No LISTEN/NOTIFY, which PostgREST cannot do, and no Redis ("What not
  to do").
- **Already TTL-bounded, accept and document:** the auth guard's account-state cache (30 s), the
  roles cache (60 s), `course_context_service` (60 s, #771) and the analytics consent cache.
  Already safe across instances: the index sweeper (`SKIP LOCKED` claim). Check the encryption
  canary's first-boot seed under two simultaneous boots before scaling.

## 6. Risks, rollout and scope

| Risk | Mitigation |
|---|---|
| Loop-affinity bug in the async client (the #354 class) | Per-loop resolution at use time (2.1); flag off; unit test for per-loop identity |
| The async pool overwhelms PostgREST's DB pool | N = 40 to start (today's effective cap); pool-wait spans; raise only on measured headroom |
| A sync DB call left in an `async def` blocks the loop | Static ratchet + runtime `db.sync_on_loop` (4.2); loop-lag gauge |
| Scope lost or leaked across `await`, tasks, generators | One `_scope_headers`; rules 1-4 in 2.4; RLS shadow mode catches divergence in reads |
| Test churn in large route modules | `fake_table()` keeps existing setups; convert one router per PR |
| Retries duplicate a write | GETs only; transport retries connect-only |

**Rollout:**

1. Wave 0 ships dark.
2. Each router PR ships with the flag `off`, so behavior is identical apart from offloading
   through the limiter.
3. Turn the flag on per user on staging, then by percentage on prod, watching loop lag, pool
   waits and p95.
4. Scale to 2 replicas only once section 5 is done and a nightly load test passes at the target.

**Out of scope:**

- No ORM, no SQLAlchemy/asyncpg, no Supabase SDK. PostgREST over `httpx` stays the only path.
- No framework rewrite, no big-bang conversion: one router per PR, behind `table()`.
- No change to RLS policy or to the §4.2 precedence. This doc only consumes the scope.
- Workers, scripts and seeds stay sync.
- No Redis or other new infrastructure for the replica prerequisites; Postgres carries them.
