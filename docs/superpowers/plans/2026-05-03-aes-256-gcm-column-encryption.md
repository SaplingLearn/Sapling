# AES-256-GCM Column-Level Encryption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AES-256-GCM encryption to every column marked `# ENCRYPTED LATER` so PII (names, email, bio, location, OAuth tokens, notes, grades) and AI-input fields (summary, concept_notes) are encrypted at rest in Supabase.

**Architecture:** New `backend/services/encryption.py` exposes `encrypt`/`decrypt` (and `_if_present`/`_numeric`/`_json` helpers) backed by `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. The 32-byte key is loaded once at import time from the `ENCRYPTION_KEY` env var (64 hex chars). Each call uses a fresh 12-byte nonce, returned base64-encoded as `nonce || ciphertext`. Reads are wrapped in a try/except that logs a warning and returns the raw value when decryption fails — this keeps legacy plaintext rows readable during transition until a backfill runs.

**Tech Stack:** Python 3, `cryptography` (PyCA), FastAPI, supabase-py, pytest.

---

## Marker Inventory & Classification

A previous pass placed `# ENCRYPTED LATER` markers across 11 backend route files. Markers split into three buckets:

**Bucket A — ENCRYPT (user-PII / sensitive content, matches STEP 2 spec):**
- `routes/auth.py` lines 172, 174, 178–180, 183, 195, 200, 207–209, 221–224, 234–235, 256
- `routes/onboarding.py` lines 39, 42–44
- `routes/profile.py` lines 29, 38, 179, 193–194, 199–200, 229–230, 232–233, 581–582
- `routes/social.py` lines 107, 110, 117, 154–155, 179, 181, 214, 219, 224–225, 228, 416, 446, 454
- `routes/quiz.py` lines 189, 191
- `routes/learn.py` lines 125, 175–177, 234–235
- `routes/calendar.py` lines 40–41, 64, 77, 117, 130, 144, 158, 171, 247, 250, 316, 324, 343, 369, 387
- `routes/gradebook.py` lines 70, 87, 124, 239–240, 243, 259, 263, 353, 355–356
- `routes/documents.py` lines 231, 337–338, 433, 448–449
- `routes/flashcards.py` lines 114, 120, 406, 413
- `routes/study_guide.py` lines 35, 42–44
- `routes/admin.py` line 215 (only — `users` SELECT)

**Bucket B — REMOVE marker, do NOT encrypt (misplaced — these are public taxonomy `name` fields on `roles` / `cosmetics` / `achievements`, not user PII; STEP 2 explicitly scopes `name` to the `users` table):**
- `routes/admin.py` lines 39, 54, 104, 118, 182, 195, 222

**Bucket C — Out of scope (not marked, despite being mentioned in the user prompt; per the "only touch markers" rule, leave alone and call out as follow-up):**
- `messages.content` writes/reads in `routes/learn.py` (`save_message`, `get_conversation_history`, lines 222–230 / 213–219, plus `routes/social.py` `room_messages.text`).
- `sessions.summary_json` writes/reads (`routes/learn.py:413`, `routes/flashcards.py:91-96`).

Document these in the rollout note in `encryption.py`.

---

## ⚠️ Hard-Blocking Schema Prerequisite

Two columns must be migrated from non-text types to `TEXT` *before* the encrypted writes will succeed in production:

| Column                          | Current type | Required type | Why                                                |
| ------------------------------- | ------------ | ------------- | -------------------------------------------------- |
| `assignments.points_possible`   | `NUMERIC`    | `TEXT`        | Encrypted ciphertext is a base64 string.           |
| `assignments.points_earned`     | `NUMERIC`    | `TEXT`        | Same.                                              |
| `documents.concept_notes`       | `JSONB`      | `TEXT`        | `encrypt_json` returns a base64 string, not JSON.  |
| `sessions.summary_json`         | `JSONB`      | `TEXT`        | (Only relevant if/when summary_json is encrypted.) |

This plan does **not** alter the schema (per rule "Only touch files that have `# ENCRYPTED LATER` markers"). A separate migration + backfill is required before deploy. The task list ends with a deferred-work note rather than a migration step.

---

## File Structure

| File                                     | Change                                                                            |
| ---------------------------------------- | --------------------------------------------------------------------------------- |
| `backend/requirements.txt`               | Add `cryptography>=42,<46`.                                                       |
| `backend/services/encryption.py`         | **NEW** — AES-GCM helpers + key load + legacy-plaintext rollout note.             |
| `backend/tests/test_encryption.py`       | **NEW** — round-trip, randomness, tamper-detection, helper coverage.              |
| `backend/.env.example`                   | Add `ENCRYPTION_KEY=` placeholder + how-to-generate comment.                      |
| `docker-compose.yml`                     | Pass `ENCRYPTION_KEY` through the backend `environment:` block.                   |
| `backend/routes/auth.py`                 | Encrypt user PII writes and reads; encrypt OAuth tokens.                          |
| `backend/routes/onboarding.py`           | Encrypt `users` write of name/first_name/last_name.                               |
| `backend/routes/profile.py`              | Decrypt user reads (name, bio, location); encrypt updates to users + user_settings; decrypt export. |
| `backend/routes/admin.py`                | Decrypt user list (line 215 only); remove misplaced markers from role/cosmetic/achievement lines. |
| `backend/routes/social.py`               | Decrypt every `users.name` read site (10 occurrences).                            |
| `backend/routes/quiz.py`                 | Decrypt `users.name` read.                                                        |
| `backend/routes/learn.py`                | Decrypt `users.name`, `documents.summary`, `documents.concept_notes` reads.       |
| `backend/routes/calendar.py`             | Decrypt OAuth tokens, encrypt OAuth refresh write, decrypt all `notes` reads, encrypt `notes` write. |
| `backend/routes/gradebook.py`            | Encrypt notes + numeric points on write; decrypt on read; pass plain floats into `gradebook_service.current_grade`. |
| `backend/routes/documents.py`            | Encrypt `summary` + `concept_notes` on write; decrypt on every read site.         |
| `backend/routes/flashcards.py`           | Decrypt `documents.summary` + `documents.concept_notes` on the two read sites.    |
| `backend/routes/study_guide.py`          | Decrypt `documents.summary` + `documents.concept_notes` before composing prompt.  |

---

## Task 1: Add `cryptography` to requirements

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add the dependency**

