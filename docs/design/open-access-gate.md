# Open access: the waitlist gate as a feature flag

Status: **built** (migration `20261116180157_open_access.sql`; code in
`backend/services/open_access.py` and the callers below).

## 1. Today

- **Domain gate.** `ALLOWED_EMAIL_DOMAINS` (env, default `bu.edu`) refuses any
  other Google account at sign-in (`routes/auth.py:283`, `invalid_domain`).
- **Waitlist gate.** `newsletter_emails` is the list: `approved_at` set =
  allowlisted, `NULL` = waitlisted. A new sign-in with no approved row gets no
  account and goes to `/pending` (`services/auth/signin.py:216`). Once in,
  access is `users.is_approved`, checked by the auth guard on every request
  (`services/auth_guard.py:263`) and read by the frontend middleware via `/me`.
- Every existing `users` row with `is_approved = false` is a **deliberate
  removal** (Admin → Users "Remove access", or an Allowlist revoke):
  unapproved sign-ins no longer create accounts.

## 2. Goal

An admin can lift the waitlist requirement and put it back, without touching
who is on the list. People who sign in while it is lifted are recorded on the
list. When it is put back, they are on the **waitlist**, not the allowlist.

## 3. Drop the domain gate

- Delete `ALLOWED_EMAIL_DOMAINS` (`config.py`), `_email_domain_allowed`, the
  `invalid_domain` refusal and its copy (`frontend/.../signInErrors.ts`),
  `tests/test_auth_domain.py`, and the env/doc lines (`.env.*.example`,
  README, `SECURITY.md`, `docs/local-supabase.md`, staging checklist,
  `docs/deploy/railway.md`, `tests/test_railway_worker_env.py`).
- A non-BU sign-in follows the same path as any unapproved one: no account,
  `/pending`, join the waitlist.
- **"Non-BU" label.** Display only, derived when the list is read
  (`newsletter_emails.email` is plaintext, ADR 0026), so no column.
  `SCHOOL_EMAIL_DOMAINS = ("bu.edu",)` in one place; a subdomain
  (`cs.bu.edu`) counts. Allowlist rows carry `school_email: bool`; the tab
  shows a **Non-BU** badge and a filter.

## 4. The flag

- Key **`open_access`**, variants `("off", "on")`; `on` = the waitlist
  requirement is lifted. Named so `off` (the fail-closed answer of an
  unreadable flag store) is the gated, safe side.
- **Global**: resolved with `user_id=None`, like `llm_fallback`. A new person
  has no id at sign-in, so user/role rules and rollouts do not apply.
- **Client-visible**, for the landing copy (§7). `/api/flags` already answers
  signed-out visitors.
- Kill switch: `SAPLING_FLAG_OPEN_ACCESS=off`. This replaces the incident
  runbook's `ALLOWED_EMAIL_DOMAINS=invalid.invalid` "refuse all new sign-ins"
  switch.

## 5. Access is computed, never migrated

Flipping the flag writes nothing. No `approved_at` or `is_approved` changes.

```
has_access(user) = not deleted AND (
      is_approved                                  -- admin-approved
   OR (open_access is on AND user.open_access_at IS NOT NULL)
)
```

- New column **`users.open_access_at TIMESTAMPTZ`**: "this account came in
  through the open gate". It is what tells an open-access entrant apart from
  a removed user (both have `is_approved = false`).
- Because access is computed, closing the gate works the same whether it is
  done in Admin → Flags or by the env kill switch.

## 6. Behaviour

### Signing in while `open_access` is on

| Who | Result |
| --- | --- |
| New person, any email domain (§9) | Account created, `is_approved = false`, `open_access_at = now`. A `newsletter_emails` row is added (or the existing one used) with `approved_at = NULL` and `joined_user_id` set; `joined_at` stays NULL (it means "joined as approved", stamped when an admin approves them). Gets in. |
| Already on the waitlist, never approved | Same: gets in, stamped `open_access_at`, row stays unapproved. |
| Already approved | Unchanged. |
| Removed by an admin (`is_approved = false`, no `open_access_at`) | **Kept out.** `/pending`, as today. A deliberate removal holds. |
| Deleted account | Refused, as today. |

### Closing the gate (`open_access` → off)

