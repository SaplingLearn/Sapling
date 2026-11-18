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

Nested ciphertexts too (PR #866 C6). `encryption.NESTED_CIPHERTEXTS` names
values sealed INSIDE a plaintext JSONB column — the learning loop's goal text
and grade checkpoints in ``loop_state`` — bound with `encryption.nested_bind`
to their session. Each is scanned wherever its path sits in the document, in
every table that holds one (`NESTED_HOLDERS`: the materialised
``sessions.loop_state`` and a lazy session's ``tutor_pending_sessions.loop_state``),
and re-sealed in place through `encryption_aad_swap_nested` (migration
20261118195701): a compare-and-swap on that one value, which leaves the rest of
the document as it stands and bumps ``loop_state_rev`` so a turn that read
the old document re-applies to the new one. Select one with
``--column loop_state`` (both paths) or ``--column 'loop_state#grade_checkpoint'``.

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
#: Migration 20261118195701: the in-document twin of SWAP_FN.
SWAP_NESTED_FN = "encryption_aad_swap_nested"
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


#: Where each `encryption.NESTED_CIPHERTEXTS` (table, column) is stored, as
#: (holder table, its primary key — also the value's row key). A lazy loop
#: session's document waits in tutor_pending_sessions under the same session
#: id until materialize_tutor_session copies it into sessions by SQL; its
#: values are bound to the session, so both copies open in place.
NESTED_HOLDERS: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    ("sessions", "loop_state"): (("sessions", "id"), ("tutor_pending_sessions", "session_id")),
}


@dataclass(frozen=True)
class NestedSpec:
    """One `encryption.NESTED_CIPHERTEXTS` path in one holder table: the
    attributes `_print_report` and the CLI filters read, like a ColumnSpec."""

    table: str  # the holder scanned
    column: str  # its JSONB column
    path: str  # the registry path, e.g. "goal.text_encrypted"
    pk: tuple[str, ...]
    bound_table: str  # the (table, column) the binding names
    bound_column: str
    kind: str = encryption.TEXT

    @property
    def key(self) -> tuple[str, ...]:
        return self.pk

    @property
    def aad_table(self) -> str:
        return self.bound_table

    @property
    def aad_column(self) -> str:
        return f"{self.bound_column}#{self.path}"

    @property
    def name(self) -> str:
        return f"{self.column}#{self.path}"


def nested_specs() -> list[NestedSpec]:
    """Every nested path in every holder, in a stable order."""
    out = []
    for bound_table, bound_column, path in sorted(encryption.NESTED_CIPHERTEXTS):
        for holder, pk in NESTED_HOLDERS[(bound_table, bound_column)]:
            out.append(NestedSpec(holder, bound_column, path, (pk,), bound_table, bound_column))
    return out


Target = ColumnSpec | NestedSpec


def _targets(tables: Iterable[str] | None, columns: Iterable[str] | None) -> list[Target]:
    specs: list[Target] = [s for s in encryption.ENCRYPTED_COLUMNS if s.backfill]
    specs += nested_specs()
    if tables:
        wanted = set(tables)
        unknown = wanted - {s.table for s in specs}
        if unknown:
            raise Abort(f"not a backfilled 🔒 table: {', '.join(sorted(unknown))}")
        specs = [s for s in specs if s.table in wanted]
    if columns:
        wanted_c = set(columns)
        specs = [s for s in specs
                 if s.column in wanted_c or (isinstance(s, NestedSpec) and s.name in wanted_c)]
        if not specs:
            raise Abort("no 🔒 column matches --column")
    return specs


def _pages(
    spec: Target, batch: int, start_after: str | None, *, filter_: str = "not.is.null",
) -> Iterator[list[dict]]:
    """Keyset pages of (pk, key columns, value) for non-null cells (a nested
    path's holder: non-empty documents)."""
    (pk,) = spec.pk
    cols = ",".join(dict.fromkeys([pk, *spec.key, spec.column]))
    last = start_after
    while True:
        filters = {spec.column: filter_}
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
    return _classify_value(spec, value, binding)


def _classify_value(
    spec: Target, value, binding: encryption.Binding,
) -> tuple[str, bytes | None, encryption.Binding | None]:
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


def _nested_values(doc, segments: tuple[str, ...], at: tuple[str, ...] = ()):
    """(JSON path, value) of every value at a key path ending in `segments`,
    wherever it sits in `doc` (a step's checkpoint is under steps.<hash>, the
    probe's under probe.current) — the walk account_bundle's NESTED_ENCRYPTED
    makes. Lists are not descended: no loop document keeps one of these
    values in a list, and a list index is no stable path to swap at."""
    if not isinstance(doc, dict):
        return
    for key, value in doc.items():
        here = (*at, str(key))
        if here[-len(segments):] == segments and value is not None:
            yield here, value
        else:
            yield from _nested_values(value, segments, here)


def _swap_nested(spec: NestedSpec, pk_value: str, path: tuple[str, ...], old: str, new: str) -> bool:
    out = rpc(SWAP_NESTED_FN, {
        "p_table": spec.table, "p_pk": pk_value, "p_path": list(path),
        "p_old_md5": _md5(old), "p_new": new,
    })
    if isinstance(out, list):
        out = out[0] if out else False
    return bool(out)


def backfill_nested(
    spec: NestedSpec, *, apply: bool, batch: int = DEFAULT_BATCH,
    start_after: str | None = None, max_rows: int | None = None,
    swap: Callable[[NestedSpec, str, tuple[str, ...], str, str], bool] = _swap_nested,
    log: Callable[[str], None] = print,
) -> ColumnReport:
    """`backfill_column` for one nested path: every value at it, in every
    row's document, classified under its `nested_bind` binding and (with
    `apply`) re-sealed in place. Counts are per value, not per row."""
    report = ColumnReport(spec)  # type: ignore[arg-type]  # NestedSpec reads as a ColumnSpec
    (pk,) = spec.pk
    segments = tuple(spec.path.split("."))
    for rows in _pages(spec, batch, start_after, filter_="neq.{}"):
        for row in rows:
            pk_value = str(row[pk])
            for path, value in _nested_values(row.get(spec.column), segments):
                try:
                    binding = encryption.nested_bind(
                        spec.bound_table, spec.bound_column, spec.path, row.get(pk))
                except encryption.MissingRowKey:
                    report.note("no_key", pk_value)
                    continue
                kind, plain, binding = _classify_value(spec, value, binding)
                report.note(kind, pk_value)
                if kind != "v1" or not apply:
                    continue
                if max_rows is not None and report.counts["rewritten"] >= max_rows:
                    continue
                new = encryption._seal_v2(plain, binding)
                if swap(spec, pk_value, path, value, new):
                    report.counts["rewritten"] += 1
                else:
                    report.note("conflict", pk_value)
        report.last_pk = str(rows[-1][pk])
        log(f"  {spec.table}.{spec.name}: through {pk}={report.last_pk} "
            f"({sum(v for k, v in report.counts.items() if k not in ('rewritten', 'conflict'))} scanned)")
    return report


def _key_guard() -> None:
    from services.encryption_canary import verify_encryption_key

    try:
        # seed=False: a backfill must never plant its own key's canary
        # (services/encryption_canary.py::require_key_for_write).
        outcome = verify_encryption_key(seed=False)
    except Exception as e:  # EncryptionKeyMismatch included
        raise Abort(f"key guard: {type(e).__name__}: {e}") from e
    if outcome != "ok":
        raise Abort(
            f"key guard: the canary check answered {outcome!r}, not 'ok'. Refusing to "
            "touch ciphertext without proof that ENCRYPTION_KEY belongs to this database."
        )


def _probe_swap(*, nested: bool = False) -> None:
    """Fail before scanning when a swap function the run needs is not
    deployed (each probe names a row that does not exist: nothing changes)."""
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
    if not nested:
        return
    try:
        rpc(SWAP_NESTED_FN, {
            "p_table": "sessions", "p_pk": "", "p_path": ["goal", "text_encrypted"],
            "p_old_md5": "", "p_new": "",
        })
    except httpx.HTTPError as e:
        raise Abort(
            f"{SWAP_NESTED_FN} is not callable ({type(e).__name__}); apply migrations first "
            "(python -m db.migrate) — migration 20261118195701_encryption_aad_swap_nested.sql"
        ) from e


def _print_report(report: ColumnReport, apply: bool) -> None:
    s = report.spec
    c = report.counts
    print(f"── {s.table}.{getattr(s, 'name', s.column)} (bound as "
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
            _probe_swap(nested=any(isinstance(s, NestedSpec) for s in specs))
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
        run = backfill_nested if isinstance(spec, NestedSpec) else backfill_column
        report = run(spec, apply=args.apply, batch=args.batch,  # type: ignore[arg-type]
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