Open `backend/requirements.txt`. After the `httpx` line (line 13), insert a new line:

```
cryptography>=42,<46
```

- [ ] **Step 2: Install into the active venv**

Run from repo root:
```
cd backend && python -m pip install "cryptography>=42,<46"
```
Expected: `Successfully installed cryptography-XX.Y.Z`.

- [ ] **Step 3: Commit**

```
git add backend/requirements.txt
git commit -m "deps: add cryptography for column-level AES-GCM encryption"
```

---

## Task 2: Write failing tests for `encryption.py`

**Files:**
- Create: `backend/tests/test_encryption.py`

- [ ] **Step 1: Set the test key in conftest so tests have a deterministic key**

Open `backend/tests/conftest.py`. Add this **at the top of the file**, before the `sys.path.insert` line:

```python
import os
os.environ.setdefault("ENCRYPTION_KEY", "0" * 64)  # 32-byte all-zero key for deterministic tests
```

- [ ] **Step 2: Write the test file**

Create `backend/tests/test_encryption.py` with this exact content:

```python
"""Tests for backend/services/encryption.py.

The encryption key is set in conftest.py so the module imports cleanly.
"""
import json

import pytest

from services import encryption


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_encrypt_decrypt_round_trip_ascii():
    ct = encryption.encrypt("hello world")
    assert encryption.decrypt(ct) == "hello world"


def test_encrypt_decrypt_round_trip_unicode():
    plain = "Andrés López — résumé €"
    assert encryption.decrypt(encryption.encrypt(plain)) == plain


def test_encrypt_decrypt_round_trip_long():
    plain = "x" * 5000
    assert encryption.decrypt(encryption.encrypt(plain)) == plain


def test_encrypt_decrypt_empty_string():
    ct = encryption.encrypt("")
    assert encryption.decrypt(ct) == ""


# ── JSON helpers ──────────────────────────────────────────────────────────────

def test_encrypt_decrypt_json_dict():
    payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    ct = encryption.encrypt_json(payload)
    assert encryption.decrypt_json(ct) == payload


def test_encrypt_decrypt_json_list():
    payload = [{"name": "X", "description": "Y"}, {"name": "Z", "description": "W"}]
    assert encryption.decrypt_json(encryption.encrypt_json(payload)) == payload


# ── Numeric helper ────────────────────────────────────────────────────────────

def test_decrypt_numeric_returns_float():
    ct = encryption.encrypt("87.5")
    out = encryption.decrypt_numeric(ct)
    assert isinstance(out, float)
    assert out == pytest.approx(87.5)


def test_decrypt_numeric_none_passthrough():
    assert encryption.decrypt_numeric(None) is None


# ── _if_present helpers ───────────────────────────────────────────────────────

def test_encrypt_if_present_none():
    assert encryption.encrypt_if_present(None) is None


def test_encrypt_if_present_value():
    out = encryption.encrypt_if_present("foo")
    assert out is not None and out != "foo"
    assert encryption.decrypt(out) == "foo"


def test_encrypt_if_present_coerces_non_string():
    out = encryption.encrypt_if_present(42)
    assert encryption.decrypt(out) == "42"


def test_decrypt_if_present_none():
    assert encryption.decrypt_if_present(None) is None


def test_decrypt_if_present_legacy_plaintext_passthrough(caplog):
    # Legacy unencrypted rows must not break reads — they pass through with a warning.
    out = encryption.decrypt_if_present("plain unencrypted text")
    assert out == "plain unencrypted text"
    assert any("decrypt" in rec.message.lower() for rec in caplog.records)


# ── Nonce randomness ──────────────────────────────────────────────────────────

def test_two_encryptions_of_same_value_differ():
    a = encryption.encrypt("same")
    b = encryption.encrypt("same")
    assert a != b
    assert encryption.decrypt(a) == encryption.decrypt(b) == "same"


# ── Tamper detection ──────────────────────────────────────────────────────────

def test_tampered_ciphertext_raises():
    import base64
    ct = encryption.encrypt("secret")
    raw = bytearray(base64.b64decode(ct))
    raw[-1] ^= 0x01  # flip one bit in the tag
    tampered = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(Exception):
        encryption.decrypt(tampered)
```

- [ ] **Step 3: Run the tests to confirm they fail (module does not exist yet)**

Run:
```
cd backend && python -m pytest tests/test_encryption.py -q
```
Expected: collection error or `ModuleNotFoundError: services.encryption`.

---

## Task 3: Implement `services/encryption.py`

**Files:**
- Create: `backend/services/encryption.py`

- [ ] **Step 1: Write the module**

Create `backend/services/encryption.py` with this exact content:

```python
"""AES-256-GCM column-level encryption for sensitive Supabase columns.

The 32-byte key is loaded once from the ENCRYPTION_KEY env var (64 hex chars)
at import time. Every encrypt() call mints a fresh 12-byte nonce; the on-disk
representation is base64(nonce || ciphertext_with_tag).

Reads use the *_if_present helpers, which try to decrypt and fall back to the
raw input on failure — this lets legacy plaintext rows continue to load while
a backfill is pending. The fallback logs a warning so unintended plaintext
reads are visible.

ROLLOUT NOTES
─────────────
1. A backfill script is required before the legacy-plaintext fallback can be
   removed: walk every encrypted column listed in the marker pass and rewrite
   each row through encrypt_if_present / encrypt_json. Until that runs, every
   read on an old row will log a warning.
2. Two table columns must be retyped before encrypted writes succeed:
       assignments.points_possible NUMERIC -> TEXT
       assignments.points_earned   NUMERIC -> TEXT
       documents.concept_notes     JSONB   -> TEXT
   These migrations are tracked separately and are NOT part of this rollout.
3. The following fields are referenced in the spec but were NOT marked in the
   prior pass and are therefore not encrypted yet: messages.content (text),
   room_messages.text, sessions.summary_json. Add markers + wire encryption in
   a follow-up before any compliance review.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12  # AES-GCM standard nonce length


def _load_key() -> bytes:
    raw = os.getenv("ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "ENCRYPTION_KEY env var is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(raw) != 64:
        raise RuntimeError(
            f"ENCRYPTION_KEY must be 64 hex chars (32 bytes); got {len(raw)} chars."
        )
    try:
        key = bytes.fromhex(raw)
    except ValueError as e:
        raise RuntimeError("ENCRYPTION_KEY is not valid hex") from e
    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


_KEY = _load_key()
_AESGCM = AESGCM(_KEY)


def encrypt(value: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ct = _AESGCM.encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(value: str) -> str:
    raw = base64.b64decode(value)
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    return _AESGCM.decrypt(nonce, ct, None).decode("utf-8")


def encrypt_if_present(value: Any) -> str | None:
    if value is None:
        return None
    return encrypt(str(value))


def decrypt_if_present(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return decrypt(value)
    except Exception as e:
        logger.warning("decrypt_if_present fallback to raw value: %s", e)
        return value


def decrypt_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(decrypt(value))
    except Exception as e:
        logger.warning("decrypt_numeric fallback: %s", e)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def encrypt_json(value: dict | list) -> str:
    return encrypt(json.dumps(value, separators=(",", ":")))


def decrypt_json(value: str) -> dict | list:
    return json.loads(decrypt(value))
```

