# Incident response runbook

Status: draft, written 2026-11-14 on branch `sec/privacy-ops`. Owner: `<owner>`.

This is the playbook for a security or privacy incident in Sapling: a leaked
secret, unauthorised access to student data, an abused AI endpoint, a vendor
breach that reaches us, or a bug that exposed one student's data to another.
It is written for a small team; one person may hold several roles.

**How to read the tags.** Every operational fact is marked:

- **[code]** with a path: verified against the code in this repository on
  2026-11-14. If the code changes, the code wins; fix this page.
- **[doc]** with a path: taken from another document in this repo, not from
  code.
- **[guidance]**: process advice, vendor console steps, or legal orientation.
  Not verified against code, and vendor UIs change: check the vendor's current
  docs before relying on a click path.

**Nothing in the breach-notification section is legal advice.** It is an
orientation so the team knows which questions to put to counsel, and how
fast. Counsel confirms every obligation and deadline before anything is sent.

Related: [`data-inventory.md`](data-inventory.md) (what data we hold, where,
and under which key), [`../../SECURITY.md`](../../SECURITY.md) (the controls),
[`../deploy/railway.md`](../deploy/railway.md) (the backend deploy),
[`../staging/setup-checklist.md`](../staging/setup-checklist.md) (where each
secret is set).

---

## 1. Roles

A small team, so roles are hats, not people. Fill the names in when this page
is adopted; until then the defaults below apply. **[guidance]**

| Role | Default holder | Decides | Does not decide |
| --- | --- | --- | --- |
| Incident lead | `<incident-lead>` (first engineer to confirm the incident, until handed off) | Severity; containment steps (flags, scaling down, key rotation); when the incident is contained and closed | Whether or what to notify externally |
| Engineering | `<engineer-on-call>` plus anyone the lead pulls in | How to implement a containment or fix; evidence collection | Severity downgrade (the lead does) |
| Comms | `<comms-lead>` | Wording and timing of user / institution / vendor messages, once the owner approves sending | Whether a legal notice is owed |
| Owner / legal contact | `<owner>`, with `<legal-counsel>` | Whether notification is legally required, to whom, and by when; any statement to press, a school, or a regulator; engaging outside counsel or forensics | Technical containment details |

Rules:

1. The incident lead may take any containment step in section 3 without
   asking first. Shutting the whole app off (3.6) needs the owner's go-ahead
   unless the owner cannot be reached within 30 minutes and data is actively
   leaving.
2. Nobody outside the response team is told anything (no public post, no
   message to a school, no reply to a reporter) until the owner approves.
3. One running log per incident (a private doc or ticket): every action with
   its UTC time and who took it. That log is the spine of any later notice.

---

## 2. Severity levels and the first hour

### 2.1 Severity **[guidance]**

| Level | Meaning | Examples | Response |
| --- | --- | --- | --- |
| SEV1 | Student personal data or credentials confirmed exposed, or an attacker is active | `ENCRYPTION_KEY` or `SUPABASE_SERVICE_KEY` leaked; DB dump outside our control; one student reading another's documents, chats or grades in production | All hands now; owner informed within 1 hour; legal clock assumed running from discovery |
| SEV2 | Credible risk of exposure, not yet confirmed; or significant abuse | Secret committed to git or pasted into a public place; auth bypass found but no sign of use; runaway AI spend from abuse; a vendor reports a breach that may include our data | Same day; owner informed within 4 hours |
| SEV3 | Weakness with no evidence of exposure | Vulnerability report from a researcher; a permission check missing on a low-value route | Next working day; tracked to a fix |
| SEV4 | Hygiene | Outdated dependency with no reachable exploit | Normal backlog |

When unsure, pick the higher level. Downgrading later is cheap; a missed
notification deadline is not.

### 2.2 First-hour checklist

1. **Open the incident log** (UTC timestamps). Record who found it, how, and
   the exact discovery time: notification deadlines usually run from
   discovery. **[guidance]**
2. **Assign the incident lead** and a severity.
3. **Preserve evidence before changing things** (section 6), at least: a
   query export of the relevant `events` / `admin_audit_log` / `llm_usage`
   rows, and the Railway and Logfire log windows. Do NOT set
   `EVENTS_LOGGING_ENABLED=false` during an incident: it is the kill switch
   that stops writes to `events` and `llm_usage`
   **[code: backend/services/events_service.py]**, i.e. it destroys the
   evidence trail going forward.
