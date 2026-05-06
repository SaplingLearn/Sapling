# Sapling Security

This document describes the security controls currently implemented in Sapling. It is sourced directly from the code; every claim cites the file (and where useful, the line) that implements it.

The codebase is split into a FastAPI backend (`backend/`) and a Next.js frontend (`frontend/`) deployed to Cloudflare Workers. The threat model assumes a hostile public internet, untrusted user-uploaded content, and the need to keep student PII unreadable to anyone who lifts the database.

---

## 1. Authentication

### 1.1 Google OAuth 2.0 with PKCE

**Files:** `backend/routes/auth.py`, `frontend/src/components/SignInModal.tsx`, `frontend/src/app/auth/callback/page.tsx`, `frontend/src/app/api/auth/session/route.ts`

Sign-in is a full-page redirect to `${API_URL}/api/auth/google`. The backend drives the OAuth flow and the frontend never touches Google directly.

- **PKCE (S256).** Each sign-in mints a fresh 32-byte code verifier via `secrets.token_bytes(32)`. The SHA-256 challenge is sent to Google with `code_challenge_method=S256` (`auth.py` ~lines 68–73, 144–152). The verifier is carried in the OAuth `state` parameter, base64-encoded JSON: `{"action": "signin", "cv": "<verifier>"}`.
- **Code exchange.** On callback, the backend decodes `state`, extracts the code verifier, and exchanges the code via `flow.fetch_token(code=code, code_verifier=code_verifier)`. The redirect URI is pinned to `GOOGLE_AUTH_REDIRECT_URI` (env-supplied) and validated by Google.
- **Domain restriction.** Only `@bu.edu` accounts may sign in. Other domains are redirected to `${FRONTEND_URL}/auth?error=invalid_domain` (`auth.py` ~lines 186–189).
- **OAuth tokens at rest.** Google access and refresh tokens are encrypted with AES-256-GCM **before** insertion into `oauth_tokens` (`auth.py` ~lines 228–229). They are never read back in plaintext from any current code path.

### 1.2 HMAC Session Tokens

**Files:** `backend/services/auth_guard.py`, `frontend/src/lib/sessionToken.ts`, `frontend/src/app/api/auth/session/route.ts`

Sapling does not use JWTs. Sessions are minimal HMAC-signed payloads of the form:

```
base64url(payload).base64url(signature)
```

- **Payload:** `{"user_id": "<id>", "exp": <unix_timestamp>}`. The key name is `user_id` (snake_case) on both ends — alignment was a recent fix (commit `02b0242`).
- **Algorithm:** HMAC-SHA256 over the base64 payload using `SESSION_SECRET` (≥32 bytes, validated at runtime in `sessionToken.ts:6`).
- **Frontend signs** with `crypto.subtle.importKey` + `crypto.subtle.sign('HMAC', …)`.
- **Backend verifies** with `hmac.compare_digest()` for timing-safe comparison (`auth_guard.py:35`).
- **Expiry:** 30 days (`SESSION_MAX_AGE = 2_592_000` in `sessionToken.ts:1`); enforced on both ends (`auth_guard.py:48`, `sessionToken.ts:60`).
- **Lookup:** Backend reads the token from cookie `sapling_session` first, falling back to the `auth_token` query parameter (`auth_guard.py:19`).

### 1.3 Cookie Hardening

**Files:** `frontend/src/app/api/auth/session/route.ts`, `frontend/wrangler.toml`

The session cookie is set exclusively by the Next.js route handler — never by the backend — using these flags:

| Flag        | Value                | Purpose                                             |
|-------------|----------------------|-----------------------------------------------------|
| `httpOnly`  | `true`               | Inaccessible to JavaScript; mitigates XSS exfil     |
| `secure`    | `true`               | HTTPS-only                                          |
| `sameSite`  | `lax`                | Implicit CSRF defense for state-changing requests   |
| `path`      | `/`                  | Whole site                                          |
| `domain`    | `.saplinglearn.com`  | Shared across all subdomains (api, app, www)        |
| `maxAge`    | 30 days              | Set to `0` on sign-out for immediate deletion       |

`COOKIE_DOMAIN=.saplinglearn.com` is shipped via `wrangler.toml [vars]` (commit `b1377ec`); the leading dot is what permits `api.saplinglearn.com` and the app origin to share the same session.