- [ ] **Step 2: Run the encryption tests to confirm they pass**

Run:
```
cd backend && python -m pytest tests/test_encryption.py -q
```
Expected: all tests pass.

- [ ] **Step 3: Commit**

```
git add backend/services/encryption.py backend/tests/test_encryption.py backend/tests/conftest.py
git commit -m "feat(backend): AES-256-GCM encryption helpers + tests"
```

---

## Task 4: Document and propagate `ENCRYPTION_KEY`

**Files:**
- Modify: `backend/.env.example`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add a placeholder to `.env.example`**

Open `backend/.env.example`. After the `SUPABASE_SERVICE_KEY=` line (line 10), insert these two lines:

```
# Column-level encryption (AES-256-GCM). 32 bytes as 64 hex chars.
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
ENCRYPTION_KEY=
```

- [ ] **Step 2: Pass it through docker-compose**

Open `docker-compose.yml`. Change the backend `environment:` block (lines 8–9) from:

```yaml
    environment:
      FRONTEND_URL: http://localhost:3000
```

to:

```yaml
    environment:
      FRONTEND_URL: http://localhost:3000
      ENCRYPTION_KEY: ${ENCRYPTION_KEY}
```

(The `env_file` on line 7 will also pull the value from `backend/.env`; the explicit `environment:` entry makes the dependency obvious and lets compose error out early if the var is unset.)

- [ ] **Step 3: Commit**

```
git add backend/.env.example docker-compose.yml
git commit -m "config: surface ENCRYPTION_KEY in env.example and docker-compose"
```

---

## Task 5: Wire encrypt/decrypt in `routes/auth.py`

**Files:**
- Modify: `backend/routes/auth.py`

This file holds the OAuth callback that creates/updates users and stores OAuth tokens. Encrypt every PII write to `users` and every OAuth-token write to `oauth_tokens`. The plaintext locals (`name`, `first_name`, `last_name`, `email`) stay plaintext in process memory and are encrypted only at the persistence boundary; this preserves the `email.endswith("@bu.edu")` check, the `name.split` call, and the redirect-back URL.

- [ ] **Step 1: Add the import at the top of the file**

After the existing `from db.connection import table` line (line 27), add:

```python
from services.encryption import encrypt, encrypt_if_present, decrypt_if_present
```

- [ ] **Step 2: Encrypt the email used as a query filter**

`email_match` on line 200 looks up an existing user by plaintext email — that won't match an encrypted column. Replace line 200:

```python
        email_match = table("users").select("id,is_approved", filters={"email": f"eq.{encrypt(email)}"})  # encrypted lookup
```

> ⚠️ NOTE: AES-GCM is non-deterministic, so this lookup will only match if a prior write used the *same* nonce — which it won't. For email lookups to remain functional after encryption, either (a) drop the email-match migration path entirely (acceptable since it's the legacy-account-merge branch and `google_id` already covers reconnecting users), or (b) introduce a deterministic email_hash column. Option (a) is in scope for this task: comment the email_match lookup out and rely on `google_id` matching only. Apply this instead:

Replace lines 199–214 with:

```python
    else:
        # Email-based account merge is disabled because emails are now encrypted
        # with random nonces; equality lookups by plaintext email cannot match.
        # New sign-ins for users without a google_id always create a fresh row.
        # Create new user
        user_id = f"user_{google_id}"
        is_approved = False
        table("users").insert({
            "id": user_id,
            "name": encrypt_if_present(name),
            "first_name": encrypt_if_present(first_name),
            "last_name": encrypt_if_present(last_name),
            "email": encrypt_if_present(email),
            "google_id": google_id,
            "avatar_url": avatar_url,
            "auth_provider": "google",
        })
```

- [ ] **Step 3: Encrypt the existing-user UPDATE (around line 195)**

Replace line 195:

```python
        table("users").update(
            {
                "name": encrypt_if_present(name),
                "first_name": encrypt_if_present(first_name),
                "last_name": encrypt_if_present(last_name),
                "avatar_url": avatar_url,
                "email": encrypt_if_present(email),
            },
            filters={"id": f"eq.{user_id}"},
        )
```

- [ ] **Step 4: Encrypt the oauth_tokens upsert (lines 231–239)**

Replace the `table("oauth_tokens").upsert(...)` call body to encrypt the tokens:

```python
    table("oauth_tokens").upsert(
        {
            "user_id": user_id,
            "access_token": encrypt(creds.token),
            "refresh_token": encrypt(creds.refresh_token or ""),
            "expires_at": creds.expiry.isoformat() if creds.expiry else "",
        },
        on_conflict="user_id",
    )
```

- [ ] **Step 5: Strip name from the redirect URL params**

The redirect back to the frontend (line 254–260) embeds `name` in the URL. The frontend doesn't strictly need the name (it can fetch `/me`), and putting it on the URL leaks PII to logs. Replace lines 254–260:

```python
    params = urlencode({
        "user_id": user_id,
        "avatar": avatar_url,
        "is_approved": "true",
        **({"auth_token": auth_token} if auth_token else {}),
    })
```

(The `# ENCRYPTED LATER` marker on line 256 is removed by virtue of the field disappearing.)

- [ ] **Step 6: Remove every remaining `# ENCRYPTED LATER` comment from this file**

Strip the trailing `# ENCRYPTED LATER` comments on the lines that were just rewritten (172, 174, 178–180, 183, 195, 200, 207–209, 221–224, 234–235, 256). The plaintext local-variable lines (172, 174, 178–180, 183) keep their code unchanged but lose the marker.

