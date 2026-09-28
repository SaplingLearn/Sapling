# Feature flags (#620): design

- **Status:** approved in conversation on 2026-09-27; this spec is awaiting review.
- **Epic:** #620.
- **Target:** 2026-10-02, ahead of the 2026-10-15 beta.
- **Branch:** `feat/620-feature-flags`, stacked on the #676 → #671 → #672 → #677 → #675 stack.

## 1. Goal

Turn features on, off, or partially on from Sapling's `/admin` page, for one student, a role, a percentage of students, or everyone, with no redeploy. Every change is audited. It fails closed.

### Non-goals, v1
- **No Canopy integration.** Flags live in Sapling's admin only; a read-only Canopy view is a possible follow-up.
- **No course/offering cohort targeting.** That's a possible follow-up.
- **No PostHog feature flags, deliberately.** Evaluating per-user flags there would send user ids to PostHog. That contradicts the analytics opt-out model (ADR 0028), and it would make app behaviour depend on an analytics vendor.
- **No creating flags from the UI.** Flags are declared in code (§3).

## 2. Data model

One migration, with a timestamp-prefixed name per `db/migrations/README.md`.

```sql
CREATE TABLE IF NOT EXISTS feature_flags (
    key              TEXT PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,62}$'),
    default_variant  TEXT NOT NULL,
    rollout_percent  SMALLINT NOT NULL DEFAULT 0 CHECK (rollout_percent BETWEEN 0 AND 100),
    rollout_variant  TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by       TEXT REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS feature_flag_targets (
    flag_key     TEXT NOT NULL REFERENCES feature_flags(key) ON DELETE CASCADE,
    target_type  TEXT NOT NULL CHECK (target_type IN ('user', 'role')),
    target_id    TEXT NOT NULL,
    variant      TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by   TEXT REFERENCES users(id) ON DELETE SET NULL,
    PRIMARY KEY (flag_key, target_type, target_id)
);

-- Analytics defaults ON once keys are set; admin can switch it off (§6.3).
INSERT INTO feature_flags (key, default_variant) VALUES ('product_analytics', 'on')
ON CONFLICT (key) DO NOTHING;
```

- **Variant validity is enforced by the app, not the database.** The database doesn't know the registry. Every write path validates against the registry, and the resolver treats an unknown stored variant as the off variant.
- **Rules for deleted users are harmless** and are left in place. They can't match: a deleted user has no session.

## 3. Flags are declared in code, configured in the database

`backend/services/feature_flags.py` holds a registry:

```python
@dataclass(frozen=True)
class FlagDef:
    key: str
    variants: tuple[str, ...]   # variants[0] is the OFF variant (fail-closed answer)
    description: str
    client_visible: bool        # exposed via GET /api/flags

REGISTRY = {f.key: f for f in (
    FlagDef("decision_router", ("off", "jev", "jev_shadow"),
            "Tutor turn router on the Jev decision seam (ADR 0027).", False),
    FlagDef("learning_loop", ("off", "on"),
            "AI learning loop (#673).", True),
    FlagDef("product_analytics", ("off", "on"),
            "PostHog product analytics, frontend + backend (ADR 0028).", True),
)}
```

- A registered flag with no database row resolves to its off variant, apart from any env override.
- Database rows for keys that aren't in the registry are ignored.
- Adding a flag takes one registry line; the database row appears the first time an admin edits it.

## 4. Resolution

`flag_variant(key, user_id) -> str`. The first match wins:

1. **Env override.** `SAPLING_FLAG_<KEY_UPPER>=<variant>` wins. An invalid value is ignored with a warn-once.
   - Legacy for `decision_router`: if `SAPLING_DECISIONS_BACKEND` is set explicitly (non-empty), the existing `decisions.configured_backend()` / `shadow_backend()` path is used unchanged. The flag isn't consulted.
