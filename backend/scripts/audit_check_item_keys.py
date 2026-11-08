#!/usr/bin/env python3
"""The human audit of check-item answer keys (learning loop, spec §13 A124).

The independent solve (scripts/backfill_check_item_keys.py, and the write path)
is a model checking a model. This is the human measurement: staff judge a
stratified sample of a course's stored keys correct, wrong or ambiguous, and the
course's key-error rate is reported with a Wilson 95% interval — overall and by
the key's status when audited (verified by the solve, held, unverified). The
admin page /admin/check-items does the same over
GET /api/admin/check-items/audit/sample and POST /api/admin/check-items/{id}/audit;
this script is the offline twin for a reviewer working from a spreadsheet.

    python scripts/audit_check_item_keys.py sample --course <id> [--n 30] [--seed S] [--out audit.csv]
    python scripts/audit_check_item_keys.py record --course <id> --csv audit.csv [--auditor <user id>]
                                                   [--apply --project <ref>]
    python scripts/audit_check_item_keys.py report --course <id>

- `sample` draws the sample (learning/item_audit.py: format × difficulty ×
  concept) and prints ids, strata and key status only; with --out it writes a
  CSV for review WITH each item's decrypted question, options (the key marked)
  and final answer, plus an empty `verdict` column — item text leaves the
  database only into that file, which the reviewer must treat as course
  material (delete it when done).
- `record` reads the `id` and `verdict` (correct / wrong / ambiguous; blank =
  not judged) columns back. Dry run by default: prints what it would record.
  With --apply (and --project naming the connected project, else exit 2) each
  verdict is recorded as the admin route records it: "correct" confirms the
  key, "wrong" / "ambiguous" holds the item (never served until an approval or
  a later "correct"). An id outside --course, unknown, or an invalid verdict is
  refused (exit 1) and nothing of that row is written.
- `report` prints the course's audit summary.

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and check
the `Project:` line printed first. No model is called. Needs the ENCRYPTION_KEY
the rows were written under (for --out) and migration
20261108073631_learning_item_keys.sql applied.
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import SUPABASE_URL  # noqa: E402
from learning.item_audit import KEY_STATUSES, stratified_sample, summary  # noqa: E402
from learning.params import (  # noqa: E402
    ITEM_AUDIT_SAMPLE_DEFAULT,
    ITEM_AUDIT_SAMPLE_MAX,
    ITEM_AUDIT_VERDICTS,
)
from services.check_item_service import (  # noqa: E402
    audit_population,
    course_audit_rows,
    get_check_item,
    items_by_ids,
    key_status,
    record_item_audit,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
_SUPABASE_SUFFIX = ".supabase.co"
CSV_COLUMNS = (
    "id",
    "concept_key",
    "format",
    "difficulty",
    "key_status",
    "question",
    "options",
    "final_answer",
    "verdict",
)


def _project_ref() -> str:
    """The project SUPABASE_URL points at (scripts/backfill_check_items.py's rule)."""
    host = (urlparse(SUPABASE_URL).hostname or "").lower()
    if not host or host in _LOCAL_HOSTS:
        return "local"
    if host.endswith(_SUPABASE_SUFFIX):
        return host[: -len(_SUPABASE_SUFFIX)].split(".")[0]
    return host


def _pct(value) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _print_rate(label: str, counts: dict) -> None:
    rate = counts["key_error"]
    upper = counts["key_error_or_ambiguous"]
    print(
        f"  {label}: {counts['audited']} audited ({counts['correct']} correct, "
        f"{counts['wrong']} wrong, {counts['ambiguous']} ambiguous); key-error rate "
        f"{_pct(rate['rate'])} (95% CI {_pct(rate['ci_low'])}–{_pct(rate['ci_high'])}); "
        f"wrong or ambiguous {_pct(upper['rate'])} "
        f"(95% CI {_pct(upper['ci_low'])}–{_pct(upper['ci_high'])})"
    )


def cmd_sample(args) -> int:
    if not 1 <= args.n <= ITEM_AUDIT_SAMPLE_MAX:
        print(f"Refusing: --n must be 1..{ITEM_AUDIT_SAMPLE_MAX}")
        return 2
    seed = args.seed or args.course
    population = audit_population(args.course)
    sample = stratified_sample(population, args.n, seed=seed)
    strata = Counter((r.get("format"), r.get("difficulty")) for r in sample)
    print(f"  {len(sample)} of {len(population)} stored item(s) sampled (seed {seed!r})")
    for (fmt, level), n in sorted(strata.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0)):
        print(f"    {fmt} {level}: {n}")
    concepts = Counter(r.get("concept_key") for r in sample)
    print(f"    {len(concepts)} concept(s), at most {max(concepts.values(), default=0)} item(s) each")
    if not args.out:
        for row in sample:
            print(f"    {row['id']} {row.get('format')} {row.get('difficulty')} {key_status(row)}")
        return 0
    texts = {i.id: i for i in items_by_ids(r["id"] for r in sample)}
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in sample:
            item = texts.get(row["id"])
            options = " | ".join(
                f"{o.letter}. {o.text}{' (key)' if o.letter == item.correct_option else ''}"
                for o in (item.options or [])
            ) if item else ""
            writer.writerow(
                {
                    "id": row["id"],
                    "concept_key": row.get("concept_key"),
                    "format": row.get("format"),
                    "difficulty": row.get("difficulty"),
                    "key_status": key_status(row),
                    "question": item.prompt if item else "",
                    "options": options,
                    "final_answer": (item.final_answer or "") if item else "",
                    "verdict": "",
                }
            )
    print(f"  wrote {args.out} — it holds item text: delete it when the review is done")
    return 0