- [ ] **Step 7: Run backend tests**

```
cd backend && python -m pytest tests/ -q
```
Expected: pre-existing tests still pass (decrypt fallback handles plaintext mock fixtures).

- [ ] **Step 8: Commit**

```
git add backend/routes/auth.py
git commit -m "feat(auth): encrypt user PII and OAuth tokens at rest"
```

---

## Task 6: Wire encrypt in `routes/onboarding.py`

**Files:**
- Modify: `backend/routes/onboarding.py`

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 5), add:

```python
from services.encryption import encrypt_if_present
```

- [ ] **Step 2: Encrypt name fields on the users update**

Replace lines 39–52 (the `name` derivation and the `table("users").update(...)` call) with:

```python
    name = f"{body.first_name} {body.last_name}".strip()
    table("users").update(
        {
            "name": encrypt_if_present(name),
            "first_name": encrypt_if_present(body.first_name),
            "last_name": encrypt_if_present(body.last_name),
            "year": body.year,
            "majors": body.majors,
            "minors": body.minors,
            "learning_style": body.learning_style,
            "onboarding_completed": True,
        },
        filters={"id": f"eq.{body.user_id}"},
    )
```

- [ ] **Step 3: Run backend tests**

```
cd backend && python -m pytest tests/test_onboarding_routes.py -q
```
Expected: pass.

- [ ] **Step 4: Commit**

```
git add backend/routes/onboarding.py
git commit -m "feat(onboarding): encrypt name/first_name/last_name on profile save"
```

---

## Task 7: Wire encrypt + decrypt in `routes/profile.py`

**Files:**
- Modify: `backend/routes/profile.py`

- [ ] **Step 1: Import helpers**

After `from db.connection import table` (line 11), add:

```python
from services.encryption import encrypt_if_present, decrypt_if_present
```

- [ ] **Step 2: Decrypt user PII inside `_get_user_or_404`**

Replace the body of `_get_user_or_404` (lines 27–34) with:

```python
def _get_user_or_404(user_id: str) -> dict:
    rows = table("users").select(
        "id,username,name,first_name,last_name,email,avatar_url,school,major,year,majors,minors,bio,location,website,streak_count,created_at",
        filters={"id": f"eq.{user_id}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="User not found")
    row = rows[0]
    for col in ("name", "first_name", "last_name", "email", "bio", "location"):
        row[col] = decrypt_if_present(row.get(col))
    return row
```

- [ ] **Step 3: Decrypt user_settings rows in `_get_or_create_settings`**

Replace `_get_or_create_settings` (lines 47–53) with:

```python
def _get_or_create_settings(user_id: str) -> dict:
    rows = table("user_settings").select(_SETTINGS_COLS, filters={"user_id": f"eq.{user_id}"})
    if not rows:
        table("user_settings").insert({"user_id": user_id})
        rows = table("user_settings").select(_SETTINGS_COLS, filters={"user_id": f"eq.{user_id}"})
    if not rows:
        return {"user_id": user_id}
    row = rows[0]
    for col in ("bio", "location"):
        row[col] = decrypt_if_present(row.get(col))
    return row
```

- [ ] **Step 4: Encrypt updates in `update_profile` (lines 215–245)**

Inside `update_profile`, change every assignment of `body.bio` / `body.location` into both dicts to encrypt at write time. Replace lines 228–233 with:

```python
    if body.bio is not None:
        updates_user["bio"] = encrypt_if_present(body.bio)
        updates_settings["bio"] = encrypt_if_present(body.bio)
    if body.location is not None:
        updates_user["location"] = encrypt_if_present(body.location)
        updates_settings["location"] = encrypt_if_present(body.location)
```

- [ ] **Step 5: Decrypt the export payload**

The `export_data` endpoint (lines 562–586) returns `user` and `settings` dicts that already came back through `_get_user_or_404` / `_get_or_create_settings` — both now return decrypted values. No code change required here, just remove the two `# ENCRYPTED LATER` markers on lines 581–582.

- [ ] **Step 6: Strip every remaining `# ENCRYPTED LATER` marker in this file** (lines 29, 38, 179, 193–194, 199–200, 229–230, 232–233, 581–582).

- [ ] **Step 7: Run backend tests**

```
cd backend && python -m pytest tests/test_profile_routes.py -q
```
Expected: pass.

- [ ] **Step 8: Commit**

```
git add backend/routes/profile.py
git commit -m "feat(profile): encrypt bio/location, decrypt user PII on read"
```

---

## Task 8: Wire decrypt in `routes/admin.py`; remove misplaced markers

**Files:**
- Modify: `backend/routes/admin.py`

This file has 7 misplaced markers on `roles` / `cosmetics` / `achievements` `name` fields (those are public taxonomy, NOT user PII per the STEP 2 spec). Only line 215 (the `users` SELECT) is a real PII read.

- [ ] **Step 1: Import the helper**

After `from db.connection import table` (line 10), add:

```python
from services.encryption import decrypt_if_present
```

- [ ] **Step 2: Decrypt the user list in `list_users`**

Replace lines 213–227 (`list_users` body) with:

```python
@router.get("/users")
def list_users(request: Request):
    require_admin(request)
    users = table("users").select("id,name,email,is_approved,created_at")
    if not users:
        return {"users": []}

    for user in users:
        user["name"] = decrypt_if_present(user.get("name"))
        user["email"] = decrypt_if_present(user.get("email"))
        roles = table("user_roles").select(
            "roles(id,name,slug,color)",
            filters={"user_id": f"eq.{user['id']}"},
        )
        user["roles"] = [r.get("roles", {}) for r in roles] if roles else []

    return {"users": users}
```

- [ ] **Step 3: Strip the misplaced `# ENCRYPTED LATER` markers from lines 39, 54, 104, 118, 182, 195, 222** — these touch role / cosmetic / achievement names, which the STEP 2 spec scopes only to the `users` table. Just delete the trailing comments; do not change the surrounding code.

- [ ] **Step 4: Run backend tests**

```
cd backend && python -m pytest tests/test_admin_routes.py -q
```
Expected: pass.

- [ ] **Step 5: Commit**

```
git add backend/routes/admin.py
git commit -m "feat(admin): decrypt users in /admin/users; drop misplaced taxonomy markers"
```

