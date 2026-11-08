# LLM provider outage drill

The acceptance test for plan phase 5 (Trov #119,
`docs/architecture-hardening-plan.md`): **a forced provider outage in staging
falls back with no user-facing errors.** This runbook forces one on staging,
drives real tutor and quiz traffic through it, and checks that the other
provider served every request.

Run it on **staging**. It is refused in production unless you set a second,
explicit variable (see [Production](#production)). Never run it against a
stack other people are demoing on: for the length of the drill every Claude
call on that deployment fails.

## How it works

`SAPLING_LLM_FORCE_OUTAGE` names the provider(s) to break: `anthropic`,
`google`, or `anthropic,google`. It is read **once, at boot**
(`agents/_resilience.py::FORCED_OUTAGE`). While it is set, every model request
to that provider fails *inside* the retry loop, before anything is sent, with
a retryable 503 (`ForcedOutageError`). So the drill runs the real path end to
end:

1. each call retries (3 attempts, jittered backoff, about 1.5 s worst case);
2. after 8 such failures in 60 s the provider's circuit breaker opens, and
   calls fail fast for 30 s at a time;
3. with the `llm_fallback` flag **on**, each failed call is retried once on the
   slot's other-provider model (`_GEMINI_FALLBACKS` in
   `agents/_providers.py`, e.g. the Sonnet tutor falls back to
   `gemini-2.5-pro`). With it **off**, the routes return their normal errors
   (the tutor's 502 "had trouble answering", the SSE `error` event, the quiz's
   `QUIZ_GENERATION_FAILED`).

The `llm_usage` row of a fallback run records the model that **served** it, so
`gemini-*` rows during the drill are the fallbacks.

Why an env var and not a feature flag: starting and stopping a drill should
take a deliberate deploy, never one misclick in `/admin/flags` that every worker
picks up within 30 s. The drill also must not depend on the flag store.

## Before you start

- [ ] Staging's Railway `GEMINI_API_KEY` is a **real** key. The fallback runs on
      Gemini; with a bad key the fallback gets a 401, which never falls back
      again, and every request errors. Embeddings use the same key, so if RAG
      works on staging the key is fine.
- [ ] You have an **admin** test account on staging and its `sapling_session`
      cookie (browser dev tools → Application → Cookies, on the staging app
      after signing in). The script reads the drill state and the per-model
      rollup through admin endpoints. A non-admin session still runs the
      requests but can't show which models served them.
- [ ] That account has at least one concept in its knowledge graph, so the
      quiz step has something to quiz on (or pass `--concept-node-id`).
- [ ] Note the time. Staging traffic from anyone else during the drill shows up
      in the rollup too.

## Run it

1. **Force the outage.** In Railway → staging → backend service → Variables,
   add `SAPLING_LLM_FORCE_OUTAGE=anthropic`. Railway redeploys. In the deploy
   log, confirm the boot line:

   ```
   LLM FORCED-OUTAGE DRILL ARMED: every request to anthropic fails with a retryable 503 ...
   ```

   If you see `llm forced-outage drill NOT armed: ...` instead, the value was
   wrong or `APP_ENV` is `production` (check the staging service's `APP_ENV`).

2. **Fallback off first (the "before" picture).** In `/admin/flags`, make sure
   `llm_fallback` is `off`. Then, from `backend/`:

   ```bash
   export SAPLING_DRILL_SESSION='<admin sapling_session cookie>'
   python -m scripts.llm_outage_drill \
       --url https://api.staging.saplinglearn.com --i-know \
       --user-id <that account's users.id> --expect errors
   ```

   Expect every request to fail with the normal, friendly errors (no 500s, no
   hung requests) and the script to exit 0. This shows the outage is real.

3. **Fallback on (the acceptance test).** In `/admin/flags`, set `llm_fallback`
   to `on` (the stored default; it is a global flag). Wait 30 s for the flag
   snapshot, then:

   ```bash
   python -m scripts.llm_outage_drill \
       --url https://api.staging.saplinglearn.com --i-know \
       --user-id <that account's users.id>
   ```

   **Pass:** `0 user-facing error(s)`, exit status 0, and the "Served models"
   list shows `gemini-*` models only (no `claude-*` calls since the drill
   started). The breaker line should read `{'anthropic': 'open'}` (or
   `half_open` between probes).

   Optionally also click through the staging app as a student: a tutor
   session, a streamed reply, a quiz. Nothing should look different except
   speed and model voice.

4. **Stop the drill.** Delete `SAPLING_LLM_FORCE_OUTAGE` in Railway and let it
   redeploy. Confirm the boot log no longer has the ARMED line and
   `GET /api/admin/llm/drill` reports `"providers": []`. Decide whether
   `llm_fallback` stays on for staging (the release plan expects it to).

5. **Record the result** on Trov #119: the date, both script outputs, and any
   request that failed.

### Other variants

- `SAPLING_LLM_FORCE_OUTAGE=google` breaks Gemini only: the Claude slots are
  unaffected, and only a slot pointed back at Gemini
  (`SAPLING_MODEL_<TASK>=gemini-*`) would fall back, to Claude. RAG embeddings
  do **not** go through this switch (`services/rag_service.py` is not an
  agent), so retrieval keeps working.
- `SAPLING_LLM_FORCE_OUTAGE=anthropic,google` is a total outage. Run it with
  `--expect errors` to check that every surface degrades with its normal error
  and nothing 500s or hangs.

## Locally

The same drill works against a local backend (`APP_ENV=local`, real model
mode, real API keys). Set the variable before starting it:

```bash
cd backend
SAPLING_LLM_FORCE_OUTAGE=anthropic SAPLING_FLAG_LLM_FALLBACK=on python main.py
# another shell:
python -m scripts.llm_outage_drill --user-id <a seeded user>   # mints a session via /api/auth/test-login
```

It is meaningless in function mode (`SAPLING_MODEL_MODE=function`, the E2E
stack): scripted models never go through the resilience layer.

## Production

`APP_ENV=production` (also what an unset `APP_ENV` means) refuses the switch
and logs `llm forced-outage drill NOT armed: ... refused in production` at
ERROR. To drill production on purpose, set **both**
`SAPLING_LLM_FORCE_OUTAGE=<provider>` and
`SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION=yes`, with `llm_fallback` already on
and the staging drill already passed. Real students will be on the fallback
model for the whole window. Remove both variables straight after.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Script says `forced outage: NONE` | The worker it reached was not booted with the variable (deploy still rolling, or a typo). Each worker answers `/drill` for itself. |
| Errors with fallback on, `401` / `PERMISSION_DENIED` in the log | Staging's `GEMINI_API_KEY` is not valid. |
| `claude-*` calls in the rollup during the drill | Calls from before the redeploy finished, or another worker still on the old deploy. Re-run once the deploy is done. |
| `429` with "today's limit for AI features" | The drill account hit its `llm_budget` daily token budget. Raise it at `/api/admin/llm/budgets` or use another account. |
