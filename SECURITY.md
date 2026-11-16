# Sapling Security

This document describes the security controls currently implemented in Sapling. It is sourced directly from the code; every claim cites the file (and where useful, the line) that implements it.

> **Verification date.** §4 (Secrets and Configuration), §7 (Logging), §8 (Dependency Surface) and the Related documents section were re-checked against the code on **2026-11-14**. Other sections carry their original sourcing and may lag the code; where they disagree, the code wins.

## Reporting a vulnerability

Do not open a public issue for a security problem. Message a maintainer directly (see "Team" in the [README](README.md)) with the affected route or file, steps to reproduce, and the impact. We acknowledge reports within a few days and credit reporters in the fix PR unless asked not to.

The codebase is split into a FastAPI backend (`backend/`) and a Next.js frontend (`frontend/`) deployed to Cloudflare Workers. The threat model assumes a hostile public internet, untrusted user-uploaded content, and the need to keep student PII unreadable to anyone who lifts the database.

---

## 1. Authentication

### 1.1 Google OAuth 2.0 with PKCE

**Files:** `backend/routes/auth.py`, `frontend/src/components/marketing/SignInModal.tsx`, `frontend/src/app/auth/callback/page.tsx`, `frontend/src/app/api/auth/session/route.ts`

Sign-in is a full-page redirect to `${API_URL}/api/auth/google`. The backend drives the OAuth flow and the frontend never touches Google directly.

- **PKCE (S256).** Each sign-in mints a fresh 32-byte code verifier via `secrets.token_bytes(32)`. The SHA-256 challenge is sent to Google with `code_challenge_method=S256` (`auth.py` ~lines 68–73, 144–152). The verifier is carried in the OAuth `state` parameter, base64-encoded JSON: `{"action": "signin", "cv": "<verifier>"}`.
- **Code exchange.** On callback, the backend decodes `state`, extracts the code verifier, and exchanges the code via `flow.fetch_token(code=code, code_verifier=code_verifier)`. The redirect URI is pinned to `GOOGLE_AUTH_REDIRECT_URI` (env-supplied) and validated by Google.
- **No domain restriction; the waitlist is the gate.** Any Google account with a verified email (`verified_email: true`) may attempt sign-in. A new address gets an account only when it is approved on the waitlist (Admin → Allowlist) or while the `open_access` flag is on; otherwise nothing is stored and the visitor lands on `/pending`. A non-`bu.edu` address is only a "Non-BU" label in Admin → Allowlist, never a refusal (`services/auth/signin.py`, `services/open_access.py`, `docs/design/open-access-gate.md`). `SAPLING_FLAG_OPEN_ACCESS=off` forces the gate closed.
- **OAuth tokens at rest.** Google access and refresh tokens are encrypted with AES-256-GCM **before** insertion into `oauth_tokens` (`auth.py` ~lines 228–229). They are never read back in plaintext from any current code path.

### 1.2 HMAC Session Tokens

**Files:** `backend/services/auth_guard.py`, `frontend/src/lib/sessionToken.ts`, `frontend/src/app/api/auth/session/route.ts`

Sapling does not use JWTs. Sessions are minimal HMAC-signed payloads of the form:

```
base64url(payload).base64url(signature)
```

- **Payload:** `{"user_id": "<id>", "exp": <unix_timestamp>, "typ": "session", "iat": <unix_timestamp>}`. The key name is `user_id` (snake_case) on both ends — alignment was a recent fix (commit `02b0242`).
- **Algorithm:** HMAC-SHA256 over the base64 payload using `SESSION_SECRET` (≥32 bytes, validated at runtime in `sessionToken.ts:6`).
- **Frontend signs** with `crypto.subtle.importKey` + `crypto.subtle.sign('HMAC', …)`.
- **Backend verifies** with `hmac.compare_digest()` for timing-safe comparison (`auth_guard.py:35`).
- **Expiry:** 7 days from issue (`SESSION_MAX_AGE = 604800` in `sessionToken.ts`, `config.SESSION_MAX_AGE_SECONDS` on the backend); both ends refuse a session whose `iat` is older, whatever its `exp` says. A token minted before `iat` existed is dated `exp - 30 days`.
- **Lookup:** Backend reads the token from the `sapling_session` cookie only. The `?auth_token=` query parameter is not a credential (tokens in URLs reach access logs, Referer headers and browser history); the OAuth handoff token travels in the frontend callback URL and reaches the session BFF in a JSON body.
- **Revocation:** `users.sessions_valid_after`; a session issued before it is refused (`auth_guard.get_session_user_id`, through its 30 s account cache).