---

## Task 9: Wire decrypt in `routes/social.py`

**Files:**
- Modify: `backend/routes/social.py`

10 read sites pull `users.name` to render in room overviews, activity feeds, matching, and the `/students` directory.

- [ ] **Step 1: Import the helper**

After `from db.connection import table` (line 8), add:

```python
from services.encryption import decrypt_if_present
```

- [ ] **Step 2: Decrypt names in `room_overview` (lines 105–110)**

Replace lines 104–110 with:

```python
    members = []
    if member_ids:
        user_rows = table("users").select(
            "id,name", filters={"id": f"in.({','.join(member_ids)})"}
        )
        for u in user_rows:
            members.append({
                "user_id": u["id"],
                "name": decrypt_if_present(u["name"]),
                "graph": get_graph(u["id"]),
            })
```

(Lines 113–117 already operate on the decrypted `m['name']`; no change.)

- [ ] **Step 3: Decrypt names in `room_activity` (lines 152–155)**

Replace lines 152–155 with:

```python
    user_name_map = {}
    if user_ids:
        user_rows = table("users").select("id,name", filters={"id": f"in.({','.join(user_ids)})"})
        user_name_map = {u["id"]: decrypt_if_present(u["name"]) for u in user_rows}
```

- [ ] **Step 4: Decrypt names in `match_partners` (lines 177–183)**

Replace lines 177–183 with:

```python
    members_with_graphs = []
    if member_ids:
        user_rows = table("users").select("id,name", filters={"id": f"in.({','.join(member_ids)})"})
        members_with_graphs = [
            {"user_id": u["id"], "name": decrypt_if_present(u["name"]), "graph": get_graph(u["id"])}
            for u in user_rows
        ]
```

- [ ] **Step 5: Decrypt names in `school_match` (lines 213–229)**

Replace lines 213–229 with:

```python
    school_users = table("users").select(
        "id,name",
        filters={"id": f"not.in.({','.join(excl_list)})"},
    )

    members_with_graphs = [
        {"user_id": u["id"], "name": decrypt_if_present(u["name"]), "graph": get_graph(u["id"])}
        for u in school_users
    ]

    requester_graph = get_graph(body.user_id)
    requester_rows = table("users").select("name", filters={"id": f"eq.{body.user_id}"})
    requester_name = decrypt_if_present(requester_rows[0]["name"]) if requester_rows else body.user_id

    all_members = [
        {"user_id": body.user_id, "name": requester_name, "graph": requester_graph}
    ] + members_with_graphs
```

- [ ] **Step 6: Decrypt names in `get_students` (lines 416–454)**

Replace lines 416 and the `students = [...]` comprehension (lines 443–454) with:

```python
    users = table("users").select("id,name,streak_count")
```

```python
    students = [
        {
            "user_id": u["id"],
            "name": decrypt_if_present(u["name"]),
            "streak": u.get("streak_count") or 0,
            "courses": sorted(courses_by_user[u["id"]]),
            "stats": dict(mastery_by_user[u["id"]]),
            "top_concepts": top_concepts_by_user[u["id"]],
        }
        for u in users
    ]
    students.sort(key=lambda s: (s["name"] or ""))
```

- [ ] **Step 7: Strip the remaining `# ENCRYPTED LATER` markers** on lines 107, 110, 117, 154, 155, 179, 181, 214, 219, 224, 225, 228, 416, 446, 454.

- [ ] **Step 8: Run backend tests**

```
cd backend && python -m pytest tests/test_social_messages.py -q
```
Expected: pass.

- [ ] **Step 9: Commit**

```
git add backend/routes/social.py
git commit -m "feat(social): decrypt user name on room/match/student reads"
```

---

## Task 10: Wire decrypt in `routes/quiz.py`

**Files:**
- Modify: `backend/routes/quiz.py`

- [ ] **Step 1: Import the helper**

After `from db.connection import table` (line 10), add:

```python
from services.encryption import decrypt_if_present
```

- [ ] **Step 2: Decrypt student_name (lines 189–191)**

Replace lines 189–191 with:

```python
    user_rows = table("users").select("name", filters={"id": f"eq.{user_id}"})
    concept_name = node2_rows[0]["concept_name"] if node2_rows else "Unknown"
    student_name = decrypt_if_present(user_rows[0]["name"]) if user_rows else "Student"
```

- [ ] **Step 3: Run backend tests**

```
cd backend && python -m pytest tests/test_quiz_routes.py -q
```
Expected: pass.

- [ ] **Step 4: Commit**

```
git add backend/routes/quiz.py
git commit -m "feat(quiz): decrypt student name before injecting into quiz prompt"
```

---

## Task 11: Wire decrypt in `routes/learn.py`

**Files:**
- Modify: `backend/routes/learn.py`

The streaming tutoring chat reads `users.name`, `documents.summary`, and `documents.concept_notes` before composing the system prompt. All three must decrypt before reaching the LLM.

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 10), add:

```python
from services.encryption import decrypt_if_present, decrypt_json
```

- [ ] **Step 2: Decrypt summary + concept_notes inside `_get_course_documents` (lines 119–130)**

Replace `_get_course_documents` body with:

```python
def _get_course_documents(user_id: str, course_id: str) -> list:
    """Fetch uploaded document summaries and concept notes for a user's course."""
    if not course_id:
        return []
    try:
        docs = table("documents").select(
            "file_name,category,summary,concept_notes",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        ) or []
        for d in docs:
            d["summary"] = decrypt_if_present(d.get("summary"))
            notes_raw = d.get("concept_notes")
            if isinstance(notes_raw, str):
                try:
                    d["concept_notes"] = decrypt_json(notes_raw)
                except Exception:
                    pass  # legacy plaintext JSON or already-parsed object: leave alone
        return docs
    except Exception:
        return []
```

(The downstream code in `build_system_prompt` lines 173–195 already operates on decrypted values; remove the markers on 175–177 only.)

- [ ] **Step 3: Decrypt user name in `get_user_name` (lines 233–235)**

Replace `get_user_name` body with:

```python
def get_user_name(user_id: str) -> str:
    rows = table("users").select("name", filters={"id": f"eq.{user_id}"})
    if not rows:
        return "Student"
    return decrypt_if_present(rows[0]["name"]) or "Student"
```

