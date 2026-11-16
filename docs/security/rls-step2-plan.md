# RLS step 2: user-scoped PostgREST client and real per-table policies

Trov #115 (saplinglearn), Phase 1 of the architecture hardening plan. Written 2026-11-08 against `main` at `e47b9a3` plus `origin/main` (`d22b0ae`, #805/#806) and PR #807 (`96ad478`, branch `security/rls-lockdown-every-table`). Plan only: nothing in the repo was changed.

## 0. Baseline and what was verified

**PR #807 is step 1.** Migration `20261108082151_rls_on_every_table.sql` enables RLS on every public table except `room_messages`, revokes all table and sequence privileges from `anon` and `authenticated`, grants all to `service_role`, and revokes default table/sequence privileges for the migration role. `backend/tests/integration/test_rls_lockdown_db.py` pins it (catalog half via psycopg, wire half via PostgREST with the local anon key). This plan does not re-propose any of that. It is step 2: a user-scoped client, real policies for `authenticated`, and moving `room_messages` under RLS with the realtime JWT bridge.

How the claims below were checked:

- **Schema.** I replayed every migration in `backend/db/migrations/` (sorted, as `db/migrate.py::discover_migrations` does), then #805's and #807's, into a scratch PostgreSQL 16 + pgvector cluster under `/tmp` with stub Supabase roles (`anon`, `authenticated`, `service_role BYPASSRLS`) and stub `auth.jwt()`/`auth.uid()`. All files applied cleanly. Result: **67 tables in `public`** created by migrations, plus `schema_migrations` (created by `db/migrate.py`), so 68 at runtime. The ticket said about 56; the extra ones are mostly post-redesign additions (email x3, feature flags x2, topic checklists x2, `course_chunk_sources`, `room_bans`, `encryption_key_check`, gamification). Note the stack is plain PG 16, not a real Supabase stack (production and `config.toml` are PG 15).
- **Policies.** The draft SQL in the appendix was applied to that scratch DB twice (idempotent) and exercised with `SET ROLE authenticated` plus `request.jwt.claims`: user B sees none of A's notes, gradebook rows or tutor messages; sees the public room but not the private one; sees class stats only for an offering B is enrolled in; sees shared chunks and not A's private ones. B cannot join A's private room, cannot add a gradebook category to A's enrollment, and cannot write `documents.index_status` (column grant). A GoTrue-style `authenticated` token (Supabase Auth issuer, uuid sub) sees zero rows even in catalog tables. A coverage query confirms every command granted to `authenticated` has at least one policy, and no policy references `auth.uid()`.
- **`auth.uid()` with our ids.** `select auth.uid()` with `sub = 'user_B'` raises `invalid input syntax for type uuid: "user_B"` (22P02) on the stack using Supabase's real definition. Confirmed.
- **Routes.** FastAPI introspection of `main.app` (venv in `/tmp`, `PYTHONDONTWRITEBYTECODE=1`, FastAPI 0.138's `_IncludedRouter` walked via `original_router` + `include_context.prefix`): **223 route handlers**, 111 with path params, 31 `async`, 192 sync. 58 are admin (`/api/admin/*` + `/api/gemini-test`).
- **Local JWT secret.** The committed local service key (`backend/.env.local.example:13`) decodes to `{"alg":"HS256"}` / `{"iss":"supabase-demo","role":"service_role"}`, and its signature verifies against the Supabase CLI default secret `super-secret-jwt-token-with-at-least-32-characters-long`. So local and CI use the legacy HS256 shared secret.
- **Not verified:** staging/prod key setup (legacy secret vs. migrated signing keys). The public JWKS endpoint was blocked by the sandbox proxy (CONNECT 403). Also unverified: whether hosted Supabase lets `postgres` `GRANT <custom role> TO authenticator`, and whether GoTrue signups are disabled on staging/prod.

## 1. Table inventory and policies

### 1.1 The identity anchor (used by every policy)

```sql
CREATE SCHEMA IF NOT EXISTS app_auth;          -- not in [api].schemas, so not exposed
CREATE OR REPLACE FUNCTION app_auth.uid() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT CASE
    WHEN (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'iss') = 'sapling-api'
    THEN nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')
  END
$$;
```

Rules:

- Every policy is `TO authenticated` and is anchored on `(SELECT app_auth.uid())`. The `SELECT` wrapper makes Postgres evaluate it once per statement (initPlan), not per row.
- Reading `request.jwt.claims` directly (rather than `auth.jwt()`) keeps the migration appliable on a bare Postgres, the same posture as the repo's guarded role DO blocks.
- The `iss` pin means only tokens the backend minted resolve to a user. Any other `authenticated` token (for example one from a Supabase Auth signup, enabled by default in `config.toml:179` `enable_signup = true`) resolves to NULL, so even "any signed-in user" catalog policies deny it. Verified in scratch.
- Membership checks that would recurse into their own table's RLS use `SECURITY DEFINER` helpers with `SET search_path = ''`: `app_auth.is_room_member(room_id)`, `app_auth.owns_room(room_id)`, `app_auth.owns_enrollment(enrollment_id)`, `app_auth.enrolled_in_offering(offering_id)`. EXECUTE goes to `authenticated` and `service_role` only.

Shorthand below: `U` = `(SELECT app_auth.uid())`. "own(col)" = SELECT `USING (col = U)`, INSERT `WITH CHECK (col = U)`, UPDATE `USING (col = U) WITH CHECK (col = U)`, DELETE `USING (col = U)`, generated for the listed commands. The exact SQL for every table is in the appendix (137 policies, 61 grant lines).

Writes that stay service-only are marked "svc". That is a separate decision from RLS: the minted JWT never leaves the backend, so these are server decisions (awards, account state, indexing, aggregates) that no route should be able to make under a user scope.

### 1.2 Bucket A: owned directly by one user (23 tables)

| Table | Policy (authenticated) | Grant | Notes |
|---|---|---|---|
| users | SELECT `id = U` | SELECT | All writes svc: `is_approved`, `deleted_at`, `total_xp`, streaks are account state read by `auth_guard`. |
| user_profiles | own(user_id) S/I/U | S,I,U | Other people's names go through svc helpers (section 3). |
| user_settings | own(user_id) S/I/U | S,I,U | `profile_visibility`, `share_class_context`, `analytics_opt_out` are user-editable. |
| oauth_tokens | own(user_id) S/I/U/D | all | Calendar routes run as the user. |
| gradescope_credentials | own(user_id) S/I/U/D | all | |
| enrollments | own(user_id) S/I/U/D | all | Written by `graph_service` add/remove course. |
| documents | own(user_id) S/I/U/D | S,I,D + UPDATE on (file_name, category, summary, concept_notes, flashcards, processed_at, deleted_at, extracted_text, shareability, shareability_confidence, offering_id) | `index_*` columns are owned by `document_indexing` (svc). |
| notes, flashcards, sessions, quiz_attempts, quiz_context, study_guides, graph_nodes, graph_edges | own(user_id) S/I/U/D | all | |
| feedback, issue_reports | own(user_id) S/I | S,I | Admin reads are svc. |
| user_achievements | own(user_id) S/U | SELECT + UPDATE (is_featured) | Awards are svc (`achievement_service`). |
| user_cosmetics, user_roles, xp_events | own(user_id) S | SELECT | Writes svc (awards, admin). |
| friend_requests | SELECT/UPDATE/DELETE `from_user_id = U OR to_user_id = U`; INSERT `from_user_id = U` | all | |
| friendships | SELECT/INSERT/DELETE `user_id = U OR friend_id = U` | S,I,D | Accept writes both directions in one upsert (`routes/social.py:923`). |

### 1.3 Bucket B: owned through a parent (9 tables)

| Table | Parent | Predicate (all granted commands) |
|---|---|---|
| messages | sessions | `EXISTS (SELECT 1 FROM sessions p WHERE p.id = messages.session_id AND p.user_id = U)` |
| node_mastery_events | graph_nodes | `EXISTS (... graph_nodes p WHERE p.id = node_id AND p.user_id = U)`; S,I only (append-only) |
| note_concepts | notes AND graph_nodes | both EXISTS (note is mine and concept node is mine); S,I,D |
| quiz_responses | quiz_attempts | `EXISTS (... quiz_attempts p WHERE p.id = attempt_id AND p.user_id = U)` |
| gradebook_categories, assignments, gradescope_course_links, topic_checklists, topic_checklist_progress | enrollments | `(SELECT app_auth.owns_enrollment(<t>.enrollment_id))` |

`apply_mastery_delta(...)` is SECURITY INVOKER and filters on `p_user_id`, so granting it EXECUTE to `authenticated` is safe: graph_nodes RLS still applies inside it.

### 1.4 Bucket C: shared between users (12 tables)

| Table | SELECT | Writes under user scope | svc writes |
|---|---|---|---|
| rooms | `U IS NOT NULL AND (is_public OR is_room_member(id))` | INSERT `owner_id = U AND created_by = U`; UPDATE `USING owner_id = U WITH CHECK owner_id = U` | Invite-code lookup and join (a private room is invisible until you join), owner transfer and last-member teardown in `leave_room` (`social.py:431-456`). |
| room_members | `is_room_member(room_id)` | INSERT self, not banned, and room is public or mine; DELETE self or room owner (kick) | Invite-code join. |
| room_bans | self or room owner | INSERT/UPDATE/DELETE by owner, `banned_by = U` | |
| room_messages | step 2e (bridge) | step 2e | |
| room_reactions | message's room is one I'm in | INSERT self + member; DELETE self | |
| room_activity | member | INSERT self + member | |
| room_summaries | member | none | Cache writes from `social_cache_service` (svc). |
| offering_concept_stats, offering_summary | `enrolled_in_offering(offering_id)` | none | `course_context_service.update_course_context` reads every classmate's graph and quiz context, so it must run svc. |
| course_chunks | `U IS NOT NULL AND (visibility = 'shared' OR uploader_id = U OR EXISTS contributor row for U)` | none | All indexing (`rag_service`, `chunk_visibility`, `document_indexing`). A user-scoped upsert onto a shared row another student uploaded fails with an RLS error (verified), which is the right outcome but means indexing must be svc. |
| course_chunk_contributors | `user_id = U` | none | svc |
| course_chunk_sources | chunk is readable to me | none | svc |

The `course_chunks` SELECT mirrors `match_course_chunks` exactly (parity, not tightening). The #758 live-source rule stays in the function, since it is retrieval policy rather than access control.

### 1.5 Bucket D: catalog / public read (12 tables)

`schools, terms, courses, course_offerings, achievements, achievement_triggers, achievement_cosmetics, cosmetics, roles, role_cosmetics, growth_stages, xp_rules`: SELECT `U IS NOT NULL`, grant SELECT only. All writes svc (admin portal, `academics.resolve_offering` creating an offering on demand, seeds, `ingest_catalog`). Unauthenticated catalog routes (`GET /api/semesters`, `GET /api/onboarding/courses`) run svc (section 3).

### 1.6 Bucket E: service-only (12 tables + ledger)

`events, llm_usage, feature_flags, feature_flag_targets, admin_audit_log, email_broadcasts, email_sends, email_suppressions, newsletter_emails, job_applications, encryption_key_check, jobs`, plus `schema_migrations`. No grants to `authenticated`, no policies; #807's state is already correct. (`jobs` is the #116 job queue; its migration, `20261108095241_jobs_queue.sql`, enables RLS and revokes anon/authenticated itself.) `routes/quiz.py`'s one `llm_usage` read must run inside `service_scope()`.

### 1.7 Gaps in #807 to close in step 2a

1. **Function EXECUTE still defaults to PUBLIC.** On the replayed schema, `has_function_privilege('anon', ...)` is true for `match_course_chunks` and `set_updated_at`. Today that is harmless (the table grants are gone, and both are SECURITY INVOKER), but the default privilege on FUNCTIONS was not revoked. So the next `SECURITY DEFINER` function a migration adds would be callable with the public anon key. Fix: `REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC, anon, authenticated` plus `ALTER DEFAULT PRIVILEGES ... REVOKE EXECUTE ON FUNCTIONS`, then explicit grants. I verified that revoking EXECUTE on `set_updated_at` does not stop its triggers firing.
2. **`test_rls_lockdown_db.py` asserts `authenticated` holds no table privileges.** Step 2c deliberately grants some, so that test has to change in the same PR: `anon` none; `authenticated` only on an allowlisted set; every granted command covered by a policy; no policy calls `auth.uid()`. The coverage query is in section 6.
3. **`room_messages` drift.** It is exempt in #807. Locally and in CI it has RLS off and Supabase's default anon DML. In production it has RLS on from the June hand-applied lockdown, with whatever `authenticated` grants that left. Nothing pins the production state. Step 2e fixes this.
4. Minor: default-privilege changes only cover objects created by the migration role (#807 says so). Storage policies are a separate track (`docs/security/storage-hardening-plan.md`).

## 2. Identity to PostgREST

### 2.1 Mint a short-lived JWT per request (yes, this works)

PostgREST accepts any JWT its project trusts, switches to the role in the `role` claim, and exposes the claims as `request.jwt.claims`. Supabase's docs say a self-minted JWT goes in `Authorization: Bearer <JWT>`, and that the separate `apikey` header must stay a project API key ("Using your minted JWT is not possible in this header"). Source: https://supabase.com/docs/guides/auth/signing-keys

Claims and header:

```
header  {"alg": "ES256" | "HS256", "kid": "<key id>", "typ": "JWT"}
payload {"iss": "sapling-api", "sub": "<users.id>", "role": "authenticated",
         "aud": "authenticated", "iat": now, "exp": now + 300}
```

- 5-minute expiry; cache per user for about 4 minutes. ES256 signing is about tens of microseconds with the already-installed `cryptography` (DER signature converted to raw r||s via `decode_dss_signature`); HS256 is stdlib `hmac`, as `services/session_tokens.py` already does. No new dependency.
- `apikey` header: the project's anon (legacy) or publishable (new) key. New env `SUPABASE_ANON_KEY`. The backend has never held one; only the frontend does (`NEXT_PUBLIC_SUPABASE_ANON_KEY`).
- The token never leaves the backend. RLS here protects against route bugs, not a hostile client. Section 2.4 covers the browser case.

### 2.2 Which signing setup applies

| Environment | Evidence | Signing |
|---|---|---|
| Local + CI | `supabase/config.toml:171-172` has `signing_keys_path` commented out; `backend/.env.local.example:13` and `frontend/.env.local.example:16` are HS256 tokens with `iss: supabase-demo`, and I verified the signature against the CLI default secret. | Legacy HS256 shared secret (`super-secret-jwt-token-with-at-least-32-characters-long`). |
| Staging / prod | `backend/.env.staging.example:16` and `docs/staging/setup-checklist.md:18` only say "service_role key". `docs/security/realtime-jwt-bridge-design.md` assumes HS256 and says to confirm at build time. No `SUPABASE_JWT_SECRET` exists anywhere in the repo. | **Unverified.** Check the dashboard JWT Keys page, or `curl https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` (an empty `keys` list means legacy only). |

What each case means, from the Supabase signing-keys doc:

- **Legacy HS256 still current:** we can mint with the legacy secret today. It stays trusted after a later migration until someone revokes it. The doc warns the legacy secret "can be compromised, if you mint your own JWTs". In practice it is no more powerful than the `SUPABASE_SERVICE_KEY` the backend already holds, since both can produce a `service_role` token.
- **Migrated to asymmetric keys:** Supabase-generated private keys cannot be extracted ("extracting of the private key or shared secret from Supabase is not possible"). The supported path for minting your own tokens is to generate a key (`supabase gen signing-key --algorithm ES256`), import it as a standby key and rotate to it. A newly created standby key is not yet accepted for verification; only the current key and previously used keys are. Revocation is instant for the Data API.

**Recommendation.** Build the minting seam once, keyed off a JWK in `SUPABASE_JWT_SIGNING_KEY` (`kty: EC` gives ES256, `kty: oct` gives HS256, `kid` from the JWK). Local and CI use the `oct` JWK of the CLI default secret. Staging, then prod: generate an ES256 key, import it, rotate to it. Because Sapling does not use Supabase Auth, rotation does not sign anyone out, and the legacy anon and service keys keep working until someone revokes the legacy secret. This removes the dependence on a secret Supabase calls deprecated, and it works whichever state the hosted projects are in. Add `SUPABASE_JWT_SIGNING_KEY` and `SUPABASE_ANON_KEY` to `config.validate_config()` as required outside local, from the release that ships `shadow` onward.

### 2.3 `auth.uid()` vs `auth.jwt()->>'sub'`

Use neither directly. Use `app_auth.uid()`, which reads `sub` as TEXT and pins `iss`.

- `auth.uid()` casts `sub` to uuid. With `user_<google id>` it raises 22P02 (verified), so every query would turn into a PostgREST 400.
- Plain `auth.jwt()->>'sub'` works but trusts any token the project signs, including Supabase Auth signups.
- Users are not in `auth.users`, and nothing in the policies refers to it.

### 2.4 The `role` claim

- Use `role: "authenticated"`. PostgREST switches to that role; it is the role #807 already revokes and the one Supabase Realtime understands. `iss: "sapling-api"` (enforced in `app_auth.uid()`) is what separates our tokens from any other `authenticated` token.
- Considered and rejected for now: a custom `sapling_api` role granted to `authenticator`. It gives cleaner separation, but whether hosted Supabase lets `postgres` grant roles to `authenticator` is unverified, and the `iss` pin already does the job.
- For the realtime bridge (2e) the browser gets a different token: `iss: "sapling-realtime"`, same `role: authenticated`. A separate helper `app_auth.realtime_uid()` accepts only that issuer, and the only policy using it is SELECT on `room_messages`. A student who extracts their realtime token from the browser and calls PostgREST directly then gets read access to their own rooms' messages and nothing else. This is why every write policy is anchored on `app_auth.uid()` and not on a bare `sub`.
- Hygiene: disable Supabase Auth signups on staging and prod (Auth settings). Not required for safety given the `iss` pin, but there is no reason to leave it on.

## 3. Service-role callers vs. user-scoped request paths

Evidence: `grep -rn "table(\|rpc(\|page_all(" backend/{routes,services,agents}` gives 588 `table(` call sites. The per-module table map, the thread/task greps, and `psycopg` and `SUPABASE_SERVICE_KEY` greps are summarized here.

### 3.1 Not affected by RLS at all (connect as `postgres`, the table owner; #807 does not FORCE RLS)

- `db/migrate.py` (psycopg on `SUPABASE_DB_URL`)
- `backend/promotion/` (`__main__.py:26,226,324`: psycopg for ledger, snapshot, migrate)
- `backend/e2e_oracles/gather.py:85-89` (psycopg); its `_authed_get` HTTP leg goes through the app as the user, so it exercises the user scope
- integration conftest truncate (psycopg) and `frontend/e2e/support/db.ts` (`pg` as postgres)
- `scripts/migration_drift_report.py`
- `services/storage_service.py:26-27` (Storage API with the service key; not PostgREST, out of scope)

### 3.2 PostgREST callers that keep the service role

Default rule (section 4): a `table()` call outside any HTTP request is service, so these need no code change.

- **Lifespan workers:** `services/index_sweeper.py:89` (`rpc("claim_documents_for_indexing")`, EXECUTE granted to service_role only), `services/local_seed_watcher.py`, `services/encryption_canary.py`, `services/events_service.py` (its own `threading.Thread` writes `events`/`llm_usage`), the PostHog worker (`services/posthog_client.py` + `services/analytics_consent.py` reading `user_settings`), DBOS (off everywhere per ADR 0011; its system schema is its own).
- **Scripts and seeds:** `db/seed_local_rich.py`, `seed_local_owner.py`, `seed_showcase.py`, `seed_local_catalog.py`, `seed_helpers.py`, `db/backfill_encryption.py`, `db/e2e_staging_http.py` (its fixture writes), and `scripts/backfill_*`, `dedupe_course_chunks.py`, `ingest_catalog.py`, `move_unapproved_users_to_waitlist.py`, `seed_quiz_fixture.py`.

Inside a request, these must opt out explicitly:

- **Router-level svc** (one dependency per router, see 4.3):
  - `routes/admin.py` (53 call sites), `admin_analytics.py`, `admin_documents.py`, `admin_email.py` (16), `admin_flags.py`, and `/api/gemini-test`
  - `routes/internal_metrics.py:129` (`rpc("canopy_metrics")`, service_role-only EXECUTE)
  - `routes/careers.py`, `routes/newsletter.py`, `routes/email.py` (unsubscribe), all unauthenticated
- **Pre-identity reads:** `services/auth_guard.py` (`_read_account_state` reads `users`; `require_admin` reads `user_roles`) and `services/feature_flags.py` (`feature_flags`, `feature_flag_targets`, `user_roles`). The flag reads must be svc or the scope check would recurse into the flag that decides it.
- **Auth flows in `routes/auth.py` (21 sites):** the OAuth callback upserts `users`, `newsletter_emails` and `oauth_tokens`; `POST /test-login`; `/pending/*`; first-login achievements.
- **Server-decided writes:**
  - `services/achievement_service.py` (27 sites; `user_achievements`/`user_cosmetics` upserts, reads of other users' rows when counting)
  - `services/xp_service.py`, `services/streak_service.py` (writes to `users`)
  - `services/email_service.py` (`email_sends`/`email_suppressions`)
  - `services/admin_audit.py`
  - `services/academics.py`'s on-demand `course_offerings` insert
- **Cross-user computation** (wrap the function in `service_scope()`):
  - `services/course_context_service.py::update_course_context`. Called inline from `apply_graph_update` and as a post-roll/BackgroundTask in `routes/documents.py` and `routes/profile.py`. Under a user scope it would silently compute class stats from one student.
  - `services/document_indexing.py::index_document`, `services/rag_service.py::index_document_chunks`, and all of `services/chunk_visibility.py` (`record_contributors`, `resync_user_chunk_visibility`, a BackgroundTask in `routes/profile.py`).
  - `services/social_cache_service.py` (room summary cache writes).
- **Cross-user projections** (narrow `service_scope()` reads, allowlisted):
  - `services/profiles.py::get_display_names` (room members, friends)
  - `services/users_search.py`
  - the gamification leaderboard (friends' XP)
  - `GET /api/profile/{user_id}` when viewer != owner, which applies `profile_visibility` in code (`profile.py:298-325`)
  - `GET /api/profile/{user_id}/roles` and `/username/check` (unauthenticated)
  - the social invite-code join, ownership transfer and room teardown
- **Account deletion:** `profile.delete_account` soft-deletes `users` (svc). The `resync_user_chunk_visibility` and `update_course_context` BackgroundTasks are svc via `service_scope`. `delete_posthog_person` is a third-party call with no DB involved.

### 3.3 Request paths that switch to the user-scoped client

Everything else, which is the bulk of the 588 sites:

- `routes/graph.py`, `notes.py` + `services/notes_service.py`
- `documents.py` CRUD and upload insert
- `learn.py` + `services/tutor_sessions.py` + `chat_stream.py`
- `quiz.py` + `quiz_*` services
- `flashcards.py`, `study_guide.py`, `gradebook.py`, `gradescope.py`, `calendar.py`, `topic_checklist.py`
- `onboarding.py` profile writes, `profile.py` self routes
- `gamification.py` `/me` and `/activity`
- `social.py` room, message and friend operations
- the agent read tools (`agents/tools/graph_read.py`, `chat_context.py`, `quiz_history.py`), which call `table()` through `asyncio.to_thread` and so inherit the request context

## 4. Integration design

### 4.1 Where the identity comes from

The request needs a subject before any handler code runs. Do not rely on the guard's stamp alone: `routes/quiz.py::_load_owned_attempt` (`:316-328`) reads the attempt **before** `require_self`, and other "load, then check owner" sites exist.

- Add a pure-ASGI step (or extend `RequestIDMiddleware._dispatch`) that runs `auth_guard._decode_session` (HMAC and expiry only, pure CPU, no DB) and writes `scope["state"]["db_subject"] = user_id`. Use a separate key from `request.state.user_id`, which keeps its meaning of "fully authenticated" for PostHog and error attribution.
- `scope["state"]` is the dict `services/request_context.py::RequestView` already shares with threadpool `Depends`, `asyncio.to_thread`, BackgroundTasks and post-roll tasks, and it survives `view.detach()`. So the subject follows the request everywhere the request context goes. Add `current_db_subject()` next to `current_session_user()`.
- A deleted or unapproved account with a still-valid cookie gets a client scoped to its own rows until the guard 401s or 403s it. That is acceptable, since it can only see its own data.

### 4.2 `table()` resolution (in `db/connection.py`, plus a new `db/scope.py`)

`table(name)` keeps its signature (see the test note in 6.5); the opt-out is a context manager, `with service_scope():`, or the `@runs_as_service` decorator, from `db/scope.py`. One shared `httpx.Client` stays; a scoped call overrides the `Authorization` and `apikey` headers per request (httpx merges per-request headers over client defaults). The order, first match wins:

1. A `service_scope()` block or `@runs_as_service` function is active (a ContextVar) gives service. Used for the auth guard's reads, the flag store, the public projections and `update_course_context`, `index_document`, `chunk_visibility.*`, the achievement, XP and email services.
2. The request is marked service at router level (`scope["state"]["db_scope"] == "service"`) gives service.
3. In a request with a `db_subject`, the mode comes from `flag_variant("db_user_scope", subject)`, memoized on `scope["state"]` (one flag resolution per request, read as svc):
   - `off`: service.
   - `shadow`: service is authoritative; a sampled fraction of SELECTs also runs scoped, and divergence is logged (4.4).
   - `enforce`: a minted user JWT.
4. In a request with no subject:
   - `enforce`: raise `UnscopedQueryError` (500 + `db.unscoped_query` event). Fail closed.
   - `off`/`shadow`: service, plus the same event at WARN. That event is how the remaining unmarked call sites get found before enforce.
5. Outside any request (no `_REQUEST_CTX`: lifespan tasks, worker threads, scripts, seeds): service. This keeps workers working without code changes. The cost is that a future thread that escapes the request context silently gets service; section 6 adds a check for it.

`rpc()` follows the same rules, so `match_course_chunks` and `apply_mastery_delta` run scoped once they have the EXECUTE grants from 2c.

### 4.3 Router-level opt-out

```python
app.include_router(admin_router, prefix="/api/admin",
                   dependencies=[Depends(admin_service_scope)])  # runs require_admin, then marks svc
app.include_router(careers.router, prefix="/api/careers",
                   dependencies=[Depends(public_service_scope)])
```

This mirrors the existing `nav_feature_gate` mounting pattern in `main.py`. The admin dependency re-checks admin (a cheap cached read) before marking, so a non-admin never gets a service-scoped admin route even if a handler forgets `require_admin`.

### 4.4 Flag, rollout and fail-safe behavior

- **Flag.** `FlagDef("db_user_scope", ("off", "shadow", "enforce"), ..., client_visible=False)` in `services/feature_flags.py::REGISTRY`. `variants[0] == "off"` per ADR 0029. It is per user, so the admin per-user and per-role rules and the stable percentage rollout all work. Kill switch: `SAPLING_FLAG_DB_USER_SCOPE=off`.
- **Shadow** compares only reads. For a sampled 10% of `select`/`select_with_count`, it runs the same query scoped and compares row count and the set of `id`s (never content). On a mismatch it logs `db.rls_shadow_divergence` with table, route template and the two counts. Writes are not shadowed; they are covered by the integration matrix and staging enforce.
- **Fail closed in enforce:**
  - Mint failure (key missing or bad) gives 503. Never fall back to service.
  - PostgREST 401 (token rejected, for example a kid or JWKS mismatch after rotation) gives 503 plus an ERROR log. Never retry as service.
  - PostgREST 42501 / 403 (RLS `WITH CHECK` violation or a missing grant) raises `ScopedAccessDenied`, which a FastAPI handler maps to **404** and logs `db.rls_denied` with table and route. A row filtered by `USING` already reads as "not found".
  - Unscoped query: 500 (see 4.2 step 4).
- **The fail-closed inversion.** ADR 0029 resolves an unreadable flag store to `off`, and for this flag `off` is the less secure state. So a flag-store outage downgrades everyone to service role. Accept it during rollout. Once prod has run at 100% enforce for a release, **graduate**: delete the flag and make enforce unconditional, keeping only the env kill switch.
- **PostgREST details to handle:** inserts use `Prefer: return=representation`, so the returned row must pass the SELECT policy. Every table with INSERT has an own-row SELECT policy (verified by the coverage query). Upserts need INSERT, UPDATE and SELECT policies; the grants follow that.
- **Allowlist test.** `tests/test_service_scope_allowlist.py` greps `service_scope(` and `runs_as_service` and compares them against a checked-in list with a one-line reason each, in the same style as `test_migration_naming.py`. A new opt-out then shows up in review.

## 5. Cross-user test matrix

**Where:** the integration lane (`.github/workflows/integration.yml`: local Supabase via `supabase start` from `config.toml`, `db.migrate`, `seed_local_rich`, `SAPLING_MODEL_MODE=function`, `RUN_INTEGRATION=1 pytest -m integration`). It already runs on every PR and boots the real app against real PostgREST. A new `backend/tests/integration/test_cross_user_matrix_db.py` is parametrized over flag mode (`off` and `enforce`, via `SAPLING_FLAG_DB_USER_SCOPE`). Local run: `docs/local-supabase.md` section "Integration tests (opt-in, #362)". This needs no E2E stack lock, since it uses TestClient and not `make e2e-up`.

**Users:** `seed_local_rich` already creates `rich-user-active` (A, with notes, documents, sessions, quiz attempts, flashcards, study guides, gradebook, rooms, chunks) and `rich-user-second` (B). Both are enrolled in `OFF_CS_S26`, which gives the classmate case for the shared tables. The matrix uses the conftest's `_client_for(user_id)` cookie helper. Add a private room A owns and B is not in, a pending friend request A to C, and one private chunk of A's.

**Enumerating endpoints:**

- Walk `main.app.routes`. On FastAPI 0.138 these are `_IncludedRouter` objects, so recurse into `r.original_router.routes` and prefix with `r.include_context.prefix`; a plain `APIRoute` filter sees only 2 routes.
- For each `APIRoute`, collect id-like inputs from the path (`{x_id}`), query (`r.dependant.query_params`) and body fields (`r.dependant.body_params[*]` model fields), matching `_id$|_ids$`.
- An `ID_SOURCES` registry maps each param name to a query for one of A's rows (`note_id` gives `SELECT id FROM notes WHERE user_id = A LIMIT 1`, and so on). The test **fails** when a route has an id param with no registry entry and no explicit exclusion, so new routes join the matrix automatically.
- Bodies are built from the route's Pydantic model with the id fields overridden. A 422 counts as a test failure, not a pass, so a route can't go green by never reaching its handler; such routes get a per-route body override.

**Size** (from the introspection):

| Group | Cases | Expected |
|---|---|---|
| Resource id belongs to A, B's own session and `user_id` | 107 (62 path, 40 body, 5 query) across 33 distinct param names; about 95 after excluding non-resource ids (`turn_id`, `popup_id`, `question_id`, external `gradescope_course_id`, catalog `role_id`/`cosmetic_id`/`achievement_ids`, onboarding `course_ids`) | **404**, and no A-owned marker in the body. `request_id` stays in: replaying A's `X-Request-ID` must not return A's document. |
| B's session with `user_id = A` | 129 | 403 (the `require_self` contract, unchanged) |
| Admin routes as B | 58 | 403 |
| Intentionally cross-user reads (public profile, public rooms list, room overview for a public room, class stats for a shared offering) | about 8, allowlisted | 200 with only the projection fields |

That is about 290 cases per mode, about 580 per run, at tens of milliseconds each against local Supabase.

- Under `off`, some resource cases will return 403 rather than 404, because today's code calls `require_self(row.user_id)` after loading the row. A `KNOWN_403` list records them; it must shrink to zero under `enforce`, where RLS makes the row invisible first.
- Also in the lane: `test_rls_policies_db.py`. It covers the coverage query from section 6, a token with the wrong `iss` seeing nothing, the class-stats aggregate run as user A still counting both students (proving `update_course_context` is svc), and B's upload into a shared chunk still indexing (svc).

## 6. Rollout order and risks

### 6.1 Migration sequence

All append-only, named with `date -u +%Y%m%d%H%M%S`, idempotent (`DROP POLICY IF EXISTS` before `CREATE POLICY`, guarded role DO blocks). Nothing below is flagged by `promotion/preflight.py`'s destructive scan (DROP TABLE/COLUMN/VIEW, TRUNCATE, ALTER COLUMN TYPE, RENAME).

| Step | Migration / change | Effect on running code |
|---|---|---|
| 1 | #807 `20261108082151_rls_on_every_table.sql` (merge first) | none (service_role bypasses) |
| 2a | `<ts>_rls_app_auth_helpers.sql`: `app_auth` schema, `uid()`, membership helpers, function EXECUTE hygiene | none |
| 2b | `<ts>_rls_policies.sql`: buckets A-D policies (appendix) | none: `authenticated` has no grants yet, and no `sapling-api` token exists |
| 2c | `<ts>_rls_grant_authenticated.sql`: table and column grants + EXECUTE on `match_course_chunks` and `apply_mastery_delta`; update `test_rls_lockdown_db.py` in the same PR | none in practice: only backend-minted tokens resolve to a user, and none are minted yet |
| code | `db/scope.py` (`service_scope`, scoped headers in `table()`/`rpc()`), subject stamping, router opt-outs, `service_scope` on the section 3.2 functions, `db_user_scope` flag, `ScopedAccessDenied` handler, matrix tests; ships with the flag `off` | none until the flag moves |
| 2d | Key setup per environment (no migration): import ES256 key, rotate, set `SUPABASE_JWT_SIGNING_KEY` and `SUPABASE_ANON_KEY` | none |
| 2e | `<ts>_rls_room_messages.sql` + the realtime bridge (`GET /api/auth/realtime-token`, `app_auth.realtime_uid()`, SELECT policy for members, user-scoped INSERT/UPDATE for authors). Remove the #807 exemption and `EXEMPT` in the test; update `frontend/e2e/study-room.spec.ts` to call `setAuth` | live chat on local/CI moves from anon to the bridge token |
| 3 | Graduate: delete the flag, enforce unconditionally | |

### 6.2 Verifying on staging before prod

- **Migrations.** Merging to `main` runs `migrate-staging.yml`. On staging, check with catalog SQL:
  - `relrowsecurity` on every table;
  - no `anon` grants;
  - for `authenticated`, the coverage query returns zero rows:
    ```sql
    SELECT t.relname, p.priv FROM pg_class t
      CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p(priv)
     WHERE t.relnamespace = 'public'::regnamespace AND t.relkind = 'r'
       AND has_table_privilege('authenticated', t.oid, p.priv)
       AND NOT EXISTS (SELECT 1 FROM pg_policy po WHERE po.polrelid = t.oid
             AND po.polcmd IN ('*', CASE p.priv WHEN 'SELECT' THEN 'r'
                 WHEN 'INSERT' THEN 'a' WHEN 'UPDATE' THEN 'w' ELSE 'd' END));
    ```
  - no policy expression matches `(^|[^_])auth\.uid`.
- **`make promote`.** Its preflight refuses DDL that staging has not run (`STAGING_SUPABASE_DB_URL`). The migrations apply to prod before the code merges, which is safe here because 2a-2c are inert for service_role. The smoke checks (`promotion/smoke.py`) include unauthenticated `GET /api/semesters` → 200, which catches a public route that lost its svc marking.
- **Per-step staging checks for the code rollout:**
  1. Deploy with the flag `off`. Watch `db.unscoped_query` WARN events and fix them until there are none.
  2. `shadow` for everyone on staging. Watch `db.rls_shadow_divergence` until there are none.
  3. `enforce` via a per-role rule for admins and test accounts. Run `dotenv -f .env.staging run -- SAPLING_FLAG_DB_USER_SCOPE=enforce python -m db.e2e_staging_http` (the existing staging HTTP harness drives the real app via TestClient). Also run the cross-user matrix module against staging data.
  4. `enforce` at 100% on staging for at least a day of real-mode traffic. This is the only place the course_chunks indexing and embedding paths run, since the function-mode lanes skip embedding. Note that #806 makes the index sweeper production-only, so staging re-drive coverage comes from the admin re-index route.
- **Prod.** Same ladder (`shadow`, then admins, then 10/50/100% rollout), with the env kill switch on hand.

### 6.3 Riskiest tables and paths

1. **`course_chunks` and its two ledgers.** Content-addressed shared rows mean any user-scoped upsert onto a classmate's row fails (verified). Every indexing path must be svc, including post-roll tasks that inherit the request context. Retrieval-quality risk: RLS quals run as a filter after the ivfflat scan, so `match_course_chunks` with `match_count = 5` could return fewer rows for students with many private chunks. Measure recall in shadow.
2. **`offering_concept_stats` / `offering_summary` via `update_course_context`.** The failure mode is silent: run user-scoped, it "works" and writes stats computed from one student. Only an aggregate assertion catches it (the section 5 test).
3. **Social: `rooms`, `room_members`, `friendships`, `user_profiles`.** These are the most cross-user code paths: invite-code join, owner transfer, two-sided friendship rows, display names. The policies cover the simple cases; the rest must be svc. Move social to enforce last.
4. **`users` and `user_roles`.** The guard reads them before any identity exists. Missing a svc mark there gives a 500 on every request in enforce. The flag store reads `user_roles` too.
5. **`documents`.** It mixes user-owned columns with indexing-owned `index_*` lease columns, written in the same request through post-roll. The column grant makes a mis-scoped indexer fail loudly instead of corrupting the lease.

### 6.4 What would break the `SAPLING_MODEL_MODE=function` E2E lanes

- `POST /api/auth/test-login` has no session yet and writes `users`, so it must be svc, or every Playwright journey fails at login.
- `local_seed_watcher` and the seeds are outside a request, so they stay service with no change.
- In function mode the upload post-roll does not embed, so the course_chunks write path is **not** exercised by E2E under enforce. A green E2E run proves nothing about indexing; see staging step 4.
- Study rooms: `frontend/e2e/study-room.spec.ts` relies on anon realtime `postgres_changes` on `room_messages`. Step 2e breaks it until the spec uses the bridge token, so 2e must ship the spec change with it.
- Flag state: `feature_flags`/`feature_flag_targets` are truncated per test and re-seeded (ADR 0029 section 9), so a lane that wants enforce should use the env override `SAPLING_FLAG_DB_USER_SCOPE=enforce` in `scripts/e2e-up.sh`, not a DB row. The flag lookup is one svc read per request with the TTL at 0.
- Oracles connect as postgres and are unaffected. The `graph` oracle's HTTP leg runs scoped, which is useful coverage.
- Function-mode handlers make no extra DB calls of their own, so no handler changes are needed.

### 6.5 Other risks

- Test churn: route tests that assert 403 for another user's resource become 404 under enforce (`KNOWN_403`).
- Hermetic unit tests patch `<module>.table` with one-argument fakes (for example `tests/conftest.py:112`, `lambda name: ...`). An `as_service=True` keyword at call sites would break those fakes, and a separate `service_table()` import would escape the patches and hit the conftest's fake `_client`. That is why the opt-out is a context manager and `table(name)` keeps its signature.
- A thread started with `threading.Thread` or `ThreadPoolExecutor` from inside a request loses the context and silently runs as service (4.2 step 5). Today only `services/extraction_backends/gemini_vision_backend.py` does this, and it copies the context explicitly. Add a ruff ban or a grep test on new raw thread sites in `routes/` and `services/`.
- Performance: one extra header and a cached token per call; the policy subqueries are index-backed (`idx_graph_nodes_user` and the enrollment PKs). The `SECURITY DEFINER` helpers are STABLE and wrapped in `SELECT`, so they are evaluated once per statement.

## 7. Open questions

1. Staging/prod signing state (legacy HS256 vs. migrated). Check the JWKS endpoint or the dashboard before 2d.
2. Are Supabase Auth signups disabled on staging/prod? Not needed for safety, but they should be off.
3. Should shared `course_chunks` be limited to students enrolled in an offering of that course? Today's function serves shared rows to anyone who asks for that `course_id`. Parity first; tightening changes tutor behavior.
4. Is the custom-role route (`GRANT sapling_api TO authenticator`) allowed on hosted Supabase, if we ever want role-level separation from the realtime token?
5. Does Supabase Realtime evaluate RLS for `postgres_changes` with our self-minted `sapling-realtime` token as the bridge design assumes? Verify in 2e on local first.
6. Does #807's production apply match the June hand-applied state for `room_messages` grants? Capture `\dp room_messages` on prod before 2e.

## Appendix: draft SQL (applied twice to the scratch PG 16 replay; generated by docs/security/rls-step2/gen_policies.py)

Section 1 already covers the reasoning behind each policy; this is the literal SQL. In the migrations, each CREATE POLICY is preceded by `DROP POLICY IF EXISTS <name> ON <table>;` (omitted here for length). The grant block is wrapped in a guard that returns early on a bare Postgres without the `authenticated` role.

```sql
-- DRAFT for <ts>_rls_app_auth_helpers.sql (step 2a). Not in the repo.
-- Identity helpers every policy is anchored on, plus function EXECUTE hygiene
-- that #807 left open.

CREATE SCHEMA IF NOT EXISTS app_auth;
REVOKE ALL ON SCHEMA app_auth FROM PUBLIC;

-- The Sapling user a request runs as, or NULL. Reads the claims PostgREST
-- sets per request. Only tokens the backend minted count (iss pin), so a
-- GoTrue-issued `authenticated` token (Supabase Auth signups are on by default)
-- resolves to NULL and every policy denies it. TEXT, never uuid: users.id is
-- `user_<google id>`, and auth.uid() casts to uuid and raises 22P02 on it.
CREATE OR REPLACE FUNCTION app_auth.uid() RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
    SELECT CASE
        WHEN (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'iss') = 'sapling-api'
        THEN nullif(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', '')
    END
$$;

-- Membership checks. SECURITY DEFINER so a policy on room_members can ask
-- "is the caller a member of this room" without recursing into its own RLS.
CREATE OR REPLACE FUNCTION app_auth.is_room_member(p_room_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.room_members m
                    WHERE m.room_id = p_room_id AND m.user_id = app_auth.uid())
$$;

CREATE OR REPLACE FUNCTION app_auth.owns_room(p_room_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.rooms r
                    WHERE r.id = p_room_id AND r.owner_id = app_auth.uid())
$$;

CREATE OR REPLACE FUNCTION app_auth.owns_enrollment(p_enrollment_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.enrollments e
                    WHERE e.id = p_enrollment_id AND e.user_id = app_auth.uid())
$$;

CREATE OR REPLACE FUNCTION app_auth.enrolled_in_offering(p_offering_id text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
    SELECT EXISTS (SELECT 1 FROM public.enrollments e
                    WHERE e.offering_id = p_offering_id AND e.user_id = app_auth.uid())
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_auth FROM PUBLIC;

-- #807 gap: EXECUTE on public functions still defaults to PUBLIC
-- (match_course_chunks and set_updated_at are callable by anon today).
-- Trigger functions do not need EXECUTE at fire time, so this is safe for
-- set_updated_at (verified on PG 16).
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

DO $$
DECLARE r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM %I', r);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM %I', r);
        END IF;
    END LOOP;
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC';
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role';
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_auth TO service_role';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA app_auth TO authenticated';
        EXECUTE 'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app_auth TO authenticated';
    END IF;
END $$;

-- ===== <ts>_rls_policies_owned_shared_catalog.sql (draft, generated) =====
CREATE POLICY users_select_own ON public.users FOR SELECT TO authenticated
    USING (id = (SELECT app_auth.uid()));
CREATE POLICY user_profiles_select_own ON public.user_profiles FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_profiles_insert_own ON public.user_profiles FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_profiles_update_own ON public.user_profiles FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_settings_select_own ON public.user_settings FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_settings_insert_own ON public.user_settings FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_settings_update_own ON public.user_settings FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY oauth_tokens_select_own ON public.oauth_tokens FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY oauth_tokens_insert_own ON public.oauth_tokens FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY oauth_tokens_update_own ON public.oauth_tokens FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY oauth_tokens_delete_own ON public.oauth_tokens FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY gradescope_credentials_select_own ON public.gradescope_credentials FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY gradescope_credentials_insert_own ON public.gradescope_credentials FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY gradescope_credentials_update_own ON public.gradescope_credentials FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY gradescope_credentials_delete_own ON public.gradescope_credentials FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY enrollments_select_own ON public.enrollments FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY enrollments_insert_own ON public.enrollments FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY enrollments_update_own ON public.enrollments FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY enrollments_delete_own ON public.enrollments FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY notes_select_own ON public.notes FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY notes_insert_own ON public.notes FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY notes_update_own ON public.notes FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY notes_delete_own ON public.notes FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY flashcards_select_own ON public.flashcards FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY flashcards_insert_own ON public.flashcards FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY flashcards_update_own ON public.flashcards FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY flashcards_delete_own ON public.flashcards FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY sessions_select_own ON public.sessions FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY sessions_insert_own ON public.sessions FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY sessions_update_own ON public.sessions FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY sessions_delete_own ON public.sessions FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_attempts_select_own ON public.quiz_attempts FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_attempts_insert_own ON public.quiz_attempts FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_attempts_update_own ON public.quiz_attempts FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_attempts_delete_own ON public.quiz_attempts FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_context_select_own ON public.quiz_context FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_context_insert_own ON public.quiz_context FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_context_update_own ON public.quiz_context FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY quiz_context_delete_own ON public.quiz_context FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY study_guides_select_own ON public.study_guides FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY study_guides_insert_own ON public.study_guides FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY study_guides_update_own ON public.study_guides FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY study_guides_delete_own ON public.study_guides FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_nodes_select_own ON public.graph_nodes FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_nodes_insert_own ON public.graph_nodes FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_nodes_update_own ON public.graph_nodes FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_nodes_delete_own ON public.graph_nodes FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_edges_select_own ON public.graph_edges FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_edges_insert_own ON public.graph_edges FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_edges_update_own ON public.graph_edges FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY graph_edges_delete_own ON public.graph_edges FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY documents_select_own ON public.documents FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY documents_insert_own ON public.documents FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY documents_update_own ON public.documents FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY documents_delete_own ON public.documents FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY feedback_select_own ON public.feedback FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY feedback_insert_own ON public.feedback FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY issue_reports_select_own ON public.issue_reports FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY issue_reports_insert_own ON public.issue_reports FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_achievements_select_own ON public.user_achievements FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_achievements_update_own ON public.user_achievements FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_cosmetics_select_own ON public.user_cosmetics FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY user_roles_select_own ON public.user_roles FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY xp_events_select_own ON public.xp_events FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY friend_requests_select_party ON public.friend_requests FOR SELECT TO authenticated
    USING (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()));
CREATE POLICY friend_requests_insert_sender ON public.friend_requests FOR INSERT TO authenticated
    WITH CHECK (from_user_id = (SELECT app_auth.uid()));
CREATE POLICY friend_requests_update_party ON public.friend_requests FOR UPDATE TO authenticated
    USING (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()))
    WITH CHECK (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()));
CREATE POLICY friend_requests_delete_party ON public.friend_requests FOR DELETE TO authenticated
    USING (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()));
CREATE POLICY friendships_select_party ON public.friendships FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR friend_id = (SELECT app_auth.uid()));
CREATE POLICY friendships_insert_party ON public.friendships FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) OR friend_id = (SELECT app_auth.uid()));
CREATE POLICY friendships_delete_party ON public.friendships FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR friend_id = (SELECT app_auth.uid()));
CREATE POLICY messages_select_own ON public.messages FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY messages_insert_own ON public.messages FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY messages_update_own ON public.messages FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())))
    WITH CHECK (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY messages_delete_own ON public.messages FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY node_mastery_events_select_own ON public.node_mastery_events FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = node_mastery_events.node_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY node_mastery_events_insert_own ON public.node_mastery_events FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = node_mastery_events.node_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY note_concepts_select_own ON public.note_concepts FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.notes p WHERE p.id = note_concepts.note_id AND p.user_id = (SELECT app_auth.uid())) AND EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = note_concepts.concept_node_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY note_concepts_insert_own ON public.note_concepts FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.notes p WHERE p.id = note_concepts.note_id AND p.user_id = (SELECT app_auth.uid())) AND EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = note_concepts.concept_node_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY note_concepts_delete_own ON public.note_concepts FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.notes p WHERE p.id = note_concepts.note_id AND p.user_id = (SELECT app_auth.uid())) AND EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = note_concepts.concept_node_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY quiz_responses_select_own ON public.quiz_responses FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY quiz_responses_insert_own ON public.quiz_responses FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY quiz_responses_update_own ON public.quiz_responses FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())))
    WITH CHECK (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY quiz_responses_delete_own ON public.quiz_responses FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
CREATE POLICY gradebook_categories_select_own ON public.gradebook_categories FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
CREATE POLICY gradebook_categories_insert_own ON public.gradebook_categories FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
CREATE POLICY gradebook_categories_update_own ON public.gradebook_categories FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
CREATE POLICY gradebook_categories_delete_own ON public.gradebook_categories FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
CREATE POLICY assignments_select_own ON public.assignments FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
CREATE POLICY assignments_insert_own ON public.assignments FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
CREATE POLICY assignments_update_own ON public.assignments FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
CREATE POLICY assignments_delete_own ON public.assignments FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
CREATE POLICY gradescope_course_links_select_own ON public.gradescope_course_links FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
CREATE POLICY gradescope_course_links_insert_own ON public.gradescope_course_links FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
CREATE POLICY gradescope_course_links_update_own ON public.gradescope_course_links FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
CREATE POLICY gradescope_course_links_delete_own ON public.gradescope_course_links FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
CREATE POLICY topic_checklists_select_own ON public.topic_checklists FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
CREATE POLICY topic_checklists_insert_own ON public.topic_checklists FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
CREATE POLICY topic_checklists_update_own ON public.topic_checklists FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
CREATE POLICY topic_checklists_delete_own ON public.topic_checklists FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
CREATE POLICY topic_checklist_progress_select_own ON public.topic_checklist_progress FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
CREATE POLICY topic_checklist_progress_insert_own ON public.topic_checklist_progress FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
CREATE POLICY topic_checklist_progress_update_own ON public.topic_checklist_progress FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
CREATE POLICY topic_checklist_progress_delete_own ON public.topic_checklist_progress FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
CREATE POLICY rooms_select_visible ON public.rooms FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL AND (is_public OR (SELECT app_auth.is_room_member(rooms.id))));
CREATE POLICY rooms_insert_owner ON public.rooms FOR INSERT TO authenticated
    WITH CHECK (owner_id = (SELECT app_auth.uid()) AND created_by = (SELECT app_auth.uid()));
CREATE POLICY rooms_update_owner ON public.rooms FOR UPDATE TO authenticated
    USING (owner_id = (SELECT app_auth.uid()))
    WITH CHECK (owner_id = (SELECT app_auth.uid()));
CREATE POLICY room_members_select_comember ON public.room_members FOR SELECT TO authenticated
    USING ((SELECT app_auth.is_room_member(room_members.room_id)));
CREATE POLICY room_members_insert_self ON public.room_members FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) AND NOT EXISTS (SELECT 1 FROM public.room_bans b WHERE b.room_id = room_members.room_id AND b.user_id = (SELECT app_auth.uid())) AND ((SELECT app_auth.owns_room(room_members.room_id)) OR EXISTS (SELECT 1 FROM public.rooms r WHERE r.id = room_members.room_id AND r.is_public)));
CREATE POLICY room_members_delete_self_or_owner ON public.room_members FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR (SELECT app_auth.owns_room(room_members.room_id)));
CREATE POLICY room_bans_select_owner_or_self ON public.room_bans FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR (SELECT app_auth.owns_room(room_bans.room_id)));
CREATE POLICY room_bans_write_owner ON public.room_bans FOR INSERT TO authenticated
    WITH CHECK (banned_by = (SELECT app_auth.uid()) AND (SELECT app_auth.owns_room(room_bans.room_id)));
CREATE POLICY room_bans_update_owner ON public.room_bans FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_room(room_bans.room_id)))
    WITH CHECK (banned_by = (SELECT app_auth.uid()) AND (SELECT app_auth.owns_room(room_bans.room_id)));
CREATE POLICY room_bans_delete_owner ON public.room_bans FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_room(room_bans.room_id)));
CREATE POLICY room_activity_select_member ON public.room_activity FOR SELECT TO authenticated
    USING ((SELECT app_auth.is_room_member(room_activity.room_id)));
CREATE POLICY room_activity_insert_member ON public.room_activity FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) AND (SELECT app_auth.is_room_member(room_activity.room_id)));
CREATE POLICY room_summaries_select_member ON public.room_summaries FOR SELECT TO authenticated
    USING ((SELECT app_auth.is_room_member(room_summaries.room_id)));
CREATE POLICY room_reactions_select_member ON public.room_reactions FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.room_messages m WHERE m.id = room_reactions.message_id AND (SELECT app_auth.is_room_member(m.room_id))));
CREATE POLICY room_reactions_insert_self ON public.room_reactions FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) AND EXISTS (SELECT 1 FROM public.room_messages m WHERE m.id = room_reactions.message_id AND (SELECT app_auth.is_room_member(m.room_id))));
CREATE POLICY room_reactions_delete_self ON public.room_reactions FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY offering_concept_stats_select_enrolled ON public.offering_concept_stats FOR SELECT TO authenticated
    USING ((SELECT app_auth.enrolled_in_offering(offering_concept_stats.offering_id)));
CREATE POLICY offering_summary_select_enrolled ON public.offering_summary FOR SELECT TO authenticated
    USING ((SELECT app_auth.enrolled_in_offering(offering_summary.offering_id)));
CREATE POLICY course_chunks_select_readable ON public.course_chunks FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL AND (visibility = 'shared' OR uploader_id = (SELECT app_auth.uid()) OR EXISTS (SELECT 1 FROM public.course_chunk_contributors k WHERE k.chunk_id = course_chunks.id AND k.user_id = (SELECT app_auth.uid()))));
CREATE POLICY course_chunk_contributors_select_own ON public.course_chunk_contributors FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
CREATE POLICY course_chunk_sources_select_readable ON public.course_chunk_sources FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.course_chunks c WHERE c.id = course_chunk_sources.chunk_id));
CREATE POLICY schools_select_signed_in ON public.schools FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY terms_select_signed_in ON public.terms FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY courses_select_signed_in ON public.courses FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY course_offerings_select_signed_in ON public.course_offerings FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY achievements_select_signed_in ON public.achievements FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY achievement_triggers_select_signed_in ON public.achievement_triggers FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY achievement_cosmetics_select_signed_in ON public.achievement_cosmetics FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY cosmetics_select_signed_in ON public.cosmetics FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY roles_select_signed_in ON public.roles FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY role_cosmetics_select_signed_in ON public.role_cosmetics FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY growth_stages_select_signed_in ON public.growth_stages FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
CREATE POLICY xp_rules_select_signed_in ON public.xp_rules FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);

-- ===== <ts>_rls_grant_authenticated.sql (draft, generated) =====
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN RETURN; END IF;
  EXECUTE $q$GRANT SELECT ON public.users TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE ON public.user_profiles TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE ON public.user_settings TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.oauth_tokens TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.gradescope_credentials TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.enrollments TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.notes TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.flashcards TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.sessions TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.quiz_attempts TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.quiz_context TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.study_guides TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.graph_nodes TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.graph_edges TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, DELETE ON public.documents TO authenticated$q$;
  EXECUTE $q$GRANT UPDATE (file_name, category, summary, concept_notes, flashcards, processed_at, deleted_at, extracted_text, shareability, shareability_confidence, offering_id) ON public.documents TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT ON public.feedback TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT ON public.issue_reports TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.user_achievements TO authenticated$q$;
  EXECUTE $q$GRANT UPDATE (is_featured) ON public.user_achievements TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.user_cosmetics TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.user_roles TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.xp_events TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.friend_requests TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, DELETE ON public.friendships TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.messages TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT ON public.node_mastery_events TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, DELETE ON public.note_concepts TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.quiz_responses TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.gradebook_categories TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.assignments TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.gradescope_course_links TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.topic_checklists TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.topic_checklist_progress TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE ON public.rooms TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, DELETE ON public.room_members TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, UPDATE, DELETE ON public.room_bans TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT ON public.room_activity TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.room_summaries TO authenticated$q$;
  EXECUTE $q$GRANT SELECT, INSERT, DELETE ON public.room_reactions TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.offering_concept_stats TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.offering_summary TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.course_chunks TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.course_chunk_contributors TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.course_chunk_sources TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.schools TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.terms TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.courses TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.course_offerings TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.achievements TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.achievement_triggers TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.achievement_cosmetics TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.cosmetics TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.roles TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.role_cosmetics TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.growth_stages TO authenticated$q$;
  EXECUTE $q$GRANT SELECT ON public.xp_rules TO authenticated$q$;
  EXECUTE $q$GRANT EXECUTE ON FUNCTION public.match_course_chunks(vector, integer, text, text) TO authenticated$q$;
  EXECUTE $q$GRANT EXECUTE ON FUNCTION public.apply_mastery_delta(text, text, double precision, double precision, double precision, double precision) TO authenticated$q$;
END $$;
```

## Addendum: dashboard findings (2026-11-08, read-only check, Trov handoff #20)

These answer open questions 1, 2 and 6 and add two findings. Full answers are on Trov #115.

| Question | Staging | Prod |
| --- | --- | --- |
| JWT signing | Migrated to signing keys. Current key is Supabase-managed ES256 (P-256), so we cannot sign with it. The legacy HS256 secret is listed as a previous key and still verifies. | Same |
| Auth signups | "Allow new users to sign up" ON, Email provider only, anonymous sign-ins off, no third-party providers. No Auth users. | Same settings. One Auth user (an Email signup from early setup). |
| Backups / PITR | None (Free plan) | None (Free plan) |
| Security Advisor | 1 error (`room_messages`) | 37 errors (35 RLS disabled + 2 sensitive columns exposed) until #807 is promoted |

Prod `room_messages`: RLS on with zero policies (so live room chat delivers nothing today). `anon` still holds TRUNCATE, REFERENCES and TRIGGER and `authenticated` holds full privileges, because the June lockdown revoked only SELECT/INSERT/UPDATE/DELETE. Step 2a revokes these.

Roles: only `service_role` has BYPASSRLS. `authenticator` can switch to `anon`, `authenticated` and `service_role`.

Consequences for this plan:

- **Step 2d (key import) is confirmed:** import our own ES256 private key and make it current. Open: whether PostgREST accepts tokens from a key that is only in standby. Test on staging before rotating.
- **Turn Auth signups off** on both projects and delete the stray prod Auth user. `app_auth.uid()` already ignores Supabase Auth tokens, but there is no reason to leave signups on.
- **No backups is a blocker for any prod migration.** Take a manual `pg_dump` of prod before every `make promote` until the project has backups.
- **Exposure window can't be audited.** The Free plan keeps 24 hours of API logs. Direct anon-key requests go to Supabase, not through the backend or Cloudflare, so no other log can answer whether tables were read while RLS was off.