2. **Fail closed.** An unregistered key, or any error reading the snapshot, gives `variants[0]`, with a warn-once.
3. **User rule:** `(user, user_id)`.
4. **Role rule.** Among the user's roles that have a rule, the one with the highest `roles.display_priority` wins; ties go to the lowest role id.
5. **Percentage rollout.** Compute `bucket = int(sha256(f"{key}:{user_id}").hexdigest()[:8], 16) % 10000 / 100`. If `bucket < rollout_percent`, the result is `rollout_variant`.
   - The bucket is stable per user and flag.
   - Raising the percentage only adds students; it never reshuffles who's in.
6. **Default:** `default_variant`.

A request with no signed-in user only reaches steps 1, 2 and 6.

A stored variant that isn't in the registry's `variants` resolves to `variants[0]`.

Helpers:
- `flag_on(key, user_id) -> bool` is `flag_variant(...) != variants[0]`.
- `require_flag(key)` is a FastAPI dependency. It answers 404 when the flag is off for the session user.
- `resolved_client_flags(user_id) -> dict[str, str]` returns the flags with `client_visible` set.

### 4.1 Caching (#98 convention)

- **Snapshot.** All flag rows and all target rows are loaded in one read into an immutable snapshot, cached per process with a 30s TTL. `clear_feature_flags_cache()` is called by every admin flag write.
- **User roles.** Cached per user for 60s. `clear_user_roles_cache(user_id)` is called by the admin role assign and revoke routes.
- **Tests.** Both caches are cleared by the autouse fixture in `tests/conftest.py`.
- **Failure handling.** A failed snapshot read is not cached as success; it's retried on the next call. Callers get the fail-closed answer meanwhile.
- **Staleness.** Other replicas see a change within 30s.

## 5. API

### 5.1 Admin API (`routes/admin_flags.py`, mounted `/api/admin/flags`, all `require_admin`)

| Method | Path | Body / query | Notes |
|---|---|---|---|
| GET | `/api/admin/flags` | none | Every registered flag: registry fields, stored config, rules (users shown by display name via `services/profiles.py`, roles by name), `updated_at`/`updated_by`. |
| PATCH | `/api/admin/flags/{key}` | `{default_variant?, rollout_percent?, rollout_variant?}` | Upserts the row. Validated against the registry. `rollout_variant` is required when `rollout_percent > 0`. |
| PUT | `/api/admin/flags/{key}/targets` | `{target_type, target_id, variant}` | Upsert. The user or role must exist. |
| DELETE | `/api/admin/flags/{key}/targets/{target_type}/{target_id}` | none | |
| GET | `/api/admin/flags/{key}/explain` | `?user_id=` | Returns `{variant, step, detail}`, where `step` is one of `env_override`/`fail_closed`/`user`/`role`/`rollout`/`default`. |

Every write:
1. validates;
2. writes through `table()`;
3. calls `admin_audit.log_admin_action(...)` with the before and after values;
4. emits `flag.changed` through `events_service.log_event`, registered in `EVENT_TAXONOMY`, with a payload of `{key, field, before, after}`;
5. calls `clear_feature_flags_cache()`.

An unknown key returns 404 and an invalid variant returns 422.

### 5.2 Client API (`GET /api/flags`)

- **Signed in** (session optional): returns `{"flags": {key: variant}}` for `client_visible` flags.
- **Signed out:** returns their defaults (steps 1, 2 and 6).
- **Caching:** `Cache-Control: private, no-store`.
- **Router mount:** in `main.py`.

## 6. Consumers

### 6.1 `decision_router` (#672)

The tutor router (`services/tutor_router.py::observe_tutor_turn`) resolves `flag_variant("decision_router", user_id)` for the turn's student, unless the legacy env from §4 step 1 is set:

| Variant | Primary backend | Shadow |
|---|---|---|
| `off` | none (no call) | none |
| `jev` | `jev` | off |
| `jev_shadow` | `jev` | `flash_lite` |

- `decisions.decide()` gains optional keyword-only `backend=` and `shadow=` overrides. Its env-driven defaults are unchanged for other callers.
- Function mode (E2E) keeps its automatic `function` backend. The flag isn't consulted there, so E2E stays deterministic.
- **Result:** Railway needs only `TYPESAFE_API_KEY`. Rollout is staff role first, then a percentage.