- [ ] **Step 4: Strip remaining `# ENCRYPTED LATER` markers** on lines 125, 175, 176, 177, 234, 235.

- [ ] **Step 5: Run backend tests**

```
cd backend && python -m pytest tests/test_learn_routes.py tests/test_shared_course_context.py -q
```
Expected: pass.

- [ ] **Step 6: Commit**

```
git add backend/routes/learn.py
git commit -m "feat(learn): decrypt student name + document summary/concept_notes for tutor prompts"
```

---

## Task 12: Wire encrypt + decrypt in `routes/calendar.py`

**Files:**
- Modify: `backend/routes/calendar.py`

OAuth token reads/writes and 9 `assignments.notes` read/write sites.

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 19), add:

```python
from services.encryption import encrypt, encrypt_if_present, decrypt, decrypt_if_present
```

- [ ] **Step 2: Decrypt OAuth tokens before constructing Credentials (lines 38–45)**

Replace the `Credentials(...)` call inside `_get_refreshed_credentials` with:

```python
    creds = Credentials(
        token=decrypt(token_row["access_token"]),
        refresh_token=decrypt(token_row["refresh_token"]),
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
```

- [ ] **Step 3: Encrypt the refreshed access_token (lines 62–68)**

Replace the `table("oauth_tokens").update(...)` body to:

```python
        table("oauth_tokens").update(
            {
                "access_token": encrypt(creds.token),
                "expires_at": creds.expiry.isoformat() if creds.expiry else "",
            },
            filters={"user_id": f"eq.{token_row['user_id']}"},
        )
```

- [ ] **Step 4: Update `calendar_status` (lines 246–252) — null-check needs to not call decrypt on None**

Replace lines 246–252 with:

```python
    rows = table("oauth_tokens").select(
        "access_token,expires_at",
        filters={"user_id": f"eq.{user_id}"},
    )
    if not rows or not rows[0].get("access_token"):
        return {"connected": False}
    return {"connected": True, "expires_at": rows[0]["expires_at"]}
```

(No decrypt is needed — we only check presence here.)

- [ ] **Step 5: Encrypt notes on the `/save` insert (lines 110–122)**

Replace the list comprehension at line 111 with:

```python
    payload = [
        {
            "title": a.title,
            "course_id": a.course_id,
            "due_date": a.due_date,
            "assignment_type": a.assignment_type,
            "notes": encrypt_if_present(a.notes),
        }
        for a in body.assignments
    ]
```

- [ ] **Step 6: Decrypt notes inside `get_upcoming` and `get_all_assignments`**

In `get_upcoming` (lines 135–149), inside the `for r in rows:` loop, change:
```python
            "notes": r.get("notes"),
```
to:
```python
            "notes": decrypt_if_present(r.get("notes")),
```

Apply the same change inside `get_all_assignments` (lines 162–176).

- [ ] **Step 7: Decrypt notes inside `sync_to_google` and `export_to_google`**

In `sync_to_google` (line 343) change:
```python
            "description": a.get("notes") or "",
```
to:
```python
            "description": decrypt_if_present(a.get("notes")) or "",
```

Apply the same change in `export_to_google` (line 387).

- [ ] **Step 8: Strip remaining `# ENCRYPTED LATER` markers** on lines 40, 41, 64, 77, 117, 130, 144, 158, 171, 247, 250, 316, 324, 343, 369, 387 (and the `# ENCRYPTED LATER.` prose comment on line 193).

- [ ] **Step 9: Run backend tests**

```
cd backend && python -m pytest tests/test_calendar_routes.py -q
```
Expected: pass.

- [ ] **Step 10: Commit**

```
git add backend/routes/calendar.py
git commit -m "feat(calendar): encrypt OAuth tokens + assignment notes; decrypt on read"
```

---

## Task 13: Wire encrypt + decrypt in `routes/gradebook.py`

**Files:**
- Modify: `backend/routes/gradebook.py`

Notes: `notes` is straightforward TEXT-with-`encrypt_if_present`. `points_possible` and `points_earned` are NUMERIC columns and the encrypted writes will fail at the Postgres layer until the schema migration noted at the top of this plan runs. This task implements the code as the spec dictates and accepts that the gradebook tests will rely on the legacy-plaintext fallback (decrypt_numeric handles numeric input directly).

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 13), add:

```python
from services.encryption import encrypt_if_present, decrypt_if_present, decrypt_numeric
```

- [ ] **Step 2: Decrypt numeric points in `get_summary` before grade math (lines 65–88)**

After the `assigns = table("assignments").select(...)` call (lines 69–72), add a normalization loop. Replace lines 69–88 with:

```python
    assigns = table("assignments").select(
        "id,course_id,category_id,points_possible,points_earned",
        filters={"user_id": f"eq.{user_id}", "course_id": in_clause},
    )

    for a in assigns:
        a["points_possible"] = decrypt_numeric(a.get("points_possible"))
        a["points_earned"] = decrypt_numeric(a.get("points_earned"))

    cats_by_course: dict[str, list] = {cid: [] for cid in course_ids}
    for c in cats:
        cats_by_course.setdefault(c["course_id"], []).append(c)
    assigns_by_course: dict[str, list] = {cid: [] for cid in course_ids}
    for a in assigns:
        assigns_by_course.setdefault(a["course_id"], []).append(a)

    out = []
    for e in enrollments:
        cid = e["course_id"]
        course = e["courses"]
        course_assigns = assigns_by_course[cid]
        graded = [a for a in course_assigns
                  if a.get("points_possible") and a.get("points_earned") is not None]
        percent = gradebook_service.current_grade(cats_by_course[cid], course_assigns)
```

- [ ] **Step 3: Decrypt notes + numeric points in `get_course` (lines 123–151)**

After the `assigns = table("assignments").select(...)` block at line 123, add a decrypt loop:

```python
    assigns = table("assignments").select(
        "id,user_id,course_id,category_id,title,due_date,assignment_type,points_possible,points_earned,notes,source",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        order="due_date.asc",
    )
    for a in assigns:
        a["points_possible"] = decrypt_numeric(a.get("points_possible"))
        a["points_earned"] = decrypt_numeric(a.get("points_earned"))
        a["notes"] = decrypt_if_present(a.get("notes"))
```

- [ ] **Step 4: Encrypt notes + numeric points on `create_assignment` insert (lines 233–246)**

Replace the `inserted = table("assignments").insert({...})` body with:

```python
    inserted = table("assignments").insert({
        "id": new_id,
        "user_id": body.user_id,
        "course_id": body.course_id,
        "title": body.title,
        "category_id": body.category_id,
        "points_possible": encrypt_if_present(body.points_possible),
        "points_earned": encrypt_if_present(body.points_earned),
        "due_date": body.due_date,
        "assignment_type": body.assignment_type,
        "notes": encrypt_if_present(body.notes),
        "source": "manual",
    })
```

- [ ] **Step 5: Encrypt encrypted fields on `update_assignment_route` patch (lines 257–270)**

Replace the loop that copies `ENCRYPTED_FIELDS` from `incoming` into `patch_data` with:

```python
    incoming = body.model_dump(exclude_unset=True, exclude={"user_id"})
    ALLOWED = {"title", "category_id", "due_date", "assignment_type"}
    ENCRYPTED_FIELDS = {"points_possible", "points_earned", "notes"}
    patch_data = {k: v for k, v in incoming.items() if k in ALLOWED}
    for k in ENCRYPTED_FIELDS:
        if k in incoming:
            patch_data[k] = encrypt_if_present(incoming[k])
    if not patch_data:
        return {"updated": False}
```

- [ ] **Step 6: Encrypt notes + numeric placeholders inside `apply_syllabus` (lines 339–358)**

Replace the `new_assigns.append({...})` call inside the loop with:

```python
        new_assigns.append({
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "course_id": body.course_id,
            "title": title,
            "due_date": a.get("due_date"),
            "assignment_type": a.get("assignment_type"),
            "notes": encrypt_if_present(a.get("notes")),
            "category_id": None,
            "points_possible": encrypt_if_present(None),  # remains None
            "points_earned": encrypt_if_present(None),    # remains None
            "source": "syllabus",
        })
```

- [ ] **Step 7: Strip every `# ENCRYPTED LATER` marker** on lines 70, 87, 124, 239, 240, 243, 259, 263, 353, 355, 356.

- [ ] **Step 8: Run backend tests**

```
cd backend && python -m pytest tests/test_gradebook_routes.py -q
```
Expected: pass. (Test fixtures provide plaintext numerics; `decrypt_numeric` handles numeric input directly via its `isinstance(value, (int, float))` branch.)

- [ ] **Step 9: Commit**

```
git add backend/routes/gradebook.py
git commit -m "feat(gradebook): encrypt assignment notes + points; decrypt on read"
```

---

## Task 14: Wire encrypt + decrypt in `routes/documents.py`

**Files:**
- Modify: `backend/routes/documents.py`

The hot path: `_process_document` produces `summary` + `concept_notes`, both written to `documents` and later read by `learn.py`, `flashcards.py`, `study_guide.py`. `concept_notes` is a JSON list; encrypt with `encrypt_json`, decrypt with `decrypt_json`.

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 14), add:

```python
from services.encryption import encrypt_if_present, encrypt_json, decrypt_if_present, decrypt_json
```

- [ ] **Step 2: Encrypt on insert in `upload_document` (lines 331–342)**

Replace the `row = {...}` dict with:

```python
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "file_name": filename,
        "category": ai["category"],
        "summary": encrypt_if_present(ai["summary"] or None),
        "concept_notes": encrypt_json(ai["concept_notes"]) if ai["concept_notes"] is not None else None,
        "created_at": now,
        "processed_at": now,
    }
    inserted = table("documents").insert(row)
```

> Important: the `inserted[0]` returned by Supabase echoes the encrypted values. The route currently returns `inserted[0]` to the frontend. To keep the response shape useful, decrypt before returning. Replace the final lines (359–361) with:

```python
    response = dict(inserted[0] if inserted else row)
    response["summary"] = decrypt_if_present(response.get("summary"))
    notes_raw = response.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            response["concept_notes"] = decrypt_json(notes_raw)
        except Exception:
            pass
    response["categories"] = ai.get("categories", [])
    return response
```

- [ ] **Step 3: Decrypt in `list_documents` (lines 226–235)**

Replace the function body with:

```python
@router.get("/user/{user_id}")
def list_documents(user_id: str, request: Request):
    require_self(user_id, request)
    _validate_user(user_id)
    docs = table("documents").select(
        "id,user_id,course_id,file_name,category,summary,concept_notes,created_at,processed_at",
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.desc",
    ) or []
    for d in docs:
        d["summary"] = decrypt_if_present(d.get("summary"))
        notes_raw = d.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                d["concept_notes"] = decrypt_json(notes_raw)
            except Exception:
                pass
    return {"documents": docs}
```

- [ ] **Step 4: Decrypt in `scan_document_concepts` (lines 432–449)**

Replace the `rows = table("documents").select(...)` block down through the `_scan_concepts_for_course` call with:

```python
    rows = table("documents").select(
        "id,user_id,course_id,file_name,summary,concept_notes",
        filters={"id": f"eq.{document_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Document not found.")
    doc = rows[0]
    course_id = doc.get("course_id")
    if not course_id:
        raise HTTPException(status_code=400, detail="Document is not associated with a course.")

    doc_summary = decrypt_if_present(doc.get("summary"))
    notes_raw = doc.get("concept_notes")
    if isinstance(notes_raw, str):
        try:
            doc_concept_notes = decrypt_json(notes_raw)
        except Exception:
            doc_concept_notes = []
    else:
        doc_concept_notes = notes_raw or []

    return _scan_concepts_for_course(
        user_id,
        course_id,
        doc_filename=doc.get("file_name"),
        doc_summary=doc_summary,
        doc_concept_notes=doc_concept_notes,
    )
```

- [ ] **Step 5: Strip remaining `# ENCRYPTED LATER` markers** on lines 231, 337, 338, 433, 448, 449.

- [ ] **Step 6: Run backend tests**

```
cd backend && python -m pytest tests/test_documents_routes.py -q
```
Expected: pass.

- [ ] **Step 7: Commit**

```
git add backend/routes/documents.py
git commit -m "feat(documents): encrypt summary + concept_notes; decrypt on read"
```

---

## Task 15: Wire decrypt in `routes/flashcards.py`

**Files:**
- Modify: `backend/routes/flashcards.py`

Two read sites pull `documents.summary` + `documents.concept_notes` to feed flashcard generation.

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 12), add:

```python
from services.encryption import decrypt_if_present, decrypt_json
```