### 1.4 Sign-out

`UserContext.signOut()` issues `DELETE /api/auth/session`, which writes a `Max-Age=0` cookie under the same domain/Secure/SameSite settings, then clears in-memory and storage state. Tokens are stateless, so revocation is by cookie deletion + 30-day expiry; there is no server-side blacklist.

---

## 2. Authorization

### 2.1 Auth Guards

**File:** `backend/services/auth_guard.py`

Three building blocks gate every authenticated route:

- **`get_session_user_id(request)`** — verifies the HMAC token and returns the `user_id`; raises `401` on missing/invalid/expired tokens.
- **`require_self(user_id, request)`** — confirms the session user matches the target resource owner; raises `403 "Forbidden: not your account"` otherwise.
- **`require_admin(request)`** — joins `user_roles` to `roles` and checks for the `admin` slug; raises `403 "Admin access required"` otherwise.
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
- **`routes/study_guide.py`** — document summary and concept notes decrypted before `call_gemini_json` (`study_guide.py` ~lines 43, 49, 54).
- **`routes/flashcards.py`** — same decrypt pattern before flashcard extraction (~lines 130, 133, 424, 428).
- **`routes/documents.py`** — concept extension and graph updates decrypt summaries first (~lines 237, 240, 454, 458).

### 3.6 Tests

`backend/tests/test_encryption.py` covers: round-trip ASCII / Unicode / 5000-char strings / empty strings, JSON helpers, numeric helpers, the `*_if_present` fallback path (including a warning assertion for legacy plaintext), nonce randomness on repeated encryption of the same plaintext, and tamper detection (a flipped bit on the auth tag must raise).

---

## 4. Secrets and Configuration

**Files:** `backend/config.py`, `backend/.env.example`, `frontend/wrangler.toml`, `frontend/.env*`

`.env`, `.env.local`, and other secret files are gitignored. The runtime contract:

| Variable                          | Surface  | Purpose                                                          |
|-----------------------------------|----------|------------------------------------------------------------------|
| `SUPABASE_URL`                    | both     | Project base URL.                                                |
| `SUPABASE_SERVICE_KEY`            | backend  | RLS-bypass service role key. Never exposed to the browser.       |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY`   | frontend | Browser-safe key used only for Realtime room subscriptions.      |
| `ENCRYPTION_KEY`                  | backend  | 64-hex-char (32-byte) AES-256-GCM key.                           |
| `SESSION_SECRET`                  | both     | HMAC-SHA256 secret for session tokens (≥32 bytes).               |
| `GOOGLE_CLIENT_ID` / `_SECRET`    | backend  | OAuth credentials.                                               |
| `GOOGLE_AUTH_REDIRECT_URI`        | backend  | Pinned OAuth callback URL.                                       |
| `GEMINI_API_KEY`                  | backend  | LLM access.                                                      |
| `COOKIE_DOMAIN`                   | frontend | `.saplinglearn.com` for cross-subdomain session cookies.         |
| `OCR_ENGINE`, `GOT_OCR_ENABLED`   | backend  | OCR backend selection.                                           |

`ENCRYPTION_KEY` and `SESSION_SECRET` are validated at import time — invalid or missing values fail fast.

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

`backend/main.py`'s `RequestLogMiddleware` records method, path, status, duration, and a random 8-char request id. It does **not** log request or response bodies, user ids, emails, names, tokens, or any decrypted column. Errors include the exception class name and traceback only.

Encryption helpers log a structured warning when `decrypt_if_present` falls back to a raw value; that's the operator signal that legacy plaintext is still being read on a column and the backfill should be re-run.

---

## 8. Dependency Surface

Security-relevant packages currently in use (no version audit performed; assume upstream patching):

**Backend (`backend/requirements.txt`)**
- `cryptography>=42,<46` — AES-GCM primitive.
- `fastapi`, `uvicorn` — web framework.
- `google-auth-oauthlib`, `google-api-python-client` — OAuth flow.
- `docling>=2.15`, `transformers>=4.46`, `torch>=2.5` — OCR / document extraction.

**Frontend (`frontend/package.json`)**
- `@supabase/supabase-js` — Realtime client.
- `react`, `next` — UI + middleware.
- `@opennextjs/cloudflare` — Workers adapter.

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
| Logging               | No PII / token / body logging          | `backend/main.py`                                      |