### 6.2 `learning_loop` (#673, owned by Jose)

- The flag system provides `learning_loop`.
- #673 is **not edited here**. A PR comment on #673 will propose:
  - `learning/gate.py::learning_loop_active` → `LEARNING_LOOP_ENABLED and flag_on("learning_loop", user_id)`;
  - drop the `user_settings.learning_loop_beta` column, which has never been applied outside local dev.
- The comment also gives the frontend `useFlag("learning_loop")` for any UI gating.

### 6.3 `product_analytics` (#677/#675)

- **Backend:** the PostHog worker (`posthog_client._deliver`) also requires `flag_on("product_analytics", actor)` before sending. It's cached, runs on the worker thread, and fails closed.
- **Frontend:** analytics starts only if `useFlag("product_analytics") === "on"`, on top of all the existing gates.
- **Seed:** the migration seeds default `on`, so behaviour is unchanged until an admin flips it.
- **Unchanged:** the per-student opt-out, DNT/GPC handling and `POSTHOG_DISABLED` all still apply.

## 7. Frontend

- **`lib/flags.ts`** holds the fetch and types. `context/FlagsContext.tsx` is a provider inside `UserProvider`:
  - it fetches `GET /api/flags` via `fetchJSON` once per page load, after auth resolves;
  - it re-fetches on user switch, with a generation guard;
  - it skips the fetch on public, `/auth` and onboarding routes, using `lib/appRoutes.ts`.
- **`useFlag(key): string`** returns the off variant until loaded, and on error. There's no flash-on.
- **Admin UI:** a new "Feature flags" tab in `components/screens/Admin.tsx` (`screens/admin/FeatureFlags.tsx`) containing:
  - **the list:** key, description, default, rollout, rule counts, last change;
  - **the editor:** a default picker, a rollout slider with its variant, and a rules table with user search and a role dropdown;
  - **the "check a student" explain box**;
  - **a confirm dialog** before a default or rollout change, stating the scope.
  - Test ids follow `docs/frontend-testids.md`.

## 8. Testing

- **Resolver unit tests:**
  - every resolution step and its precedence;
  - role priority and ties;
  - hash stability, and a monotonic rollout (raising the percentage keeps earlier members);
  - an unknown or invalid stored variant, and an unregistered key;
  - a snapshot read failure fails closed and isn't cached;
  - an env override, valid and invalid;
  - legacy `SAPLING_DECISIONS_BACKEND` precedence;
  - cache clear on write.
- **Route tests:**
  - admin endpoints behind `require_admin` (non-admin gets 403);
  - validation (422s, 404s);
  - an audit row plus `flag.changed` on each write;
  - explain steps;
  - `/api/flags` returns only client-visible flags, and defaults for signed-out users.
- **Consumer tests:**
  - router variant → backend/shadow mapping, and no call when off;
  - the PostHog worker drops when `product_analytics` is off;
  - function mode is unaffected.
- **Frontend (vitest):**
  - `useFlag` returns off until loaded and on error;
  - the generation guard;
  - no fetch on public routes;
  - admin screen interactions: the confirm dialog and the explain box.
- **E2E:**
  - `db/seed_local_rich.py` seeds a known flag set;
  - a new Chapter 1 journey: an admin sets a user rule on a client-visible test flag in `/admin`, and that user sees the variant after a reload;
  - a raw-SQL oracle check in `e2e_oracles`: no stored variant is invalid for its registry flag.
- **Integration lane:** the migration replays from empty.

## 9. Rollout

1. Merge after the #676 → #675 stack.
2. The staging migration seeds `product_analytics=on`.
3. Admin sets `decision_router`: a role rule for Admin/Moderator = `jev`, then a percentage.
4. Railway `SAPLING_DECISIONS_*` values become unnecessary. If set, they still override the flag.

## 10. Docs

- ADR in `docs/decisions/` (next free number after 0028).
- A `CLAUDE.md` repo-map line for `services/feature_flags.py`, and a Conventions line: "gate unfinished features with `flag_on`/`useFlag`; flags are declared in the registry".
- `docs/architecture.md` gets a flags paragraph.