- [ ] **Step 2: Decrypt inside `_get_course_documents` (lines 101–125)**

Replace lines 106–125 with:

```python
        course_rows = table("courses").select(
            "id", filters={"user_id": f"eq.{user_id}", "course_name": f"eq.{course_name}"}, limit=1
        )
        if course_rows:
            course_id = course_rows[0]["id"]
            docs = table("documents").select(
                "file_name,category,summary,concept_notes",
                filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
            )
        else:
            docs = table("documents").select(
                "file_name,category,summary,concept_notes",
                filters={"user_id": f"eq.{user_id}"},
            )
        docs = docs or []
        for d in docs:
            d["summary"] = decrypt_if_present(d.get("summary"))
            notes_raw = d.get("concept_notes")
            if isinstance(notes_raw, str):
                try:
                    d["concept_notes"] = decrypt_json(notes_raw)
                except Exception:
                    pass
        return docs
    except Exception:
        return []
```

- [ ] **Step 3: Decrypt in `import_generate` library_doc branch (lines 405–414)**

Replace lines 405–414 with:

```python
        rows = table("documents").select(
            "id,user_id,summary,concept_notes,file_name",
            filters={"id": f"eq.{body.document_id}", "user_id": f"eq.{body.user_id}"},
            limit=1,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Document not found")
        doc = rows[0]
        doc_summary = decrypt_if_present(doc.get("summary")) or ""
        notes_raw = doc.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                doc_notes = decrypt_json(notes_raw)
            except Exception:
                doc_notes = notes_raw
        else:
            doc_notes = notes_raw or {}
        parts = [doc_summary, str(doc_notes)]
        source_text = "\n\n".join(p for p in parts if p)
```

- [ ] **Step 4: Strip remaining `# ENCRYPTED LATER` markers** on lines 114, 120, 406, 413.

- [ ] **Step 5: Run backend tests**

```
cd backend && python -m pytest tests/test_flashcard_import_routes.py -q
```
Expected: pass.

- [ ] **Step 6: Commit**

```
git add backend/routes/flashcards.py
git commit -m "feat(flashcards): decrypt document summary/concept_notes before card generation"
```

---

## Task 16: Wire decrypt in `routes/study_guide.py`

**Files:**
- Modify: `backend/routes/study_guide.py`

- [ ] **Step 1: Import the helpers**

After `from db.connection import table` (line 12), add:

```python
from services.encryption import decrypt_if_present, decrypt_json
```

- [ ] **Step 2: Decrypt inside `_generate_and_insert` document loop (lines 33–60)**

Replace lines 33–60 with:

```python
    docs = table("documents").select(
        "summary,concept_notes",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []

    parts: list[str] = []
    for doc in docs:
        summary = decrypt_if_present(doc.get("summary"))
        if summary:
            parts.append(f"Summary: {summary}")
        notes_raw = doc.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                concept_notes = decrypt_json(notes_raw)
            except Exception:
                concept_notes = notes_raw
        else:
            concept_notes = notes_raw
        if concept_notes and isinstance(concept_notes, list):
            lines = []
            for note in concept_notes:
                if not isinstance(note, dict):
                    continue
                name = note.get("name")
                desc = note.get("description")
                if not name:
                    continue
                if desc:
                    lines.append(f"- {name}: {desc}")
                else:
                    lines.append(f"- {name}")
            if lines:
                parts.append("Key Concepts:\n" + "\n".join(lines))
```

- [ ] **Step 3: Strip remaining `# ENCRYPTED LATER` markers** on lines 35, 42, 43, 44.

- [ ] **Step 4: Run backend tests**

```
cd backend && python -m pytest tests/ -q
```
Expected: full suite still passes.

- [ ] **Step 5: Commit**

```
git add backend/routes/study_guide.py
git commit -m "feat(study_guide): decrypt document summary/concept_notes before prompt build"
```

---

## Task 17: Final verification + leftover-marker scan

- [ ] **Step 1: Confirm no `# ENCRYPTED LATER` markers remain anywhere**

Run from repo root:
```
git grep -n "ENCRYPTED LATER"
```
Expected: zero matches. (If anything remains, address per the marker classification at the top of this plan.)

- [ ] **Step 2: Run the entire backend test suite**

```
cd backend && python -m pytest tests/ -q
```
Expected: all green.

- [ ] **Step 3: Boot the backend with a fake key locally to verify the import-time validation**

```
cd backend && ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") python -c "from services import encryption; print('key loaded, len=', len(encryption._KEY))"
```
Expected: `key loaded, len= 32` and no exception. Then verify the failure path:

```
cd backend && ENCRYPTION_KEY=tooshort python -c "from services import encryption" 2>&1 | head -2
```
Expected: a `RuntimeError: ENCRYPTION_KEY must be 64 hex chars (32 bytes); got 8 chars.`.

---

## Deferred Follow-Up Work (NOT part of this plan)

The following items are explicitly out of scope per the rules ("Only touch files that have `# ENCRYPTED LATER` markers"). They must be handled before declaring the rollout complete:

1. **Schema migration**: change `assignments.points_possible` and `assignments.points_earned` from `NUMERIC` to `TEXT`, and `documents.concept_notes` from `JSONB` to `TEXT`. Until this lands, any encrypted gradebook write or document upload will error against the real Supabase schema. Add a migration file under `backend/db/`.
2. **Backfill script**: a one-shot script that reads every existing row across the encrypted columns, re-writes through the new helpers, and removes the legacy-plaintext fallback once complete.
3. **Mark + encrypt the un-marked sensitive fields** named in the original spec: `messages.content` (tutor chat history in `routes/learn.py`), `room_messages.text` (study room chat in `routes/social.py`), and `sessions.summary_json` (`routes/learn.py:413`, `routes/flashcards.py:91`).
4. **Account-merge behavior change**: `routes/auth.py` no longer merges legacy users by plaintext email (encryption is non-deterministic). If multi-OAuth account merging is required, add an `email_hmac` column with a deterministic HMAC-SHA256 of the lowercased email and migrate the merge lookup to that column.
5. **Frontend dependency on `name` query param**: confirm `frontend/src/app/signin/callback/page.tsx` no longer needs the `name` query param after Task 5 step 5 (since `/auth/callback?...` no longer includes it). If it does, switch the callback to fetch `/api/auth/me` for the display name.