- Open-access entrants fail `has_access` on their next request (up to ~35 s:
  the guard's 30 s account-state cache plus ~5 s flag convergence). The
  middleware sends them to `/pending`.
- Their list row was never approved, so they are **on the waitlist**. Account
  and study data are kept.
- Approving them in the Allowlist sets `is_approved = true` and they are back
  in with their data. `open_access_at` stays as history.
- Opening the gate again lets earlier entrants back in automatically.

### Admin actions while the gate is open

- **Remove access** (Admin → Users) and **Allowlist revoke** also clear
  `open_access_at`, so the removal holds through the open gate.
- **Approve** works as today.

## 7. Surfaces

### Backend

- `services/auth/signin.py::record_google_sign_in`: the open-gate branch
  (§6), and drop the domain check from the callback.
- `services/auth_guard.py::_read_account_state`: read `open_access_at`,
  return `active` per `has_access`. The flag is read only for an unapproved
  account that carries the mark, and only on the account-state cache's miss
  path, which already runs off the event loop (`guard_off_loop`); the
  resolved state is cached with the row, so a flip lands within the 30 s TTL.
- `/api/auth/me` (`services/auth/accounts.py`): `is_approved` becomes the
  computed access (the middleware keeps working), plus
  `access: "approved" | "open" | "none"`.
- Every "approved users" query uses `has_access` instead of `is_approved`:
  the social directory (`services/social/directory.py`), Admin → Users
  (`services/users_search.py`), the admin overview counts
  (`services/admin/overview.py`) and email broadcast recipients
  (`routes/admin_email.py`).
- Admin → Email's "Waitlist, not yet approved" audience skips open-access
  entrants while the gate is open (they already use Sapling); "All users" is
  everyone with access.
- `services/admin/users.py::unapprove_user` and
  `services/admin/allowlist.py::revoke_allowlist` clear `open_access_at`.
- Allowlist rows gain `open_access` (the linked account's `open_access_at` is
  set) and `school_email`.

### Frontend

- **Admin → Allowlist:** a gate banner ("Open access is ON — anyone can sign
  in" / "Waitlist required") linking to the flag, the **Non-BU** badge and
  filter, and a row state **"Open access"**: "in" while open, "waiting —
  signed in during open access" while closed.
- **Landing / sign-in:** with `useFlag("open_access") === "on"`,
  BetaModal's "Join the Waitlist" CTA becomes "Sign up" and goes to Google
  sign-in. The waitlist copy shows when off. Remove "domain-gated" from
  `lib/landing/companionContent.ts`.

### Emails

- **Welcome** goes to an open-access entrant on their first sign-in (they got
  in).
- **"You're in"** is still sent only when an admin approves an address, and
  is skipped when that address is using Sapling through the open gate right
  now (gate open). With the gate closed an open-access entrant is back on
  `/pending`, so the approval is what lets them in and they get the email.

## 8. Build pieces

1. Migration: `users.open_access_at TIMESTAMPTZ` (timestamp-prefixed).
   Covered by the account wipe/purge/bundle rules (a column on `users`, not a
   new per-user table).
2. `REGISTRY` entry `open_access` (`client_visible=True`), plus a migration
   seeding its config row `off`.
3. Domain-gate removal (§3) and the Non-BU label.
4. Sign-in, guard, `/me`, the access queries, and the admin actions (§7).
5. Admin Allowlist UI, landing copy.
6. Docs: incident-response §3.3/§3.4 and the breach "presumably BU students"
   fact, SECURITY.md, README.
7. Tests:
   - the sign-in matrix (§6) × gate on/off
   - the guard on a gate flip
   - removal/revoke holding while open
   - the access queries
   - the Non-BU label
   - a Playwright journey: open → new sign-in gets in → close → `/pending` →
     approve → back in.

## 9. Decision: the open gate admits non-BU too

Decided 2026-11-16: **open means open.** With `open_access` on, anyone who
signs in with a verified Google account gets in, BU or not; a non-BU entrant
shows as "Open access · Non-BU" in the Allowlist, and goes back on the
waitlist like everyone else when the gate closes. The email domain is never
consulted by any access decision; it is a label only. Product note: the
course catalog is BU-only.