### 1.3 Cookie Hardening

**Files:** `frontend/src/app/api/auth/session/route.ts`, `frontend/wrangler.toml`

The session cookie is set exclusively by the Next.js route handler — never by the backend in any deployed environment — using these flags:

| Flag        | Value                | Purpose                                             |
|-------------|----------------------|-----------------------------------------------------|
| `httpOnly`  | `true`               | Inaccessible to JavaScript; mitigates XSS exfil     |
| `secure`    | `true`               | HTTPS-only (production builds, and any https request) |
| `sameSite`  | `lax`                | Implicit CSRF defense for state-changing requests   |
| `path`      | `/`                  | Whole site                                          |
| `domain`    | `.saplinglearn.com`  | Shared across all subdomains (api, app, www)        |
| `maxAge`    | 7 days               | Set to `0` on sign-out for immediate deletion       |

`COOKIE_DOMAIN=.saplinglearn.com` is shipped via `wrangler.toml [vars]` (commit `b1377ec`); the leading dot is what permits `api.saplinglearn.com` and the app origin to share the same session.

**One test-only exception (#381).** `POST /api/auth/test-login` (`backend/routes/auth.py`) sets `sapling_session` directly, with the same flags, so the pytest integration suite and Playwright's global setup can obtain a session without driving real Google OAuth (which is not headless-automatable). It is hard-gated on `APP_ENV in {"local", "test"}` — evaluated per request, not captured at import — and returns a stock `404 {"detail": "Not Found"}` in every other environment, so it does not advertise its existence; it is also `include_in_schema=False`, so it never appears in `/openapi.json`. The allowlist is deliberately narrower than `config.IS_LOCAL` (`{local, development, dev, test}`). See `backend/tests/test_auth_test_login.py`.

### 1.4 Sign-out

`UserContext.signOut()` issues `DELETE /api/auth/session`. The BFF first calls the backend's `POST /api/auth/logout` with the cookie, which sets `users.sessions_valid_after = now()` and so revokes every session the account was issued until then (sign-out is everywhere); it then writes a `Max-Age=0` cookie under the same domain/Secure/SameSite settings, and the client clears in-memory and storage state. Other backend processes honour the revocation within the guard's 30 s account cache.

### 1.5 Boot refusals

`config.validate_config()` refuses to start a process whose `APP_ENV` is local/test/dev/development but which looks deployed (an https `FRONTEND_URL` or `GOOGLE_AUTH_REDIRECT_URI` off localhost, `SECURE_COOKIES=true`, or a hosting platform's env), and, outside local, refuses the `SESSION_SECRET` / `ENCRYPTION_KEY` values committed to the repository. FastAPI's `/docs`, `/redoc` and `/openapi.json` are served only when `APP_ENV` is local or test.

---

## 2. Authorization

### 2.1 Auth Guards

**File:** `backend/services/auth_guard.py`

Three building blocks gate every authenticated route:

- **`get_session_user_id(request)`** — verifies the HMAC token and returns the `user_id`; raises `401` on missing/invalid/expired tokens.
- **`require_self(user_id, request)`** — confirms the session user matches the target resource owner; raises `403 "Forbidden: not your account"` otherwise.
- **`require_admin(request)`** — joins `user_roles` to `roles` and checks for the `admin` slug; raises `403 "Admin access required"` otherwise. Step-up: the session must also have been issued within `ADMIN_REAUTH_WINDOW_SECONDS` (12 h), else `401` with `detail.code = "reauth_required"` and the admin console asks for a fresh Google sign-in. **`require_admin_recent(request)`** applies the stricter `ADMIN_DESTRUCTIVE_REAUTH_WINDOW_SECONDS` (30 min) to account wipe/seed/copy, role assign/revoke, email broadcasts and feature-flag changes.
- **`require_role(role_slug)`** — generic factory that returns a checker for any role.

Errors are surfaced as standard FastAPI `HTTPException` with deterministic status codes (`401` unauthenticated, `403` authorized-but-forbidden).

### 2.2 Roles Schema

**File:** `backend/db/migration_roles.sql`

```
roles(id, slug UNIQUE, name, color, icon, description,
      is_staff_assigned, is_earnable, display_priority)
user_roles(user_id, role_id, granted_at, granted_by)
```

Seeded slugs: `admin`, `moderator`, `verified`, `vip`, `early-adopter`. `user_roles` is indexed on `user_id` for fast guard lookups.

### 2.3 Admin Surface

**File:** `backend/routes/admin.py`

Every admin route declares `require_admin(request)` as a dependency. Coverage today:

- **Roles:** list / create / update / delete; assign / revoke per user.
- **Achievements:** list / create / update / delete; manual grant; trigger creation.
- **Cosmetics:** list / create / update / delete (avatar frames, banners, name colors, titles).
- **Users:** list (with decrypted names/emails for review); `PATCH /users/{user_id}/approve`.

### 2.4 Approval Gate

**Files:** `backend/db/migration_add_is_approved.sql`, `backend/routes/auth.py`, `frontend/src/middleware.ts`

New users are created with `users.is_approved = false`. The gate is enforced in two places:

1. **Backend OAuth callback.** If `is_approved` is false the user is redirected to `${FRONTEND_URL}/pending` instead of receiving a session token (`auth.py` ~lines 235–236).
2. **Frontend middleware.** Even if a token is present, `middleware.ts` calls `/api/auth/me` for every protected route and redirects to `/pending` when `data.is_approved !== true` (`middleware.ts:58`).

Promotion happens via `PATCH /api/admin/users/{user_id}/approve`, which only admins can call.

### 2.5 Cross-Tenant Isolation

User-owned resources are gated either by `require_self()` or by explicit `user_id` filters on every Supabase query. Sampled enforcement:

- **`routes/documents.py`** — `require_self()` on read/upload; deletes filter `id eq <id> AND user_id eq <user>`.
- **`routes/flashcards.py`** — `require_self()` on list/import/commit; deletes scoped on `user_id`.
- **`routes/gradebook.py`** — `_user_owns_course()`, `_user_owns_category()`, `_user_owns_assignment()` helpers gate every write.
- **`routes/calendar.py`** — `require_self(user_id, request)` on every endpoint.
- **`routes/social.py`** — room membership is verified via `room_id eq <id> AND user_id eq <viewer>` before exposing chat or member graphs.

### 2.6 Frontend Route Guard

**File:** `frontend/src/middleware.ts`

A Next.js middleware enforces auth + approval before any of the 12 protected paths render:

```
/dashboard, /learn, /study, /tree, /library, /calendar,
/social, /settings, /achievements, /admin,
/gradebook, /course-planner
```

For each request it (1) reads `sapling_session`, (2) verifies the HMAC locally via `verifySession`, (3) calls the backend `/api/auth/me` with a 3-second `AbortController` timeout, and (4) checks `is_approved`. Any failure redirects to Google sign-in or `/pending`. `NEXT_PUBLIC_LOCAL_MODE=true` bypasses the middleware for local development only.

---

## 3. Encryption at Rest

### 3.1 Primitive

**File:** `backend/services/encryption.py`

- **Cipher:** AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
- **Key:** 32 bytes loaded from `ENCRYPTION_KEY` at module import time. Validated as exactly 64 hex characters; any other shape raises `RuntimeError` and prevents the app from booting (`_load_key`, lines 43–60).
- **Nonce:** 12 random bytes from `os.urandom()` per call. Never reused (verified in `tests/test_encryption.py`).
- **Wire format:** `base64(nonce || ciphertext_with_tag)`. The 16-byte GCM authentication tag is included in the ciphertext blob, so any bit-flip is detected on decrypt.

### 3.2 Helpers

| Helper                 | Purpose                                                                            |
|------------------------|------------------------------------------------------------------------------------|
| `encrypt(value)`       | Encrypts a string; mints a fresh nonce.                                            |
| `decrypt(value)`       | Decrypts; raises on tamper / wrong key.                                            |
| `encrypt_if_present`   | Returns `None` for `None`; otherwise stringifies and encrypts.                     |
| `decrypt_if_present`   | Tries to decrypt; **falls back to the raw value with a warning** if it cannot.     |
| `decrypt_numeric`      | Decrypts then casts to `float`; passes through native numerics.                    |
| `encrypt_json`         | Compact-serializes JSON, then encrypts.                                            |
| `decrypt_json`         | Decrypts then `json.loads`; falls back to parsing raw input.                       |

The `*_if_present` fallback is what lets a partially-backfilled table keep serving traffic: encrypted rows return plaintext, legacy plaintext rows return themselves, and an operator log warning surfaces every legacy read.

### 3.3 Encrypted Columns

Verified by grepping for `encrypt_if_present` / `decrypt_if_present` / `encrypt_json` / `decrypt_json` in `backend/routes/`:

| Table             | Column(s)                                                  | Notes                                  |
|-------------------|------------------------------------------------------------|----------------------------------------|
| `users`           | `name`, `first_name`, `last_name`, `email`, `bio`, `location` | Decrypted at every read boundary.    |
| `user_settings`   | `bio`, `location`                                          | Profile-edit duplicates.               |
| `oauth_tokens`    | `access_token`, `refresh_token`                            | Encrypted on insert; never read today. |
| `documents`       | `summary`, `concept_notes`                                 | `concept_notes` was retyped JSONB→TEXT.|
| `messages`        | `content`                                                  | Tutoring chat history.                 |
| `room_messages`   | `text`                                                     | Study-room chat.                       |
| `sessions`        | `summary_json`                                             | Retyped JSONB→TEXT; write-only today.  |
| `assignments`     | `notes`, `points_possible`, `points_earned`                | Numeric columns retyped to TEXT.       |
| `calendar_*`      | assignment `notes`                                         | Encrypted on every sync.               |

### 3.4 Migration & Backfill

- **`backend/db/migration_encryption_text_columns.sql`** retypes columns whose original types couldn't hold base64 (`NUMERIC` and `JSONB` → `TEXT`), preserving existing values via `USING column::TEXT`.
- **`backend/db/backfill_encryption.py`** is idempotent: for each candidate row it tries to decrypt; if that fails, it encrypts and writes (only when `--apply` is passed). It supports `--table` for narrow runs and prints per-column counts on completion.

### 3.5 AI Prompt Boundary

All Gemini callers decrypt before constructing a prompt. None of `decrypt_if_present` / `decrypt_json`'s outputs leave the process before being assembled into a system or user message:

- **`routes/learn.py`** — student name (`get_user_name`), document summaries, and concept notes decrypted before `_make_system_prompt()` (`learn.py` ~lines 130, 133, 243, 286).
- **`routes/quiz.py`** — student name decrypted before `quiz_context_update` and `quiz_generation` prompts (`quiz.py` ~lines 192, 198).
- **`routes/study_guide.py`** — document summary and concept notes decrypted before the study-guide agent's context block is assembled (`study_guide.py` ~lines 43, 49, 54).
- **`routes/flashcards.py`** — same decrypt pattern before flashcard extraction (~lines 130, 133, 424, 428).
- **`routes/documents.py`** — concept extension and graph updates decrypt summaries first (~lines 237, 240, 454, 458).

### 3.6 Tests

`backend/tests/test_encryption.py` covers: round-trip ASCII / Unicode / 5000-char strings / empty strings, JSON helpers, numeric helpers, the `*_if_present` fallback path (including a warning assertion for legacy plaintext), nonce randomness on repeated encryption of the same plaintext, and tamper detection (a flipped bit on the auth tag must raise).

---

## 4. Secrets and Configuration

**Files:** `backend/config.py`, `backend/.env.example`, `backend/services/encryption.py`, `backend/db/user_jwt.py`, `backend/services/typesafe_client.py`, `backend/main.py`, `frontend/wrangler.toml`, `frontend/.env.example`

*Verified against the code on 2026-11-14.* `.env`, `.env.local`, and other secret files are gitignored. Backend secrets are Railway service variables (the `worker` service references them from the API service, `.railway/railway.ts`); frontend secrets are Cloudflare Worker secrets or Workers Builds build variables. Where each one is set, its blast radius and how to rotate it: [`docs/security/incident-response.md` §4](docs/security/incident-response.md#4-key-and-secret-rotation).

**Secrets** (names exactly as the code reads them):

| Variable                          | Surface  | Purpose                                                          |
|-----------------------------------|----------|------------------------------------------------------------------|
| `SUPABASE_SERVICE_KEY`            | backend  | RLS-bypass service role key for PostgREST and Storage. Never exposed to the browser. Required at startup. |
| `SUPABASE_JWT_SIGNING_KEY`        | backend  | One JWK that signs backend-minted student JWTs (`db_user_scope`) and the browser Realtime token (`db/user_jwt.py`). Optional; unset, those paths answer 503 / fail closed. |
| `SUPABASE_ANON_KEY`               | backend  | The project's anon/publishable key, sent as `apikey` on user-scoped requests. Public by design. |
| `SUPABASE_DB_URL`                 | backend (ops) | Postgres URI (password inside) for the migration runner and `make backup-db`; unused by the app runtime. |
| `STAGING_SUPABASE_DB_URL`         | ops / CI | Staging's Postgres URI, read by the promotion runner (also a GitHub Actions secret). |
| `DBOS_DATABASE_URL`               | backend  | Postgres URI for the optional DBOS durable-workflow shim (`services/durable.py`); only when DBOS is enabled. |
| `ENCRYPTION_KEY`                  | backend  | 64-hex-char (32-byte) AES-256-GCM key for column encryption. Required. |
| `SESSION_SECRET`                  | both     | HMAC-SHA256 secret (≥32 bytes) for session tokens, OAuth state, `/pending` tokens and email recipient hashes / unsubscribe tokens. Backend and frontend values must be equal. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | backend | Google OAuth client (sign-in and Calendar). |
| `ANTHROPIC_API_KEY`               | backend  | Claude, the provider for every agent (ADR 0030). Required at startup. |
| `GEMINI_API_KEY`                  | backend  | Gemini embeddings for RAG, and any slot pointed at a `gemini-*` model. Required at startup. |
| `RESEND_API_KEY`                  | backend  | Resend email sending; unset = nothing is sent (sends recorded `skipped`). |
| `POSTHOG_PROJECT_TOKEN`           | backend  | PostHog ingestion key (public by PostHog's design); unset = no PostHog client. |
| `POSTHOG_PERSONAL_API_KEY` (+ `POSTHOG_PROJECT_ID`) | backend | PostHog personal key with `person:write`, used only to erase a deleted account's PostHog person. |
| `LOGFIRE_TOKEN`                   | backend  | Logfire write token; unset = no trace egress. |
| `CANOPY_METRICS_TOKEN`            | backend  | Bearer token for `GET /api/internal/metrics` (Canopy dashboard); unset = route 404s. |
| `ACCOUNT_SYNC_PEER_TOKEN` / `ACCOUNT_SYNC_INBOUND_TOKEN` | backend | Cross-environment admin account copy: the token sent to the peer / the token accepted from it. The inbound token grants read and overwrite of any account's study data; unset = routes 404. |
| `TYPESAFE_API_KEY`                | backend  | TypeSafe Jev decision model (`services/typesafe_client.py`), used only when the `decision_router` flag is on. |
| `RECOST_API_KEY`                  | backend  | Optional Recost API-cost telemetry middleware (`main.py`). |
| `REDIS_URL`                       | backend  | Optional cross-worker OCR/extraction cache; may embed a password. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`   | frontend | Browser-safe key used only for Realtime room subscriptions. |
| `NEXT_PUBLIC_POSTHOG_KEY`         | frontend | PostHog project key (public), inlined at build time; unset = analytics off. |

**Non-secret configuration** that still matters for security:

| Variable                          | Surface  | Purpose                                                          |
|-----------------------------------|----------|------------------------------------------------------------------|
| `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL` | backend / frontend | Project base URL. |
| `APP_ENV`                         | backend  | Defaults to `production` (strict). `local`/`development`/`dev`/`test` relax the `SESSION_SECRET` check; `/api/auth/test-login` exists only under `local`/`test`. |
| `GOOGLE_AUTH_REDIRECT_URI` / `GOOGLE_REDIRECT_URI` | backend | Pinned OAuth callback URLs (sign-in / Calendar). |
| `FRONTEND_URL`                    | backend  | The CORS origin and OAuth redirect target. |
| `COOKIE_DOMAIN`, `DEPLOY_ENV`     | frontend | `.saplinglearn.com` (prod) for cross-subdomain session cookies; `DEPLOY_ENV` derives the backend origin and cookie domain. |
| `SAPLING_FLAG_<KEY>`              | backend  | Per-process feature-flag override that beats every stored rule; the incident kill switch. |
| `OCR_ENGINE`, `GOT_OCR_ENABLED`   | backend  | OCR backend selection. |

`ENCRYPTION_KEY` is validated when `services/encryption.py` is imported (missing, non-hex or wrong-length values raise). `validate_config()` runs at the start of the API lifespan and of `python -m worker`, before any request is served, and and refuses to boot without `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and, outside local `APP_ENV`s, a `SESSION_SECRET` of at least 32 bytes. The encryption-key canary (`services/encryption_canary.py`) then refuses to boot with a key that cannot open the database's `encryption_key_check` row.

### Supabase key split

- **Backend (`backend/db/connection.py`, `backend/services/storage_service.py`)** uses the **service role key**, which bypasses RLS. All persistent writes flow through the backend.
- **Frontend (`frontend/src/lib/supabase.ts`)** uses the **anon key** and only for Supabase Realtime subscriptions in `Social.tsx`:
  - `room:${roomId}` channel — `postgres_changes` on `room_messages` / `room_reactions`, filtered by `room_id`.
  - `presence:${roomId}` channel — typing presence.
- Room writes still flow through the backend (which checks membership before insert), so the anon key alone cannot post into a room a user has not joined.

---

## 5. Transport, CORS, and Deployment

- **TLS.** The frontend runs on Cloudflare Workers via `@opennextjs/cloudflare` (`wrangler.toml`); TLS is terminated at the edge for `*.saplinglearn.com` and `api.saplinglearn.com`.
- **CORS** (`backend/main.py`):
  ```python
  CORSMiddleware(
      allow_origins=[FRONTEND_URL, "http://localhost:3000"],
      allow_credentials=True,
      allow_methods=["*"], allow_headers=["*"],
  )
  ```
  Only the configured frontend origin and localhost for development are permitted. `allow_credentials=True` is required because the session cookie is sent cross-origin from the app to the API.
- **No wildcard origins.** Production never sets `*` because credentials would be refused by the browser anyway.

---

## 6. File Uploads and OCR

### 6.1 Documents (`backend/routes/documents.py`)

- **Allowed types:** `.pdf`, `.docx`, `.pptx`. Both extension and MIME type are validated.
- **Max size:** 15 MB.
- **No raw file persistence.** Files are extracted in-memory; only the metadata (name, category) and AI-generated summary/concept_notes (encrypted) are written to Supabase.
- **Prompt sizing.** Extracted text is truncated to 12,000 characters before being passed to Gemini.

### 6.2 Avatars and Cosmetics (`backend/services/storage_service.py`)

- **Allowed MIME types:** `image/jpeg`, `image/png`, `image/webp`, `image/gif`.
- **Max size:** 5 MB.
- **Storage:** Supabase Storage bucket `avatars` with paths `avatars/{user_id}/avatar.{ext}` and `cosmetics/{cosmetic_id}.{ext}`. Uploads use the service key with `x-upsert: true`; reads are public via signed-bucket URL.

### 6.3 OCR Backends (`backend/services/extraction_backends/`)

A thin router (`extraction_service.py`) selects a backend by `OCR_ENGINE`:

- **`docling`** (default) — layout-aware markdown extraction.
- **`auto`** — Docling, with GOT-OCR 2.0 fallback for low-density / math pages, only when `GOT_OCR_ENABLED=true`. GOT-OCR loads a Hugging Face model with `trust_remote_code=True`, so it stays disabled in production by default and the model path should be pinned to a known revision when enabled.
- **`tesseract`** — legacy fallback.

All backends are lazy-imported to keep cold start sub-second. Failures degrade Docling → GOT-OCR → Tesseract before raising `RuntimeError`, which `routes/extract.py` surfaces as `503`.

---

## 7. Logging

*Verified against the code on 2026-11-14.*

`RequestIDMiddleware` (`backend/services/request_context.py`, installed in `backend/main.py`) emits one line per request with the request id, method, URL **path** (never the full URL, so no query string), status and duration. It does **not** log request or response bodies, emails, names, tokens, or any decrypted column. Errors include the exception class name and traceback only; error responses carry the request id (`X-Request-ID`) for correlation. The uvicorn access log drops query strings too, so a token passed as `?auth_token=` never reaches process logs.

**Logfire** (`LOGFIRE_TOKEN`; unset = no egress) receives FastAPI request traces and Pydantic AI agent spans, scrubbed before they leave the process (`backend/services/logfire_scrubber.py`, wired in `backend/main.py`):

- Agents are instrumented with `include_content=False`, so prompts, model output, system instructions and tool-call arguments/results are not captured at all; any other content attribute the scrubber is routed is replaced whole by `[redacted, type:…, length:…, sha256:…]`: a length and a content fingerprint, never the content.
- URL query strings are stripped from span attributes (a span processor plus the FastAPI request hook).
- Parsed endpoint arguments (request bodies, query/path params) are never recorded on request spans (`_drop_request_arguments` in `main.py`).
- Logfire's default patterns (`password`, `secret`, `api key`, …) still redact matching attributes outright.

The in-house `events` table holds ids, counts and enums only; free text that must be correlatable is stored as a fingerprint (`backend/services/events_service.py`).

Encryption helpers log a structured warning when `decrypt_if_present` falls back to a raw value; that's the operator signal that legacy plaintext is still being read on a column and the backfill should be re-run.

---

## 8. Dependency Surface

*Verified against the repo on 2026-11-14.*

**What pins dependencies today**

- **Backend lock with hashes.** `backend/requirements.lock` is `requirements.txt` compiled by `uv pip compile --generate-hashes` (every package pinned with sha256 hashes). CI installs it with `pip install --require-hashes -r requirements.lock` (`.github/workflows/ci.yml`), so a tampered or substituted wheel fails the install.
- **Image follows the lock.** The Docker image cannot use `--require-hashes` (the OCR stack in `requirements-worker.txt` is outside the lock, and torch comes from the CPU wheel index), so `backend/scripts/lock_constraints.py` turns the lock into a constraints file and `verify`s the installed set against it (`backend/Dockerfile`, #694). Every locked package resolves to its locked version; the OCR stack's own transitive dependencies (numpy, scipy, huggingface-hub, …) still float.
- **Frontend lock.** `frontend/package-lock.json`, installed with `npm ci` in CI on a pinned npm (10.9.x, enforced by `engine-strict` in `frontend/.npmrc`); `npm run check:lockfile` guards the lockfile format.

**What audits them: nothing automated.** There is no `pip-audit`, `npm audit`, OSV scanner, Snyk, Trivy or CodeQL step in `.github/workflows/`, and no `.github/dependabot.yml` or Renovate config (Dependabot is only mentioned in a comment in `pr-hygiene.yml`). Advisories have been handled by hand (CVE upgrades in #808, per `docs/architecture-hardening-plan.md`). Whether GitHub's repository-level Dependabot alerts are enabled is a repo setting, not visible in the code. Gap: add an advisory scan to CI (e.g. `pip-audit -r requirements.lock` and `npm audit --omit=dev`) and a Dependabot config.

Security-relevant packages currently in use:

**Backend (`backend/requirements.txt`, `backend/requirements-worker.txt`)**
- `cryptography>=50.0.2,<51` — AES-GCM primitive.
- `fastapi`, `uvicorn[standard]` — web framework (exact pins in `requirements.txt`).
- `google-auth-oauthlib`, `google-api-python-client` — OAuth flow and Calendar.
- `pydantic-ai-slim[google,anthropic]>=1.107.7,<2`, `anthropic>=0.108.0,<1` — the only LLM seam.
- `logfire[fastapi]` — tracing (scrubbed, see §7).
- `docling>=2.15,<3`, `transformers>=4.46,<5`, `torch>=2.5,<3` — OCR / document extraction, worker image only.

**Frontend (`frontend/package.json`)**
- `@supabase/supabase-js` — Realtime client.
- `react`, `next` — UI + middleware.
- `@opennextjs/cloudflare` — Workers adapter.

---

---

## 9. Summary Matrix

| Domain                | Mechanism                              | File(s)                                                |
|-----------------------|----------------------------------------|--------------------------------------------------------|
| Sign-in               | OAuth 2.0 + PKCE (S256), `@bu.edu`     | `backend/routes/auth.py`                               |
| Session               | HMAC-SHA256, 30-day expiry             | `backend/services/auth_guard.py`, `frontend/src/lib/sessionToken.ts` |
| Cookie                | HttpOnly, Secure, SameSite=Lax, `.saplinglearn.com` | `frontend/src/app/api/auth/session/route.ts`, `frontend/wrangler.toml` |
| Frontend gate         | Next.js middleware → `/api/auth/me`    | `frontend/src/middleware.ts`                           |
| Backend gate          | `require_self` / `require_admin`       | `backend/services/auth_guard.py`                       |
| Approval              | `users.is_approved` + `/pending`       | `backend/routes/auth.py`, `frontend/src/middleware.ts` |
| Encryption at rest    | AES-256-GCM, random nonce, base64      | `backend/services/encryption.py`                       |
| Backfill              | Idempotent re-encrypt walker           | `backend/db/backfill_encryption.py`                    |
| Supabase key split    | Service (backend) vs anon (frontend)   | `backend/db/connection.py`, `frontend/src/lib/supabase.ts` |
| CORS                  | Configured frontend origin + localhost | `backend/main.py`                                      |
| TLS                   | Cloudflare Workers edge termination    | `frontend/wrangler.toml`                               |
| Uploads               | Type + size validation, no raw persist | `backend/routes/documents.py`, `backend/services/storage_service.py` |
| Logging               | No PII / token / body / query-string logging; Logfire spans scrubbed | `backend/services/request_context.py`, `backend/services/logfire_scrubber.py`, `backend/main.py` |

---

## Related documents

*Added 2026-11-14.*

- [`docs/security/incident-response.md`](docs/security/incident-response.md) — incident roles, severity levels, kill switches and shutdown steps, key and secret rotation, breach-notification orientation (not legal advice), evidence preservation.
- [`docs/security/data-inventory.md`](docs/security/data-inventory.md) — what personal data Sapling holds, where, and which columns are encrypted.
