# DB Identity Reconcile — fix cross-domain `users.name` breakages from the 0024 split

Branch: `db/identity-reconcile` off `epic/db-modular-redesign`.

## Problem

Migration 0024 (identity split) moved the public-profile fields **out of `users`**
into a new 1:1 `user_profiles` table (PK/FK `user_id`). `name` (and
`first_name`/`last_name`/`bio`/`location`) are 🔒 column-encrypted on
`user_profiles`. Migration 0024 also **renamed `users.room_id` → `users.current_room_id`**.

The identity slice updated identity-owned files (`routes/profile.py`) but left
cross-domain readers/writers of `users.name` untouched. Mocked tests didn't catch
these because they stub `table()`; against the real DB these raise (writes) or
return NULL → blank names (reads).

Separately: migration 0025 rebuilt `flashcards` with the link column named
`offering_id` (was `course_id`); `flashcard_import_service.dedup_against_existing`
still filters on `course_id`.

## The `user_profiles` pattern (established in `routes/profile.py`)

- 1:1 with `users` on `user_id`.
- Encrypted columns: `name, first_name, last_name, bio, location`.
- Write via `encrypt_if_present`; read via `decrypt_if_present`
  (both from `services/encryption.py`).
- A row may not exist yet for a freshly FK-stubbed user (it's created at
  onboarding/oauth). Display-name reads must tolerate a missing row → "" / fallback.

## New helper: `services/profiles.py`

```
get_display_name(user_id: str) -> str
    Read user_profiles.name by user_id, decrypt_if_present, return "" if absent.

get_display_names(user_ids: list[str]) -> dict[str, str]
    Bulk: one `in.(...)` select on user_profiles, returns {user_id: decrypted_name}.
    Missing rows simply absent from the dict (callers default per their old shape).
```

All DB access through `db.connection.table("user_profiles")`. Decrypt via
`services.encryption.decrypt_if_present`.

## Site list (current → new)

### HARD WRITE BREAK
- `services/graph_service.py` `ensure_user_exists` (~L72):
  `insert({"id": user_id, "name": name, "streak_count": 0})`
  → `insert({"id": user_id, "streak_count": 0})`. Drop the derived `name` and the
  derivation line. Do **not** create a `user_profiles` row here (onboarding/oauth own it).

### READ sites (NULL → blank name)
- `main.py:191` `list_users`: `select("id,name,room_id")` on `users`.
  - `name` no longer on `users` → use `get_display_names([...])`.
  - `room_id` renamed → select `current_room_id`, still return it under key `"room_id"`.
  - Response shape unchanged: `{"users": [{"id","name","room_id"}]}` sorted by name.
- `routes/social.py:159` (room activity): bulk `select("id,name")` →
  `get_display_names(user_ids)`; `user_name` falls back to `user_id` when absent.
- `routes/social.py:184` (`match_partners`): per-member name →
  `get_display_names(member_ids)`; name falls back to "".
- `routes/social.py:225/229` (`school_match`): bulk member names + requester name →
  `get_display_names(...)` for members, `get_display_name(body.user_id)` for requester
  (fallback to `body.user_id` to match old behavior).
- `routes/social.py:469` (`get_students`): `select("id,name,streak_count")` →
  select `id,streak_count` and resolve names via `get_display_names([u["id"]...])`.
  Response keys unchanged: `user_id,name,streak,courses,stats,top_concepts`.
- `routes/quiz.py:461`: `table("users").select("name")` → `get_display_name(user_id)`
  with "Student" fallback (matches old `if user_rows else "Student"`).
- `routes/learn.py:382` `get_user_name`: `table("users").select("name")` →
  `get_display_name(user_id)` with "Student" fallback.

### flashcards column rename
- `services/flashcard_import_service.py:51,57,59-60` `dedup_against_existing`:
  rename param `course_id` → `offering_id`; filter key `course_id` → `offering_id`.
  Caller `routes/flashcards.py:335` already passes the resolved `offering_id`
  positionally, so update the keyword/positional binding accordingly (positional —
  no call-site change needed beyond clarity). Behavior identical.

## users_search decision

`services/users_search.py::paginate_users` reads `table("users").select("id,name,email,...")`
directly — **not** a DB view (grepped: no `search_users_decrypted` / decrypted view
exists in `db/migrations/`). After 0024, `users.name` is gone, so `name` must come
from `user_profiles`.

**Decision: CODE-ONLY fix, no migration.** Select identity columns from `users`
(`id,email,is_approved,created_at,last_sign_in_at`), then enrich each page's rows
with decrypted names from `user_profiles` via `get_display_names`. For the search
path we still need names for every user to filter — fetch all profile names in bulk
(admin scale, behind `require_admin`, matches the existing "decrypt the whole table"
rationale). No `0028` migration required.

## Tests (TDD)

- `tests/test_profiles_service.py` (new):
  - `get_display_name` decrypts a present row; returns "" when absent.
  - `get_display_names` bulk-maps decrypted names; missing rows omitted; empty input.
- `tests/test_graph_service.py` or a new focused test: assert `ensure_user_exists`
  insert payload does **not** contain `"name"` (and contains `id`/`streak_count`).
- Update `tests/test_users_roster_auth.py`: mock now returns `current_room_id` on
  users + a `user_profiles` lookup for names.
- Update `tests/test_social_students.py`: users rows no longer carry `name`; add a
  `user_profiles` lookup in the table factory.
- Update `tests/test_users_search.py`: users rows carry no `name`; add a
  `user_profiles` lookup.
- Update `tests/test_flashcard_import*`/`test_flashcards*` if they assert the
  `course_id` filter key → `offering_id`.

## Gate

- `cd backend && $PY -m pytest tests/ -q` — zero NEW failures beyond the 2 known
  env-only `test_storage_service.py` failures.
- `$RUFF check .` — clean.
- Commit on `db/identity-reconcile`, push `-u origin db/identity-reconcile`. No PR.
