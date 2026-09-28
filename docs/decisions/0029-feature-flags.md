# 0029: Feature flags — code registry + DB configuration, fail-closed

- Status: accepted
- Date: 2026-09-28
- Relates to: #620 (this epic), #673 (the AI learning loop, whose in-flight
  `user_settings.learning_loop_beta` column this decision replaces),
  ADR 0027 (the typed decision seam, whose `decision_router` variants this
  flag now drives), ADR 0028 (PostHog, whose capture is now gated by
  `product_analytics`)
- Supersedes: none

## Context

Every toggle in this codebase so far has been an env var (`SAPLING_DECISIONS_BACKEND`,
`INDEX_SWEEPER_ENABLED`, …) or a one-off `user_settings` column
(`share_class_context`, and #673's proposed `learning_loop_beta`). Both have
the same failure mode: changing them needs a redeploy (env vars) or a
migration (a column), so there is no way to flip a feature on for one
student, roll it out by percentage, or turn it off mid-incident without
touching the deploy pipeline. #673 was about to add a second bespoke
`user_settings` boolean for exactly this need; #620 asks for a general
mechanism instead, before that pattern repeats a third time.

## Decision

1. **A code registry plus DB configuration.** A flag is declared once, in
   code, as a `FlagDef` in `backend/services/feature_flags.py::REGISTRY`
   (key, ordered variants, description, `client_visible`). Its
   *configuration* — default variant, percentage rollout, and per-user/role
   rules — lives in two tables, `feature_flags` and `feature_flag_targets`
   (migration `20260928022711_feature_flags.sql`), edited from `/admin`
   through `routes/admin_flags.py` (`GET/PATCH /api/admin/flags`,
   `PUT`/`DELETE .../targets`). The DB never validates variant membership;
   the app does (`REGISTRY` is the only source of truth for what a flag's
   values can be), so a variant typo is rejected at the API boundary
   (422) rather than stored.
2. **Resolution order, first match wins** (`feature_flags.explain`):
   `SAPLING_FLAG_<KEY>` env override → fail-closed (unregistered flag,
   unreadable store, or an invalid stored/env value) → a per-user target row
   → a per-role target row (highest `roles.display_priority`, then lowest
   role id, so a student who holds two matching roles gets a single
   deterministic answer) → a stable percentage rollout (`sha256(key:user_id)`
   bucketed 0.00–99.99, so raising the percentage only ever adds users) →
   the stored default. A flag with no row at all resolves to `variants[0]`.
3. **Fail-closed, always to `variants[0]`.** `variants[0]` is a contract, not
   a convention the app happens to follow: every unregistered flag, every
   value that isn't one of the flag's own variants (stored or from the env),
   and any exception reading the DB (a network blip, a missing table) all
   collapse to `variants[0]` — which every registry entry defines as `"off"`.
   There is no separate "unknown" state a caller has to handle. The **admin
   API is the deliberate exception**: `list_flags`/`update_flag`/
   `upsert_target`/`delete_target` call the uncached `read_config()` directly
   and let a DB failure raise into a 500, rather than showing an admin a
   healthy-looking "off" for a store that is actually down. Fail-closed is a
   promise to the *student-facing* resolution path; it would be actively
   misleading for the page whose job is to diagnose that same store.
4. **A 30 s per-process snapshot cache, cleared on every write.**
   `_get_snapshot` holds one `(flags, targets)` snapshot per process for
   30 s (`FEATURE_FLAGS_SNAPSHOT_TTL_S`); every admin mutation calls
   `clear_feature_flags_cache()` (the #98 pattern) so the writer's own
   process sees its change immediately. Each clear bumps a generation, and a
   read that was already in flight when it landed returns its answer but
   does not cache it, so a write can't be papered over by a stale fill. Other
   replicas still serve the old snapshot for up to 30 s — accepted
   staleness, not a bug (§ Consequences). User-role membership is cached
   separately for 60 s (`FEATURE_FLAGS_ROLES_TTL_S`; `clear_user_roles_cache`
   on assign/revoke for that user, and for everyone on a role update or
   delete, since `display_priority` rides in the cached tuple). Both TTLs
   are read at call time and `0` means "always read the DB".
5. **No PostHog flags.** PostHog ships its own flag product; we don't use
   it here. Two reasons: privacy (a flag evaluation is itself an event, and
   student cohort membership by flag is exactly the kind of profiling ADR
   0028 goes out of its way to avoid sending) and decoupling (`product_analytics`
   is the flag that turns PostHog *on*, so PostHog cannot be the thing that
   decides whether PostHog runs).
6. **No Canopy in v1.** Canopy issue/roadmap state is not wired to flag
   values (no ticket-status-driven rollout, no flag read from a Canopy doc).
   Flags are operated exclusively from `/admin`; revisit only if a real
   workflow needs it.
7. **The three first flags**, all declared in `REGISTRY` today:
   - `decision_router` (`off` | `jev` | `jev_shadow`, not client-visible) —
     the tutor turn router's backend (ADR 0027). Replaces
     `SAPLING_DECISIONS_BACKEND` as the *normal* way to turn Jev on for a
     cohort; the env var still exists as a layer above the flag (§
     Consequences).
   - `learning_loop` (`off` | `on`, client-visible) — #673's AI learning
     loop, gated by `flag_on("learning_loop", user_id)` instead of a
     `user_settings` column (see the #673 follow-up comment).
   - `product_analytics` (`off` | `on`, client-visible) — gates PostHog
     capture end to end, backend (`posthog_client._deliver`, re-checked on
     the worker thread, right beside the existing consent check) and
     frontend (`FlagsProvider` calls `setProductAnalyticsFlag` from the same
     `GET /api/flags` response that feeds `useFlag`). Seeded `on` by the
     migration itself (`INSERT ... ON CONFLICT DO NOTHING`), so PostHog
     stays on by default wherever it was already on before flags existed;
     an admin can switch it off per-student, by role, or globally without a
     deploy.
8. **The admin confirm step states the scope of the change.** Saving a
   default/rollout change in the Feature Flags admin tab goes through the
   repo's existing two-click `useConfirm` (no new confirmation component),
   with the confirm body naming the concrete before → after transition and
   who it applies to, e.g. *"Default off → on; rollout 0% → 20% on.
   Applies to every student without a user or role rule."* — because a flag
   change is a blast-radius action with no undo button beyond another
   change, and "Save" alone doesn't say what it's about to do.
9. **The flag tables are not in the E2E truncate denylist.** Unlike the
   migration-seeded reference tables (`roles`, `terms`, …),
   `feature_flags`/`feature_flag_targets` ARE wiped by the per-test
   `TRUNCATE ... RESTART IDENTITY CASCADE` (both
   `backend/tests/integration/conftest.py::_TRUNCATE_DENYLIST` and
   `frontend/e2e/support/db.ts::TRUNCATE_DENYLIST` omit them on purpose).
   They are restored instead: `db/seed_local_rich.py::seed_feature_flags`
   re-upserts the `product_analytics=on` baseline after every reset. The
   reset writes the DB directly, so it cannot clear the backend's
   per-process snapshot or roles cache: on its own it would leave the
   backend answering from the previous journey's rules for up to 30 s (and a
   retried `feature-flags.spec.ts` would fail its "off" baseline).
   `scripts/e2e-up.sh` therefore exports `FEATURE_FLAGS_SNAPSHOT_TTL_S=0`
   and `FEATURE_FLAGS_ROLES_TTL_S=0`, so the E2E backend resolves every flag
   from the DB. Together that keeps flag state reproducible per test while
   still exercising the exact fail-closed path a genuinely empty table would
   hit, rather than special casing the tables as immutable fixtures.

## Consequences

- **Up to 30 s of staleness on other replicas.** An admin's change is live
  on the process that made it immediately, but a different backend replica
  can keep answering with the old variant for up to the snapshot TTL. This
  is judged acceptable for the kind of change flags gate here (rollouts,
  kill switches for non-critical paths); nothing time-sensitive should be
  built assuming sub-second propagation.
- **New flags need a registry line**, not just a database row — a row for
  an unregistered key is inert (the admin API 404s it; `explain` never sees
  a key it doesn't have a `FlagDef` for). This is deliberate friction: a
  flag's variants and client-visibility are a code-review-able contract, not
  something an admin can invent from the UI.
- **`SAPLING_DECISIONS_*` becomes an optional override, not the primary
  switch.** `services/decisions.py::router_backends` still checks
  `SAPLING_DECISIONS_BACKEND` (and function mode) first, and when either is
  set it keeps the old fully env-driven behavior (`configured_backend()` /
  `shadow_backend()`) — this is what keeps the E2E lane's `function` value
  and an operator's emergency override working unchanged. Only when
  `SAPLING_DECISIONS_BACKEND` is unset does `decision_router`'s flag
  resolution run. The env var therefore now sits *above* the flag rather
  than being the only lever; day-to-day rollout should use the flag, and the
  env var should be reserved for the E2E seam and genuine incidents.
- **Analytics now needs `product_analytics=on` in addition to the existing
  ADR 0028 gates** (a project token, consent, no DNT/GPC, not a test/E2E
  run). The migration seeds it `on` so this is a no-op for existing
  deployments; a fresh environment that never runs the migration's seed row
  (or whose row is later deleted) fails closed to no analytics, matching the
  rest of the system's default-off posture.
