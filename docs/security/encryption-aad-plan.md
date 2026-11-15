# Binding encrypted columns to their row (AES-GCM associated data)

Status: design, not started. No data is migrated by this document.
Owner of the code it describes: `backend/services/encryption.py`.

## Where we are

Every 🔒 column (the list is in the root `CLAUDE.md`, Gotchas) is written by
`services/encryption.py` as `base64(nonce || ciphertext || tag)` under one
AES-256-GCM key, `ENCRYPTION_KEY`. `encrypt` passes `None` as the associated
data (`encryption.py`, `_AESGCM.encrypt(nonce, ..., None)`), so a ciphertext
carries no record of where it belongs. Reads go through `decrypt_if_present`,
`decrypt_json`, `decrypt_numeric`, which **fail soft**: a value that does not
open comes back raw, with a WARNING, so legacy plaintext rows keep loading.

About 44 modules write through the helpers and about 190 call sites read
through them. `services/encryption_canary.py` refuses to boot a backend whose
key cannot open the database's one-row `encryption_key_check` canary.

## What the current format does not protect against

GCM authenticates the bytes, not their location. Anyone who can write to the
database without holding the key (a leaked service-role key, a PostgREST or
RLS hole, a SQL function bug, a hand-edited restore) can move ciphertext
around, and the backend will faithfully decrypt it in its new place:

| Attack | Example | Effect today |
|---|---|---|
| Cross-row move (confidentiality) | Copy user A's `messages.content` or `user_profiles.name` ciphertext into a row user B owns | The app decrypts it and serves A's plaintext to B, through B's own normal session |
| Cross-row swap (integrity) | Swap two users' Google OAuth token ciphertexts | Each account acts with the other's Google identity |
| Cross-row swap (integrity) | Move `assignments.points_earned` between enrollments, or `check_items.correct_option` between items | Grades or answer keys change with no key needed |
| Cross-column move | Move `notes.body` into `notes.title`, or `documents.extracted_text` of a private document into one that is indexed shared | Text surfaces where its owner never put it |
| Plaintext injection | Write plaintext into any 🔒 column | `decrypt_if_present` serves it as if it were genuine |

Associated data (AAD) closes the first four. With `table|column|row key`
bound into the tag, a ciphertext opened anywhere but its own cell fails
authentication. The fifth needs strict reads (phase 4 below), which only
become possible once no legacy value remains in a column.

Out of scope, recorded so nobody assumes otherwise: rolling a cell back to an
older ciphertext of the SAME cell (that needs a per-row version counter in the
AAD and a place to store it), and key custody (the key still sits in an env
var; a KMS is a separate decision).

## The binding

```
aad = b"sapling/enc/v2|" + table + b"|" + column + b"|" + row_key
```

* `table` and `column` are the physical names, fixed literals at each call
  site, never derived from request data.
* `row_key` is the row's primary key, as text. Where the primary key is
  composite, the key columns joined with `|` in a fixed order.
* The AAD is not stored. Reader and writer each rebuild it from the row they
  are touching, so a moved ciphertext meets the wrong AAD.

The constraint this imposes, and the main cost of the change: **the row key
must be known before encryption.** Inserts that let Postgres mint the id
(`DEFAULT gen_random_uuid()`, serials) have to mint it in Python first, as
`services/documents/persistence.py::_persist_document` already does. The
inventory step (phase 0) lists every 🔒 write and which kind it is. A table
whose rows cannot get an app-minted key binds to its owner instead
(`user_id`), which still stops cross-user moves but not moves inside one
user's rows; each such fallback is listed by name in the inventory.

Content-addressed ids (`course_chunks.id`, a hash of the plaintext) are known
before encryption and stay stable across the shared upsert, so the binding
holds when two uploaders dedupe onto one row.

Three things move ciphertext between rows today and must decrypt and
re-encrypt instead:

* SQL that copies a 🔒 column between rows or tables (the 0024 identity split
  moved names from `users` to `user_profiles` this way). Inventory with
  `grep -n` over `db/migrations` and the RPC bodies for every 🔒 column name;
  any future such migration becomes a Python backfill.
* `services/account_bundle.py` import, which re-keys rows on the target. It
  already decrypts on export (environments have different keys); it must
  re-encrypt with the TARGET row's binding on import.
* Anything that duplicates a row (a "copy" feature, a seeder cloning
  fixtures). The account seeder and `db/seed_local_rich.py` encrypt per row
  already; they gain the binding argument.

## A versioned envelope, so old and new coexist

```
v1 (today):  base64(nonce || ct || tag)                       no prefix, AAD None
v2:          "enc2:" kid ":" base64(nonce || ct || tag)       AAD = binding above
```

The base64 alphabet has no `:`, so `enc2:` can never begin a v1 value, and the
reader dispatches on the prefix alone. `kid` is a short key id (see rotation).
A legacy plaintext value that happens to start with `enc2:` fails to open and
takes the same soft fallback any undecryptable value takes today.

API shape (one module, no call site guesses the format):

```python
@dataclass(frozen=True)
class Binding:
    table: str
    column: str
    row_key: str

encrypt(value, *, bind: Binding | None = None) -> str     # v2 when bind is given
decrypt(value, *, bind: Binding | None = None) -> str     # dispatches v1 / v2
```

