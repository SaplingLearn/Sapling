#!/usr/bin/env python3
"""Accuracy check for a BU catalog scrape.

Two passes over `data/bu_catalog_fall_2026.json`:

1. **Structural** — offline sanity checks on the whole file: duplicate course
   codes, malformed codes, missing titles, implausible credits, boilerplate that
   leaked into descriptions, the distribution of `semester_offered`, and the
   per-section layer (#280) the offering import consumes — section codes,
   instructor/meeting/location coverage, and placeholder instructors.

2. **Live spot-check** — re-fetches a random sample of course pages and re-parses
   them with the same parser, comparing field by field. This catches silent
   parser drift (the class of bug that left `semester_offered` empty on every
   record of the previous scrape) and confirms the stored data matches bu.edu
   *now*.

Run (from `backend/`):

    python scripts/verify_catalog_scrape.py                 # structural + 25 live samples
    python scripts/verify_catalog_scrape.py --sample 60
    python scripts/verify_catalog_scrape.py --sample 0      # structural only, no network
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

from scrape_bu_catalog import HEADERS, parse_course  # noqa: E402

CATALOG_FILE = BACKEND_DIR / "data" / "bu_catalog_fall_2026.json"
CODE_RE = re.compile(r"^[A-Z]{2,4}\s+[A-Z]{1,4}\s+[A-Z]?\d{3}[A-Z]?$")
BOILER_RE = re.compile(r"accredited|javascript|cookie|copyright|privacy|terms of use", re.I)
SPOT_DELAY = 1.5   # seconds between spot-check fetches


def structural(catalog: list[dict]) -> int:
    """Offline checks. Returns the number of problems worth looking at."""
    print(f"=== structural — {len(catalog):,} records ===")
    problems = 0

    codes = [c.get("course_code", "") for c in catalog]
    dupes = {c for c in codes if codes.count(c) > 1} if len(codes) < 3000 else None
    if dupes is None:
        seen, dupes = set(), set()
        for c in codes:
            (dupes if c in seen else seen).add(c)
    if dupes:
        # Expected: BU cross-lists CAS graduate courses under GRS, so the same code
        # appears under two school slugs. Verified 2026-07-31 that all 436 dupes were
        # cross-school (0 same-school), i.e. real cross-listings, not a parser fault.
        # Same-school duplicates WOULD be a bug — the listing walk revisiting a page.
        by_school: dict[str, set[str]] = {}
        for c in catalog:
            by_school.setdefault(c.get("course_code", ""), set()).add(c.get("school", ""))
        same = [c for c in dupes if len(by_school.get(c, set())) == 1]
        print(f"  [warn] {len(dupes):,} duplicate course_codes ({len(same):,} same-school)")
        print(f"         e.g. {sorted(dupes)[:5]}")
        if same:
            problems += len(same)
            print(f"  [FAIL] same-school duplicates suggest a double-crawl: {same[:5]}")

    malformed = [c for c in codes if c and not CODE_RE.match(c)]
    if malformed:
        problems += len(malformed)
        print(f"  [FAIL] {len(malformed):,} malformed course_codes")
        print(f"         e.g. {malformed[:5]}")

    for field, label in (("title", "titles"), ("course_code", "codes")):
        missing = sum(1 for c in catalog if not c.get(field))
        if missing:
            problems += missing
            print(f"  [FAIL] {missing:,} missing {label}")

    # Upper bound is 40, not the ~4-8 of a typical course: SDM postgraduate clinical
    # courses really are listed at 30 units (verified against bu.edu 2026-07-31).
    bad_credits = [
        c["course_code"] for c in catalog
        if c.get("credits") is not None and not (0 <= c["credits"] <= 40)
    ]
    if bad_credits:
        problems += len(bad_credits)
        print(f"  [FAIL] {len(bad_credits):,} implausible credits: {bad_credits[:5]}")

    leaked = [c["course_code"] for c in catalog if BOILER_RE.search(c.get("description") or "")]
    if leaked:
        print(f"  [warn] {len(leaked):,} descriptions may contain boilerplate: {leaked[:3]}")

    # Coverage — these are informational, not failures.
    n = len(catalog) or 1
    for field in ("description", "credits", "instructors", "semester_offered", "sections"):
        have = sum(1 for c in catalog if c.get(field))
        print(f"  coverage {field:18} {have:6,}/{n:,}  ({100*have//n}%)")

    sems: dict[str, int] = {}
    for c in catalog:
        for s in c.get("semester_offered") or []:
            sems[s] = sems.get(s, 0) + 1
    print(f"  semester_offered values: {sorted(sems.items(), key=lambda x: -x[1])}")
    if not sems:
        problems += 1
        print("  [FAIL] no semester data at all — the schedule parser is broken again")

    problems += _sections(catalog)
    return problems


def _sections(catalog: list[dict]) -> int:
    """Checks on the per-section operational layer the importer consumes (#280).

    This is the half of the scrape that fails *silently*: a parser regression here
    yields a plausible-looking file whose `sections` are empty, and the import then
    writes nothing while reporting success.
    """
    print("\n=== sections ===")
    problems = 0

    total = sum(len(c.get("sections") or []) for c in catalog)
    offered = [c for c in catalog if c.get("semester_offered")]
    print(f"  {total:,} sections across {sum(1 for c in catalog if c.get('sections')):,} courses")

    if not total:
        print("  [FAIL] no sections at all — re-run scrape_bu_catalog.py --rescan")
        return problems + 1

    # A course listed as offered must have at least one section; that's where
    # semester_offered is derived from, so a mismatch means the two disagree.
    inconsistent = [c["course_code"] for c in offered if not c.get("sections")]
    if inconsistent:
        problems += len(inconsistent)
        print(f"  [FAIL] {len(inconsistent):,} courses claim a semester but have no sections: "
              f"{inconsistent[:5]}")

    # Every section needs a code — it's the offering's dedup key.
    nameless = sum(
        1 for c in catalog for s in (c.get("sections") or []) if not (s.get("section") or "").strip()
    )
    if nameless:
        problems += nameless
        print(f"  [FAIL] {nameless:,} sections with no section code")

    # A repeated section code is normally a second *meeting pattern* for the same
    # section (lecture + exam block), which the importer merges into one row —
    # `course_offerings` is UNIQUE (course_id, term_id, section). Informational.
    dup_courses = [
        c["course_code"] for c in catalog
        if (codes := [s.get("section") for s in (c.get("sections") or [])])
        and len(codes) != len(set(codes))
    ]
    if dup_courses:
        print(f"  [warn] {len(dup_courses):,} courses publish multiple meetings for one "
              f"section (merged on import): {dup_courses[:3]}")

    for field in ("instructor_name", "meeting_times", "location"):
        have = sum(1 for c in catalog for s in (c.get("sections") or []) if s.get(field))
        print(f"  coverage {field:16} {have:6,}/{total:,}  ({100*have//total}%)")

    # "Staff"/"TBA" must be NULL, not stored literally — students would see it.
    placeholder = sum(
        1 for c in catalog for s in (c.get("sections") or [])
        if (s.get("instructor_name") or "").strip().lower() in {"staff", "tba", "tbd"}
    )
    if placeholder:
        problems += placeholder
        print(f"  [FAIL] {placeholder:,} sections stored a placeholder instructor literally")

    return problems


def spot_check(catalog: list[dict], n: int) -> int:
    """Re-fetch a random sample and diff against the stored records."""
    print(f"\n=== live spot-check — {n} random courses ===")
    sample = random.sample(catalog, min(n, len(catalog)))
    mismatches = 0

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for i, stored in enumerate(sample, 1):
            url = stored["source_url"]
            try:
                r = client.get(url, headers=HEADERS)
            except httpx.HTTPError as exc:
                print(f"  [{i}] {stored['course_code']}: fetch failed — {exc}")
                continue
            if r.status_code != 200:
                print(f"  [{i}] {stored['course_code']}: HTTP {r.status_code}")
                continue

            fresh = parse_course(r.text, url, stored["school"])
            if fresh is None:
                mismatches += 1
                print(f"  [{i}] {stored['course_code']}: re-parse returned None")
                continue

            diffs = [
                f"{f}: stored={stored.get(f)!r} live={fresh.get(f)!r}"
                for f in ("course_code", "title", "credits", "semester_offered")
                if stored.get(f) != fresh.get(f)
            ]
            # Sections are compared by code only: instructor/room assignments churn
            # on bu.edu mid-summer, and a re-import picks those up anyway. A
            # different *set of sections* is the real signal of parser drift.
            if {s.get("section") for s in stored.get("sections") or []} != \
               {s.get("section") for s in fresh.get("sections") or []}:
                diffs.append(
                    f"sections: stored={sorted(s.get('section') for s in stored.get('sections') or [])} "
                    f"live={sorted(s.get('section') for s in fresh.get('sections') or [])}"
                )
            if diffs:
                mismatches += 1
                print(f"  [{i}] {stored['course_code']} MISMATCH")
                for d in diffs:
                    print(f"        {d}")
            else:
                sem = ",".join(fresh.get("semester_offered") or []) or "-"
                print(f"  [{i}] {stored['course_code']:14} ok  ({sem}, "
                      f"{len(fresh.get('sections') or [])} sections)")
            time.sleep(SPOT_DELAY)

    print(f"\n  {len(sample) - mismatches}/{len(sample)} matched live bu.edu")
    return mismatches


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", type=int, default=25, help="live spot-checks (0 = offline only)")
    a = p.parse_args()

    if not CATALOG_FILE.exists():
        raise SystemExit(f"Missing {CATALOG_FILE}")
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))

    issues = structural(data)
    if a.sample:
        issues += spot_check(data, a.sample)

    print(f"\n{'=' * 50}")
    print("VERDICT:", "clean" if issues == 0 else f"{issues} issue(s) to review")
    sys.exit(1 if issues else 0)
