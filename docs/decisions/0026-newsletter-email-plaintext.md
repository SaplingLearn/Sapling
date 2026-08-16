# 0026: `newsletter_emails.email` stays plaintext, deliberately

- Status: accepted
- Date: 2026-08-05
- Relates to: #519 (this decision), #522 (encryption-coverage epic),
  ADR 0025 (chunk_text — the sibling decision), #231 (bucket lockdown)
- Supersedes: none

## Context

`users.email` is encrypted; `newsletter_emails.email` is not (#519). Same data
type, different answer, and nothing wrote down why. The table is 4 rows in
production and doubles as the beta-allowlist workflow: `routes/newsletter.py:27`
upserts on `email` at subscribe, and `routes/admin.py` lists/approves/revokes
by email value (`/api/admin/allowlist`).

`services/encryption.py` is AES-256-GCM with a fresh random nonce per call —
the same address never encrypts to the same bytes. Naive encryption therefore
breaks this table's `UNIQUE(email)` constraint, its lookup index, and both
upserts' conflict detection, silently converting dedupe into duplicate rows.

## Options considered

1. **Deterministic lookup column** — add `email_hash TEXT UNIQUE`
   (HMAC-SHA256 of the normalised address, key derived from `ENCRYPTION_KEY`),
   move the constraint/index/conflict targets to it, encrypt `email`.
   Preserves everything; costs a migration, a key-derivation seam, a rewrite
   of two routes, and a backfill.
2. **Leave plaintext, record the decision** (chosen).
3. **Stop storing it** — hand subscription to the newsletter sender.
   Rejected outright: it kills the admin allowlist workflow.

## Decision

Option 2. A subscription/allowlist address with no other user data attached is
the lowest-sensitivity personal field in the schema; the operational value of
a value-keyed UNIQUE table (dedupe, dashboard readability, trivial upserts) is
high; and the HMAC machinery of option 1 buys little at this sensitivity for a
4-row table. If this table ever grows richer user data or the beta gate is
retired, revisit option 1.

## Consequences

- `newsletter_emails.email` is an **intentional exception**, listed in
  CLAUDE.md next to the encrypted-columns gotcha, so the gap is not re-filed.
- The `users.email` inconsistency is now documented rather than silent, which
  is what #519 actually asked for.
- The e2e ciphertext oracle deliberately does NOT cover this column.
