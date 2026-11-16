"""Re-seal legacy (v1) 🔒 values as v2, bound to their cell (finding M13).

docs/security/encryption-aad-plan.md, phase 3. Every column in
`services.encryption.ENCRYPTED_COLUMNS` (except the key canary) is scanned;
each v1 value is opened with no associated data and re-sealed as
``enc2:<kid>:...`` under its binding (table, column, row key), exactly as the
app's own writers seal it, because both build the binding from the same
registry through `encryption.bind`.

Safe to run against a live app:

* Key guard first. `services.encryption_canary.verify_encryption_key()` must
  answer ``ok``; anything else aborts before a row is read. A wrong key would
  read every v1 value as undecryptable and every v2 value as tampered.
* Compare-and-swap. Each rewrite goes through the `encryption_aad_swap` SQL
  function (migration 20261116162200), which writes only if the cell still
  holds the value this run read (md5), so a concurrent write by the app is
  never overwritten; that row is retried on the next run.
* Idempotent and resumable. A v2 value under the active kid is skipped, rows
  are paged by primary key (keyset, never offsets), so an interrupted run is
  re-run as is (``--start-after`` skips ahead in a single column).
* Content-free output: counts per column, and primary keys for the rows that
  need a human (never a value).

The order (docs/security/encryption-aad-plan.md, "Rollout"): every instance of
the environment must already run the v2-capable readers and write v2
(``ENCRYPTION_WRITE_V2=on``) BEFORE ``--apply``; v2 values are unreadable to
older code.

Values that do not open as v1 are reported, not touched: legacy plaintext (run
``python -m db.backfill_encryption --apply`` first, which seals it), or
ciphertext under another key (the 2026-10-21 incident's leftovers). A v2 value
that does not open under its own binding is reported as ``v2_bad``: that is
tampering or a bug, and it is what an attacker's moved ciphertext looks like.

Usage (from backend/; reads .env):

    python -m db.backfill_encryption_aad                       # dry run: counts, writes nothing
    python -m db.backfill_encryption_aad --apply               # rewrite v1 -> v2
    python -m db.backfill_encryption_aad --apply --table messages --batch 500
    python -m db.backfill_encryption_aad --table notes --column body --start-after <id>

Staging / production:

    dotenv -f .env.staging run -- python -m db.backfill_encryption_aad
    dotenv -f .env.staging run -- python -m db.backfill_encryption_aad --apply

Exit status: 0 when every scanned cell is v2 that opens in place (after an
``--apply``: everything that could be rewritten was), 1 when anything else
remains (the dry run of a fully migrated environment exiting 0 is the gate for
turning legacy reads off), 2 when the key guard or the swap function refuses.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

import httpx

from db.connection import rpc, table
from services import encryption
from services.encryption import ACTIVE_KID, V2_PREFIX, ColumnSpec

SWAP_FN = "encryption_aad_swap"
DEFAULT_BATCH = 200
#: Primary keys listed per column and category before the list is truncated.
MAX_LISTED = 25


class Abort(RuntimeError):
    """Stop before (or instead of) writing; exit status 2."""


@dataclass
class ColumnReport:
    spec: ColumnSpec
    counts: Counter = field(default_factory=Counter)
    listed: dict[str, list[str]] = field(default_factory=dict)
    last_pk: str | None = None

    def note(self, kind: str, pk: str) -> None:
        self.counts[kind] += 1
        if kind in ("v2_bad", "undecryptable", "non_string", "no_key", "conflict"):
            ids = self.listed.setdefault(kind, [])
            if len(ids) < MAX_LISTED:
                ids.append(pk)

    @property
    def remaining(self) -> int:
        """Cells that are not (yet) v2 opening in place."""
        c = self.counts
        return (c["v1"] - c["rewritten"]) + c["v2_bad"] + c["v2_other_kid"] + \
            c["undecryptable"] + c["non_string"] + c["no_key"]


def _targets(tables: Iterable[str] | None, columns: Iterable[str] | None) -> list[ColumnSpec]:
    specs = [s for s in encryption.ENCRYPTED_COLUMNS if s.backfill]
    if tables:
        wanted = set(tables)
        unknown = wanted - {s.table for s in specs}
        if unknown:
            raise Abort(f"not a backfilled 🔒 table: {', '.join(sorted(unknown))}")
        specs = [s for s in specs if s.table in wanted]
    if columns:
        wanted_c = set(columns)
        specs = [s for s in specs if s.column in wanted_c]
        if not specs:
            raise Abort("no 🔒 column matches --column")
    return specs


def _pages(spec: ColumnSpec, batch: int, start_after: str | None) -> Iterator[list[dict]]:
    """Keyset pages of (pk, key columns, value) for non-null cells."""
    (pk,) = spec.pk
    cols = ",".join(dict.fromkeys([pk, *spec.key, spec.column]))
    last = start_after
    while True:
        filters = {spec.column: "not.is.null"}
        if last is not None:
            filters[pk] = f"gt.{last}"
        rows = table(spec.table).select(cols, filters=filters, order=f"{pk}.asc", limit=batch)
        rows = rows or []
        if rows:
            yield rows
        if len(rows) < batch:
            return
        last = str(rows[-1][pk])


def _open_v1(spec: ColumnSpec, value: str) -> bytes:
    """The plaintext bytes of a v1 value (raises when it is not one)."""
    if spec.kind == encryption.BYTES:
        return encryption.decrypt_bytes(value)
    return encryption.decrypt(value).encode("utf-8")


def _classify(spec: ColumnSpec, row: dict) -> tuple[str, bytes | None, encryption.Binding | None]:
    value = row.get(spec.column)
    try:
        binding = encryption.bind(spec.table, spec.column, row)
    except encryption.MissingRowKey:
        return "no_key", None, None
    if not isinstance(value, str):
        return "non_string", None, binding
    if value.startswith(V2_PREFIX):
        kid = value[len(V2_PREFIX):].partition(":")[0]
        try:
            encryption.decrypt(value, bind=binding) if spec.kind != encryption.BYTES \
                else encryption.decrypt_bytes(value, bind=binding)
        except encryption.BindingMismatch:
            return "v2_bad", None, binding
        return ("v2" if kid == ACTIVE_KID else "v2_other_kid"), None, binding
    try:
        return "v1", _open_v1(spec, value), binding
    except Exception:
        return "undecryptable", None, binding


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _swap(spec: ColumnSpec, pk_value: str, old: str, new: str) -> bool:
    (pk,) = spec.pk
    out = rpc(SWAP_FN, {
        "p_table": spec.table, "p_column": spec.column, "p_pk_column": pk,
        "p_pk": pk_value, "p_old_md5": _md5(old), "p_new": new,
    })
    if isinstance(out, list):
        out = out[0] if out else False
    return bool(out)


def backfill_column(
    spec: ColumnSpec, *, apply: bool, batch: int = DEFAULT_BATCH,
    start_after: str | None = None, max_rows: int | None = None,
    swap: Callable[[ColumnSpec, str, str, str], bool] = _swap,
    log: Callable[[str], None] = print,
) -> ColumnReport:
    report = ColumnReport(spec)
    (pk,) = spec.pk
    for rows in _pages(spec, batch, start_after):
        for row in rows:
            pk_value = str(row[pk])
            kind, plain, binding = _classify(spec, row)
            report.note(kind, pk_value)
            if kind != "v1" or not apply:
                continue
            if max_rows is not None and report.counts["rewritten"] >= max_rows:
                continue
            new = encryption._seal_v2(plain, binding)
            if swap(spec, pk_value, row[spec.column], new):
                report.counts["rewritten"] += 1
            else:
                report.note("conflict", pk_value)
        report.last_pk = str(rows[-1][pk])
        log(f"  {spec.table}.{spec.column}: through {pk}={report.last_pk} "
            f"({sum(v for k, v in report.counts.items() if k not in ('rewritten', 'conflict'))} scanned)")
    return report


def _key_guard() -> None:
    from services.encryption_canary import verify_encryption_key

    try:
        outcome = verify_encryption_key()
    except Exception as e:  # EncryptionKeyMismatch included
        raise Abort(f"key guard: {type(e).__name__}: {e}") from e
    if outcome != "ok":
        raise Abort(
            f"key guard: the canary check answered {outcome!r}, not 'ok'. Refusing to "
            "touch ciphertext without proof that ENCRYPTION_KEY belongs to this database."
        )


def _probe_swap() -> None:
    """Fail before scanning when the swap function is not deployed."""
    try:
        rpc(SWAP_FN, {
            "p_table": "encryption_key_check", "p_column": "canary", "p_pk_column": "id",
            "p_pk": "-1", "p_old_md5": "", "p_new": "",
        })
    except httpx.HTTPError as e:
        raise Abort(
            f"{SWAP_FN} is not callable ({type(e).__name__}); apply migrations first "
            "(python -m db.migrate) — migration 20261116162200_encryption_aad_swap.sql"
        ) from e


def _print_report(report: ColumnReport, apply: bool) -> None:
    s = report.spec
    c = report.counts
    print(f"── {s.table}.{s.column} (bound as "
          f"{s.aad_table or s.table}.{s.aad_column or s.column} by {'|'.join(s.key)})")
    print(f"  v2 ok: {c['v2']}   v1: {c['v1']}   "
          f"{'rewritten' if apply else 'would rewrite'}: {c['rewritten'] if apply else c['v1']}")
    for kind in ("conflict", "v2_bad", "v2_other_kid", "undecryptable", "non_string", "no_key"):
        if c[kind]:
            ids = report.listed.get(kind, [])
            more = "" if len(ids) >= c[kind] else f" (+{c[kind] - len(ids)} more)"
            print(f"  {kind}: {c[kind]}  {s.pk[0]}={', '.join(ids)}{more}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write. Without it, counts only.")
    parser.add_argument("--table", action="append", help="Restrict to a table. Repeatable.")
    parser.add_argument("--column", action="append", help="Restrict to a column. Repeatable.")
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH, help="Rows per page (<= 1000).")
    parser.add_argument("--start-after", help="Resume one column after this primary key.")
    parser.add_argument("--max-rows", type=int, help="Rewrite at most N cells per column (a canary run).")
    args = parser.parse_args(argv)

    if not 0 < args.batch <= 1000:
        print("--batch must be in 1..1000 (PostgREST max_rows)")
        return 2
    try:
        specs = _targets(args.table, args.column)
        if args.start_after and len(specs) != 1:
            raise Abort("--start-after needs exactly one column (--table and --column)")
        _key_guard()
        if args.apply:
            _probe_swap()
            if not encryption.write_v2_enabled():
                print("WARNING: ENCRYPTION_WRITE_V2 is not on in THIS environment. Every "
                      "deployed instance must run the v2 readers and write v2 before --apply.")
    except Abort as e:
        print(f"ABORT: {e}")
        return 2

    print(f"AAD backfill: {'APPLY (writing)' if args.apply else 'DRY RUN (no writes)'}; "
          f"{len(specs)} column(s)\n")
    remaining = 0
    for spec in specs:
        report = backfill_column(spec, apply=args.apply, batch=args.batch,
                                 start_after=args.start_after, max_rows=args.max_rows)
        _print_report(report, args.apply)
        remaining += report.remaining
        print()
    print(f"Cells not yet v2-in-place: {remaining}")
    if remaining and not args.apply:
        print("Re-run with --apply to rewrite v1. Other categories need a human (see above).")
    return 1 if remaining else 0


if __name__ == "__main__":
    sys.exit(main())