def cmd_record(args) -> int:
    connected = _project_ref()
    if args.apply and args.project != connected:
        print(
            f"Refusing: --apply needs --project {connected} (the connected project); got "
            f"{args.project!r}. Check the env file this run loaded."
        )
        return 2
    with open(args.csv, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)]
    planned: list[tuple] = []
    refused = 0
    for row in rows:
        verdict = (row.get("verdict") or "").strip().lower()
        if not verdict:
            continue  # not judged yet
        item = get_check_item((row.get("id") or "").strip(), include_held=True)
        if verdict not in ITEM_AUDIT_VERDICTS or item is None or item.course_id != args.course:
            refused += 1
            print(f"    refused {row.get('id')!r}: unknown item, another course, or verdict {verdict!r}")
            continue
        planned.append((item, verdict))
    counts = Counter(v for _, v in planned)
    print(
        f"  {len(planned)} verdict(s) to record ({', '.join(f'{v} {counts[v]}' for v in ITEM_AUDIT_VERDICTS)}), "
        f"{refused} refused" + (" — dry run" if not args.apply else "")
    )
    failed = 0
    if args.apply:
        for item, verdict in planned:
            try:
                record_item_audit(item, verdict, auditor=args.auditor)
            except Exception as exc:  # noqa: BLE001 — one failed row is reported, the rest still run
                failed += 1
                print(f"  record failed for {item.id}: {type(exc).__name__}")
        print(f"Done: {len(planned) - failed} recorded, {failed} failed")
    return 1 if failed or refused else 0


def cmd_report(args) -> int:
    out = summary(course_audit_rows(args.course))
    _print_rate("all", out)
    for status in KEY_STATUSES:
        _print_rate(status, out["by_key_status"][status])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The human audit of check-item keys (spec §13 A124).")
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample", help="Draw a stratified audit sample of a course's keys.")
    sample.add_argument("--course", required=True)
    sample.add_argument("--n", type=int, default=ITEM_AUDIT_SAMPLE_DEFAULT)
    sample.add_argument("--seed", help="Default: the course id (the same sample while items stay).")
    sample.add_argument("--out", help="Write a review CSV (holds item text) here.")
    record = sub.add_parser("record", help="Record verdicts from a reviewed CSV.")
    record.add_argument("--course", required=True)
    record.add_argument("--csv", required=True)
    record.add_argument("--auditor", help="The reviewing staff member's user id (users.id).")
    record.add_argument("--apply", action="store_true", help="Record (default: dry run).")
    record.add_argument("--project", help="With --apply: the Supabase project ref this run writes to.")
    report = sub.add_parser("report", help="Print the course's key-error rate.")
    report.add_argument("--course", required=True)
    args = parser.parse_args(argv)

    print(f"Project: {_project_ref()}")
    return {"sample": cmd_sample, "record": cmd_record, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