4. **Contain** (section 3): the smallest switch that stops the harm. Prefer a
   flag over a deploy, and a deploy over a shutdown.
5. **Rotate** any secret that may be exposed (section 4). A secret that may
   have leaked is treated as leaked.
6. **Scope**: which students, which tables / columns, which time window,
   which environment (prod vs staging). Use the data inventory to say whether
   the exposed columns are encrypted at rest.
7. **Tell the owner** (SEV1/SEV2) and start the notification assessment
   (section 5) in parallel with the fix: do not wait for the root cause.
8. **Schedule the next checkpoint** (e.g. every 2 hours for SEV1).

---

## 3. Containment: switching things off

### 3.1 Feature-flag kill switches

Flags are declared in `backend/services/feature_flags.py::REGISTRY` and
configured in the `feature_flags` / `feature_flag_targets` tables.
**[code: backend/services/feature_flags.py]**

Resolution order, first match wins: **env override → fail-closed → user rule →
role rule → percentage rollout → stored default.** Anything unreadable or
invalid resolves to `variants[0]`, which is `off`.
**[code: backend/services/feature_flags.py::explain]**

Two ways to throw a switch:

- **Env override, the hard kill.** Set `SAPLING_FLAG_<KEY>` (key upper-cased,
  e.g. `SAPLING_FLAG_LLM_BUDGET=on`) on the Railway service to one of the
  flag's own variants. It beats every stored rule, including per-user and
  per-role targets. An unknown value is ignored with a warning and the stored
  config applies. It needs a restart/redeploy of the service to take effect.
  **[code: backend/services/feature_flags.py::explain, ::cached_explain]**
  The worker service must get the same value: `.railway/railway.ts` shares
  `SAPLING_FLAG_<KEY>` for every non-nav flag from the API service to the
  worker by reference **[code: .railway/railway.ts `FLAG_KILL_SWITCHES`]**
  (that file is not yet applied to Railway **[doc: docs/deploy/railway.md]**,
  so check the worker's variables by hand).
- **Admin API, no deploy.** `/api/admin/flags` (admin only):
  `GET /api/admin/flags`, `PATCH /api/admin/flags/{key}` (default variant,
  rollout percent / variant), `PUT /api/admin/flags/{key}/targets`,
  `DELETE /api/admin/flags/{key}/targets/{target_type}/{target_id}`,
  `GET /api/admin/flags/{key}/explain`. **[code: backend/routes/admin_flags.py,
  backend/main.py mount]** Caveat: changing the **default** does not override a
  user or role target or a rollout; delete those too, or use the env
  override. Each change writes `admin_audit_log` (`flag.update`) and a
  `flag.changed` event, and other replicas pick it up in about 5 s via
  `feature_flags_version` (30 s snapshot TTL worst case).
  **[code: backend/routes/admin_flags.py::record_flag_change,
  backend/services/feature_flags.py module docstring]**

Flags useful in an incident (variants as registered today; `off` is always
`variants[0]`) **[code: backend/services/feature_flags.py::REGISTRY]**:

| Flag | Variants | Incident use |
| --- | --- | --- |
| `llm_budget` | off / on | Turn **on** to refuse new AI runs (429) for students over their daily token budget; budgets edited at `/api/admin/llm/budgets` **[code: backend/routes/admin_llm.py]**. First lever for AI-spend abuse. |
| `llm_fallback` | off / on | Global. Turn **off** to stop retrying a failed provider call on the other provider (keeps traffic off a provider you have cut). |
| `decision_router` | off / jev / jev_shadow | **off** stops all TypeSafe Jev calls. |
| `product_analytics` | off / on | **off** stops every PostHog capture (backend worker drops it; frontend never starts posthog-js). Use if PostHog is the leak path or the vendor is breached. |
| `jobs_queue` | off / on | **off** keeps uploads and indexing in-request instead of the worker. |
| `db_user_scope` | off / shadow / enforce | RLS-as-student. Its fail-closed answer (`off`) is the *less* secure side; do not flip it during an incident without the engineer who owns RLS. |
| `stateless_rate_limit`, `stateless_locks`, `stateless_tutor_sessions`, `async_db_client` | off / on | Infrastructure flags; not containment levers. Turning one off while two replicas run reintroduces split state **[doc: docs/deploy/railway.md "Rollback"]**. |
| `llm_outage_drill` | off / anthropic / google / both | A drill switch; refused in production without `SAPLING_LLM_FORCE_OUTAGE_ALLOW_PRODUCTION=yes`. Can be used deliberately to make every LLM call to a provider fail fast. |
| `realtime_rls` | off / on | Retired; never set its kill switch to off (see the registry comment). |
| `spend_alerts` | off / on (seeded **on**) | The hourly admin alert emails (`services/spend_alerts.py`): today's AI spend over `SPEND_ALERT_DAILY_USD` (default $50), a student over `SPEND_ALERT_USER_DAILY_USD` ($5), and `auth.permission_denied` / `error.5xx` spikes. One email per alert type per admin per UTC day; recipients are the admin-role accounts or `SPEND_ALERT_RECIPIENTS`. Needs `RESEND_API_KEY`. During an incident, check it is on and that an admin received it; switch **off** only if the alerts themselves are the problem. **[code: backend/services/spend_alerts.py, backend/db/migrations/20261114192656_spend_alerts_flag.sql]** |

### 3.2 `hide_<feature>` nav flags

One per main-nav feature: `hide_tutor`, `hide_quiz`, `hide_tree`,
`hide_study`, `hide_library`, `hide_calendar`, `hide_social`,
`hide_achievements`, `hide_grades`, `hide_notetaker`,
`hide_course_planner`. `on` = hidden. The frontend redirects the feature's
pages to `/dashboard`, and for most flags the backend also 404s the feature's
API routers **[code: backend/services/feature_flags.py `NAV_FEATURES`,
`NAV_FEATURE_API`; backend/main.py `nav_feature_gate`]**:

| Flag | API routers 404'd (minus listed exemptions) |
| --- | --- |
| `hide_quiz` | `/api/quiz` (except `GET /attempts`) |
| `hide_study` | `/api/flashcards`, `/api/study-guide`, `/api/study` |
| `hide_calendar` | `/api/calendar` (with exemptions) |
| `hide_social` | `/api/social` (except `/friends`) |
| `hide_achievements` | `/api/gamification` (except `GET /me`) |
| `hide_grades` | `/api/gradebook` |
| `hide_notetaker` | `/api/notes` |

**Not enforced on the API** (nav only, so not a containment step for a
backend bug): `hide_tutor`, `hide_tree`, `hide_library` (uploads,
`/api/documents`), `hide_course_planner`
**[code: backend/services/feature_flags.py `NAV_FEATURES_NOT_ENFORCED`]**. To
stop uploads or tutor chat in an emergency you need a deploy or the
shutdown in 3.6.

### 3.3 Other switches

| Switch | Effect | Source |
| --- | --- | --- |
| `INDEX_SWEEPER_ENABLED=false` | Stops the background indexing sweeper (re-indexing documents into `course_chunks`). | **[code: backend/services/index_sweeper.py]** |
| `RESEND_API_KEY` unset | No email is sent; each send is recorded as `skipped`. | **[code: backend/services/email_service.py; backend/.env.example]** |
| `POSTHOG_PROJECT_TOKEN` unset | No PostHog client is built at boot. Account-deletion erasure in PostHog runs off `POSTHOG_PERSONAL_API_KEY` independently. | **[doc: backend/.env.example; CLAUDE.md]** |
| `CANOPY_METRICS_TOKEN` unset | `GET /api/internal/metrics` answers 404. | **[code: backend/config.py::canopy_metrics_token]** |
| `ACCOUNT_SYNC_INBOUND_TOKEN` unset | `/api/internal/account-sync/*` answers 404 (stops cross-env account copy into this env). | **[code: backend/config.py; backend/.env.example]** |
| `ALLOWED_EMAIL_DOMAINS` | Sign-in email-domain allowlist, default `bu.edu`. **An empty value allows any domain**: never blank it to "turn it off". To refuse all new sign-ins, set a domain nobody has (e.g. `invalid.invalid`). | **[code: backend/config.py, backend/services/auth/signin.py]** |

### 3.4 Approval gate

New accounts start with `users.is_approved = false` and are sent to
`/pending` instead of receiving a session **[code: backend/routes/auth.py]**.
An admin removes an existing user's access with
`PATCH /api/admin/users/{user_id}/unapprove` (account and data kept)
**[code: backend/routes/admin.py::unapprove_user]**. The auth guard reads
`users.deleted_at` / `users.is_approved` on every authenticated request
through a 30 s per-process cache, so an unapproved or soft-deleted account is
refused within about 30 s on every replica
**[code: backend/services/auth_guard.py `ACCOUNT_STATE_TTL_SECONDS`,
::get_session_user_id]**. Allowlist approvals are revoked with
`POST /api/admin/allowlist/revoke` **[code: backend/routes/admin.py]**.

### 3.5 Revoking sessions

How sessions work **[code: backend/services/session_tokens.py,
backend/services/auth_guard.py::_decode_session,
frontend/src/lib/sessionToken.ts]**:

- A session token is `base64url(payload).base64url(HMAC-SHA256(SESSION_SECRET, payload))`,
  payload `{"user_id", "exp", "typ"}`. Stateless: there is no session table
  and no server-side revocation list.
- The frontend session route signs the `sapling_session` cookie with the same
  `SESSION_SECRET` (a Cloudflare Worker secret) and a 30-day expiry; the
  backend verifies the HMAC, the expiry and the `typ`, then the account state.
- The backend also accepts the token from the `auth_token` query parameter
  **[code: backend/services/auth_guard.py::presented_session_token]**.

So:

- **One student or a few:** unapprove them (3.4). Effective in about 30 s.
  Their token stays cryptographically valid, so re-approving restores it.
- **Everyone:** rotate `SESSION_SECRET` on the Railway backend **and** the
  Cloudflare frontend Worker to the same new value (section 4). Every
  session cookie, OAuth state, pending token and in-flight OAuth handoff
  stops verifying; every user signs in again. Side effects in 4.2.

### 3.6 Taking the app offline **[guidance]**

The repo documents image-target and replica rollbacks only
**[doc: docs/deploy/railway.md]**. The steps below are Railway / Cloudflare
console actions; confirm the current UI.

Backend (Railway, project with the `backend` API service and the `worker`):

1. **Roll back** a bad deploy: service → Deployments → pick the last good
   deployment → Redeploy / Rollback. For the image split specifically: delete
   `SAPLING_IMAGE_TARGET` (or set `full`) and redeploy
   **[doc: docs/deploy/railway.md]**.
2. **Stop serving:** remove the active deployment of the API service (and of
   `worker`, so jobs stop too), or scale replicas to zero where the plan
   allows. The frontend then shows API errors; data stays in Supabase.
3. **Cut public access without stopping the process:** service → Settings →
   Networking → remove the custom domain (`api.saplinglearn.com`) and any
   generated `*.up.railway.app` domain. Note where DNS for
   `api.saplinglearn.com` lives before removing anything.
4. Railway variable changes trigger a redeploy; plan for a short outage per
   change and batch variable edits where possible.

Frontend (Cloudflare Workers via OpenNext; Worker `frontend`, staging
`frontend-staging`) **[code: frontend/wrangler.toml]**:

1. **Roll back:** Workers & Pages → `frontend` → Deployments → roll back to a
   previous version.
2. **Gate the site:** staging already sits behind Cloudflare Access with an
   admin-email allowlist **[doc: docs/staging/setup-checklist.md Step 5]**. In
   an emergency the same kind of Access application can be put on the
   production hostnames, so only listed admins reach the app.
3. **Block traffic:** a WAF custom rule (block all, or block a specific
   path / IP / ASN) on the `saplinglearn.com` zone, if the zone is on
   Cloudflare.

Supabase: if the service key may be in an attacker's hands, rotating it
(section 4) is the containment: stopping our backend does not stop someone
holding the key.

---

## 4. Key and secret rotation

Where secrets live **[doc: docs/staging/setup-checklist.md "What secret goes
where"; frontend/wrangler.toml; .github/workflows]**:

- Backend: Railway service variables on the `backend` service, per
  environment (staging, production). The `worker` service references most of
  them from `backend` **[code: .railway/railway.ts]**, so rotate on
  `backend` and confirm the worker picked the new value up (redeploy it).
- Frontend: Cloudflare Worker secrets (`wrangler secret put …`, `--env
  staging` for staging) and Workers Builds build variables for
  `NEXT_PUBLIC_*`.
- Local ops files: `backend/.env`, `backend/.env.staging`,
  `backend/.env.production` (gitignored; used by `make promote`,
  `make backup-db`) **[code: Makefile]**. Anyone holding one must update it.
- GitHub Actions secrets: `STAGING_SUPABASE_DB_URL`, `LOADTEST_SESSION_TOKEN`,
  `CLAUDE_CODE_OAUTH_TOKEN` **[code: .github/workflows]**.

Every row below: rotate **staging and production separately**; each
environment has its own value. Env var names are exact
**[code: backend/config.py, backend/.env.example, and the files cited]**.

| Secret | Where set | Blast radius if leaked | Rotation |
| --- | --- | --- | --- |
| `ENCRYPTION_KEY` (64 hex chars, AES-256-GCM) | Railway `backend` (+ worker); local ops `.env*` | With a DB copy: every encrypted column readable (names, chats, document text, notes, grades, OAuth tokens…; full list in the data inventory). Alone: nothing. | See 4.1. No dual-key support exists: `services/encryption.py` loads exactly one key **[code]**. |
| `SESSION_SECRET` (≥32 bytes) | Railway `backend` **and** Cloudflare Worker secret (must be equal) | Forge a session for any user id, including admins. | See 4.2. Effective on restart; logs everyone out. |
| `SUPABASE_SERVICE_KEY` | Railway `backend`; local ops `.env*` | Full read/write of every table and storage bucket, bypassing RLS. Encrypted columns stay ciphertext without `ENCRYPTION_KEY`. | Supabase dashboard → API keys: issue a new secret/service key, set it on Railway, redeploy, then revoke the old one. If the project still uses the legacy JWT-based `service_role` key, rotating it means rotating the project JWT secret, which also changes the anon key: update `SUPABASE_ANON_KEY` (backend) and `NEXT_PUBLIC_SUPABASE_ANON_KEY` (frontend build) together. **[guidance]** |
| `SUPABASE_DB_URL` (password inside), `STAGING_SUPABASE_DB_URL`, `DBOS_DATABASE_URL` | Railway (`SUPABASE_DB_URL` per staging checklist); local ops `.env*`; GitHub secret `STAGING_SUPABASE_DB_URL`; DBOS only if enabled | Direct Postgres: everything the service key gives, plus DDL. | Supabase → Database settings → reset the database password; rebuild each URL (`backend/scripts/pooler_url.py`); update every holder. **[guidance]** |
| `SUPABASE_JWT_SIGNING_KEY` (JWK) | Railway `backend` (+ worker) | Mint student-scoped DB JWTs and Realtime tokens for any user (RLS then applies as that user). | Import a new signing key in Supabase (JWT signing keys), set it here, redeploy, then revoke the old key in Supabase. **[code: backend/db/user_jwt.py; guidance for the Supabase steps]** |
| `SUPABASE_ANON_KEY` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Railway; Cloudflare build variable | Public by design; RLS is the control. Rotate only alongside a JWT-secret rotation. | As above. |
| `GOOGLE_CLIENT_SECRET` (with `GOOGLE_CLIENT_ID`) | Railway `backend` | Impersonate the Sapling OAuth client in a phishing flow; combined with a stolen refresh token, act on a student's Google Calendar within the granted scopes. | Google Cloud Console → Credentials → the OAuth client → add a new secret, deploy it, then disable/delete the old secret. Stored refresh tokens (encrypted in the DB) are bound to the client, not the secret; revoke them only if the DB was also exposed. **[guidance]** |
| `ANTHROPIC_API_KEY` | Railway `backend` (+ worker) | Spend on our account; no access to our data. | Anthropic Console → API keys: create, deploy, revoke old. Revoking without a replacement stops all agents (a blunt spend kill). **[guidance]** |
| `GEMINI_API_KEY` | Railway `backend` (+ worker) | Spend on our Google AI account (embeddings, any `gemini-*` slot). | Google AI Studio / Cloud Console: create, deploy, delete old. **[guidance]** |
| `RESEND_API_KEY` | Railway `backend` | Send email as our verified domain (phishing students). | Resend → API keys: create, deploy, revoke old. **[guidance]** |
| `POSTHOG_PROJECT_TOKEN` / `NEXT_PUBLIC_POSTHOG_KEY` | Railway; Cloudflare build variable | Public ingestion key: lets someone inject junk events, not read data. | Rotate in PostHog project settings if abused. **[guidance]** |
| `POSTHOG_PERSONAL_API_KEY` (with `POSTHOG_PROJECT_ID`) | Railway `backend` | Personal key with `person:write`: delete or alter PostHog persons, read analytics within its scopes. | PostHog → personal API keys: roll, deploy, delete old. **[guidance]** |
| `LOGFIRE_TOKEN` | Railway `backend` (+ worker) | Write-only token: inject spans into our Logfire project; no read. | Logfire → project → Settings → Write tokens: create, deploy, revoke old. **[doc: backend/.env.example]** |
| `CANOPY_METRICS_TOKEN` | Railway `backend`; the same value is Canopy's `SAPLING_METRICS_TOKEN` Worker secret | Read aggregate usage counts (no per-student data). | Generate (`openssl rand -hex 32`), set on both sides. Read at call time, so no code change. **[code: backend/config.py::canopy_metrics_token]** |
| `ACCOUNT_SYNC_INBOUND_TOKEN` / `ACCOUNT_SYNC_PEER_TOKEN` | Railway (staging inbound, prod peer, per the recommended setup) | The inbound token grants read and overwrite of any account's study data on the env that accepts it. | New long random value on both envs; unsetting the inbound token 404s the routes. **[doc: backend/.env.example]** |
| `TYPESAFE_API_KEY` | Railway `backend` (only if `decision_router` is used) | Spend on our TypeSafe account. | Rotate in TypeSafe; or set `decision_router` off. **[code: backend/services/typesafe_client.py]** |
| `RECOST_API_KEY` | Railway `backend` (optional) | Write cost telemetry to our Recost project. | Rotate in Recost. **[code: backend/main.py]** |
| `REDIS_URL` (may embed a password) | Railway (only if Redis is used) | Read/poison the OCR/extraction cache (document text). | Rotate the Redis password. **[code: backend/services/cache.py; guidance]** |
| `LOADTEST_SESSION_TOKEN` | GitHub Actions secret | A real session token: as powerful as that user until it expires or `SESSION_SECRET` rotates. | Re-mint after any `SESSION_SECRET` rotation; delete if unused. **[code: .github/workflows/loadtest.yml]** |
| `CLAUDE_CODE_OAUTH_TOKEN` | GitHub Actions secret | Runs the Claude Code review workflows on our account. | Re-issue and replace. **[guidance]** |

### 4.1 Rotating `ENCRYPTION_KEY`

The backend refuses to boot with a key that cannot open the
`encryption_key_check` canary row, because the read helpers fail soft and a
wrong key would otherwise re-encrypt rows under itself
**[code: backend/services/encryption_canary.py]**. Its documented rotation
rule: **re-encrypt every encrypted column, then delete the canary row so the
new key re-seeds it on the next boot.**

There is no rotation tool in the repo: `db/backfill_encryption.py` encrypts
legacy *plaintext*, and `services/encryption.py` holds one key. A rotation
therefore needs a one-off script, reviewed like a migration, that decrypts
each encrypted column with the old key and re-encrypts it with the new one. Steps
**[guidance]**:

1. Take a backup: `make backup-db ENV=prod` (pg_dump into the gitignored
   `backups/`) **[code: Makefile]**. Store it encrypted; it contains the
   ciphertext *and* is useless without the old key, so keep the old key
   until the rotation is verified.
2. Stop writers: remove the API and worker deployments (3.6), so nothing
   writes under the old key mid-rotation.
3. Run the re-encryption script against every column listed in the data
   inventory and CLAUDE.md "Gotchas". `course_chunks.chunk_text` ids are
   hashes of the plaintext, so they do not change.
4. Delete the `encryption_key_check` row.
5. Set the new `ENCRYPTION_KEY` on Railway (`backend` and `worker`) and in
   local ops files; deploy. The first boot re-seeds the canary.
6. Spot-check decryption of each column type; then destroy the old key.

The account-sync bundle never carries keys; each env re-encrypts with its own
**[doc: backend/.env.example]**.

### 4.2 Rotating `SESSION_SECRET`

Set the same new value on the Railway `backend` service and as the
Cloudflare Worker secret (`wrangler secret put SESSION_SECRET`, plus
`--env staging` for staging and the Preview secret for PR previews)
**[doc: docs/staging/setup-checklist.md; frontend/wrangler.toml]**. A
mismatch breaks sign-in for everyone ("Sign-in failed").

It invalidates, in one step **[code]**:

- every session cookie and every `auth_token` (`services/auth_guard.py`);
- OAuth `state` cookies and redirect handoff tokens in flight
  (`services/auth/oauth_state.py`);
- `/pending` waitlist tokens (`services/auth/pending.py`);
- email `recipient_hash` values and unsubscribe tokens, which are keyed off
  `SESSION_SECRET` (`services/email_service.py::_derived_key`): existing
  suppressions no longer match their addresses and old unsubscribe links stop
  working. Before rotating, export `email_suppressions` and plan to re-key
  them, or accept that suppressed recipients must be re-suppressed (this
  matters legally for marketing email). **[guidance on the remedy]**
- `LOADTEST_SESSION_TOKEN` (re-mint).

---

## 5. Breach notification: orientation, not legal advice

**This section is not legal advice.** It lists frameworks that *may* apply
so the owner can brief counsel fast. Whether each applies, what counts as a
reportable breach, and every deadline must be confirmed by counsel for the
facts of the incident. Encryption matters: many state laws exempt encrypted
data when the key was not also compromised, which is why section 4 asks
whether `ENCRYPTION_KEY` leaked.

Facts that shape the analysis (to verify when the incident happens):

- Sign-in is limited to `@bu.edu` Google accounts by default
  **[code: backend/config.py `ALLOWED_EMAIL_DOMAINS`]**, so users are
  presumably Boston University students. Students' home states vary; state
  breach laws generally follow the *resident's* state, not the school's.
- Whether Sapling has a contract or DPA with BU (or any school) decides
  whether FERPA's school-official route and any contractual notice clause
  apply. Check before the first call with counsel.
- The Privacy page states Sapling is not directed at children under 13
  **[code: frontend/src/app/(public)/privacy/page.tsx]**.

### 5.1 Frameworks

| Framework | When it may apply | What it asks (orientation) |
| --- | --- | --- |
| **FERPA** (US) | Sapling holds education records *on behalf of* an institution, typically under the "school official" exception with a written agreement. | FERPA itself sets no fixed breach-notification deadline. The duty usually runs through the contract: notify the institution, which decides on notice to students (or families, for K-12). Institutional contracts and DPAs commonly require notice within **24 to 72 hours** of discovery. |
| **COPPA** (US) | Personal information from children under 13 is involved. Sapling says it does not knowingly collect it. | No standalone breach-notice clock in the rule as we understand it, but any under-13 data in an incident goes to counsel immediately (FTC enforcement exposure), and state breach laws still apply. |
| **State breach-notification laws** (all 50 states) | Defined personal information (often name + another identifier, account credentials, etc.) of a state's residents is acquired without authorisation. | Most say "without unreasonable delay" / "most expedient time possible". Several set fixed outer limits, commonly **30, 45 or 60 days**, and many also require notice to the state attorney general above a resident-count threshold. Counsel to map affected residents to states. |
| **Massachusetts** (M.G.L. c. 93H; 201 CMR 17.00) | Massachusetts residents' personal information (likely many BU students). | Notice "as soon as practicable and without unreasonable delay" to affected residents, the Attorney General and the Office of Consumer Affairs and Business Regulation; 201 CMR 17.00 also requires a written information security program. Counsel to confirm triggers (the statute's definition of personal information is narrower than "student data"). |
| **New York Education Law §2-d** (8 NYCRR Part 121) | Only if Sapling is a third-party contractor to a New York educational agency. | Notify the educational agency within **7 calendar days** of discovery (as we understand Part 121). |
| **California SOPIPA** and similar state student-privacy laws | SOPIPA covers operators of K-12 services; likely not BU, but related state laws (and CCPA/CPRA for California residents, if thresholds are met) may. | Counsel to confirm applicability. |
| **GDPR / UK GDPR** | EU/UK-located users are in scope (e.g. we offer the service to people in the EU). | Notify the lead supervisory authority within **72 hours** of becoming aware, where feasible (Art. 33); notify data subjects without undue delay when the risk to them is high (Art. 34). Document every breach, reportable or not. |
| **Vendor contracts** | Supabase, Railway, Cloudflare, Anthropic, Google, PostHog, Pydantic (Logfire), Resend, TypeSafe, Recost. | A vendor breach reaches us through their notice to us; our own contracts may also require us to notify them (e.g. of key compromise). |

### 5.2 Notification timeline (planning defaults; counsel confirms)

| Clock from discovery | Action | Owner |
| --- | --- | --- |
| 0 h | Incident log opened; discovery time recorded; severity set | Incident lead |
| ≤ 1 h (SEV1) / ≤ 4 h (SEV2) | Owner informed; counsel engaged for SEV1 | Incident lead → owner |
| ≤ 24 h | Preliminary scope (who, what data, encrypted or not, window); decision on whether any contract requires notice in 24 h | Engineering → owner, counsel |
| ≤ 24 to 72 h | Institution notice if a contract/DPA requires it; GDPR authority notice if in scope (72 h) | Owner / comms |
| ≤ 7 days | NY Ed Law 2-d agency notice, if applicable | Owner / comms |
| ≤ 30 / 45 / 60 days (state-dependent) | Individual and AG notices under state law, at the latest; most states expect sooner ("without unreasonable delay") | Owner / comms, counsel |
| After notices | Post-incident review (section 7) | Incident lead |

### 5.3 Notice template outline (structure only; counsel writes the text)

1. What happened, in plain words, and when (discovery date, incident window).
2. What information was involved (categories, not values), and whether it was
   encrypted.
3. What we have done (containment, rotation, fixes).
4. What the reader can do (e.g. sign out and back in, watch for phishing that
   impersonates Sapling, revoke Sapling's Google Calendar access).
5. How to reach us (a monitored address), and for regulators/institutions a
   named contact.
6. Any regulator-specific elements counsel requires (e.g. number of
   affected residents, AG contact language, credit-monitoring offer).

---

## 6. Evidence preservation

Snapshot first, then fix. Copy evidence somewhere access-controlled; it
contains personal data. **[guidance unless tagged]**

| Source | What it holds | How to preserve |
| --- | --- | --- |
| `events` table | Typed app events: `auth.login`, `auth.permission_denied` (reason, route), `error.4xx` / `error.5xx`, `flag.changed`, usage events. Payloads are ids/counts/enums, never raw text. The table has no retention job. **[code: backend/services/events_service.py `EVENT_TAXONOMY`; backend/db/migrations/20260921041555_canopy_active_users.sql comment]** | Export the incident window (SQL over the session pooler, or `/api/admin/analytics`). |
| `admin_audit_log` | Every admin action (flag changes, user approve/unapprove, …). **[code: backend/services/admin_audit.py]** | Export the window; check for actions nobody on the team took. |
| `llm_usage` | One row per agent run: model, tokens, cost, user. Shows AI abuse and spend. **[code: backend/agents/usage.py, backend/services/events_service.py]** | Export the window. |
| `email_sends` | What email was sent to whom (recipient hashes only). **[code: backend/services/email_service.py]** | Export if email abuse is suspected. |
| Logfire | Request traces and agent spans, with prompt / output / tool-call content scrubbed before egress (`services/logfire_scrubber.py`). **[code]** Retention depends on the Logfire plan. | Export or screenshot the relevant traces early. |
| Railway logs | Process stdout: per-request lines with request id, method, path, status, duration; boot logs; warnings. Retention depends on the Railway plan. | Download the window for `backend` and `worker` per environment. |
| Supabase logs | API (PostgREST), Postgres, auth and storage logs; short retention on lower plans. | Export from the dashboard immediately. |
| Database snapshot | Full state at the time. The Supabase Free plan has no backups or PITR **[doc: docs/architecture-hardening-plan.md]**. | `make backup-db ENV=prod` **[code: Makefile, backend/promotion/backup.py]**. |
| Cloudflare | Worker logs (observability is enabled in `frontend/wrangler.toml` **[code]**), WAF / Access logs. | Export the window. |
| GitHub | Commits, Actions runs, secret-scanning alerts (if a secret was pushed). | Note SHAs; do not force-push history away before the secret is rotated and evidence is copied. |

Correlate by request id: the backend returns `X-Request-ID` on errors and
logs it per request **[code: backend/main.py]**.

---

## 7. Post-incident review

Within 5 working days of closing a SEV1/SEV2 **[guidance]**:

1. Timeline from the incident log (UTC), including the discovery time used
   for notification clocks.
2. Root cause and contributing factors; blameless.
3. What was exposed, to whom, for how long; which notices were sent and when.
4. What worked and what was slow in this runbook; fix this page in the same PR
   as the follow-ups.
5. Follow-up items as tickets with owners: code fix, regression test (and an
   E2E journey if the surface is E2E-covered), monitoring or alerting gap
   (e.g. would the spend/abuse alert emails have caught it earlier?).
6. If something was tried and did not work, record it in `docs/attempts/`.