* v2 value, `bind` given: open with the kid's key and the AAD. Failure is a
  **hard** failure (raise in `decrypt`; in `decrypt_if_present`, return `None`
  and emit `encryption.binding_mismatch`, never the raw ciphertext). A v2
  value that does not open in this cell is tampering or a bug, not legacy data.
* v2 value, no `bind`: hard failure. A reader that has not been threaded
  through must not be able to open v2 data by accident.
* v1 value: today's path, AAD `None`, today's soft fallback, until phase 4.

The JSON pair, `decrypt_numeric`, `encrypt_bytes` and the canary all ride the
same envelope.

## Rollout

Each phase ships alone and is reversible until the next starts.

**Phase 0: inventory.** One table in this doc's appendix (added with the
phase-1 PR): every 🔒 column, its write sites, its read sites, whether its row
key is known before insert, and any SQL or script that copies it. A test pins
the inventory to the helper call sites so a new 🔒 column cannot skip it.

**Phase 1: readers first.** Ship the v2-aware `decrypt` and the `Binding`
argument at every read site. Nothing writes v2 yet, so behaviour is identical;
the tests prove v2 round-trips, a moved v2 value fails, a v2 value read
without a binding fails, and every v1 value still reads. This must be live in
every environment (local, staging, production via `make promote`) before any
writer flips, because a reader that cannot open v2 would treat it as
undecryptable.

**Phase 2: writers, one table at a time.** A code-level allowlist
(`V2_TABLES`) in `encryption.py`; a PR adds a table and passes `bind=` at its
write sites. Rollback is reverting that PR: readers still open the v2 values
already written. Not a feature flag: the format must not vary per student,
and the allowlist is reviewed code.

**Phase 3: backfill.** `scripts/backfill_encryption_v2.py`, modelled on
`scripts/backfill_encrypt_chunk_text.py`:

* Dry run by default; `--apply` to write; `--table` to scope.
* Key guard first: call `services.encryption_canary.verify_encryption_key()`
  and abort on anything but `ok`. A wrong key turns "already v2, skip" checks
  into a silent double encryption, the same hazard that script documents.
* Per row: decrypt v1 (soft path), re-encrypt v2 with the row's binding, PATCH
  filtered on the OLD ciphertext (`column=eq.<old>`), so a concurrent write by
  the live app is never overwritten; a zero-row PATCH is retried next run.
* Idempotent: a value already `enc2:` with the active kid is skipped.
* Order: staging first, under `dotenv -f .env.staging run -- python ...`, then
  production after the promotion that shipped phase 2 for that table
  (`backend/promotion/README.md`). The promotion's `pg_dump` covers schema
  changes; a data backfill is not a migration, so take the README's manual
  `pg_dump -Fc` ("Backups") immediately before `--apply` on production.
* Report: rows rewritten, rows skipped, rows that did not decrypt under v1
  (legacy plaintext, listed by id only, never content).

Verification: `e2e_oracles`' `ciphertext` judge learns that a migrated column
must hold `enc2:` values; a read-only `--count` mode of the backfill prints v1
remaining per column and is the gate for phase 4.

**Phase 4: strict reads, per column.** When a column's v1 count is zero in
every environment, its reads stop accepting v1 and plaintext: a value without
the `enc2:` prefix is refused like a mismatched one. This is what closes
plaintext injection. Columns that knowingly hold legacy plaintext stay soft and
are named in the inventory with the reason.

## Key rotation

Today rotation is offline: re-encrypt every 🔒 column under the new key, then
delete the canary row (`encryption_canary.py` docstring). The `kid` in the v2
envelope makes it online:

* `ENCRYPTION_KEYS` holds `kid:hex` pairs; `ENCRYPTION_ACTIVE_KID` names the
  one `encrypt` uses. `ENCRYPTION_KEY` keeps working as the single key with
  kid `0`, and every v1 value is read as kid `0`.
* The canary becomes one row per kid (a migration adds `kid` to
  `encryption_key_check`). Boot verifies every configured key against its own
  canary, seeds a canary for a new kid, and refuses to boot when the active
  kid is missing, so a half-configured rotation fails loudly instead of
  writing values another process cannot read.
* Rotate: add the new key to `ENCRYPTION_KEYS` everywhere (readers can open
  it); flip `ENCRYPTION_ACTIVE_KID`; run the phase-3 backfill, which rewrites
  any value whose kid is not active; confirm the count of old-kid values is
  zero; remove the old key and its canary row.
* Every environment keeps its own keys, as now. `account_bundle` and any other
  cross-environment copy decrypt on the way out and encrypt (with the target's
  active kid and binding) on the way in.

## Tests the implementation must carry

* Round trip per helper (`encrypt`/`decrypt`, JSON pair, numeric, bytes) with
  a binding.
* A v2 value fails under a different table, column or row key, and without a
  binding; `decrypt_if_present` returns `None` for it, never the ciphertext.
* Every v1 value written by today's code still reads, with and without a
  binding, until phase 4.
* Prefix dispatch: no v1 output (base64) can begin with `enc2:`.
* Keyring: a value under kid `a` opens after the active kid moves to `b`; a
  value under an unknown kid fails hard; boot refuses a missing active kid.
* The backfill: dry run writes nothing; the canary guard aborts on a wrong
  key; the old-value filter leaves a concurrently updated row alone; a second
  run is a no-op.
