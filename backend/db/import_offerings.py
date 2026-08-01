"""Import real per-section `course_offerings` from a BU catalog scrape (#280).

Staging's academics data is **catalog-only**: every course carries one hollow
offering with no section, no meeting time, and no location, so courses can't
behave like a real registrar. This script ingests the operational layer — one
`course_offerings` row **per published section** — from
`data/bu_catalog_<term>.json`, which `scripts/scrape_bu_catalog.py` produces.

Per-section input contract (the `sections` list on each scraped course):

    course_code      "CAS CS 330"        space-separated, uppercase; joins to courses.course_code
    section          "A1"                required; the registrar's section code
    instructor_name  "Erdos" | null      null when the registrar published Staff/TBA
    meeting_times    "TR 2:00 pm-3:15 pm" | null
    location         "LSE B01" | null    null for ARR ("arranged") sections
    term             "Fall 2026"         matched against terms.label

`syllabus_url` is part of the offering model but bu.edu does not publish one in
the schedule table, so it is left untouched here rather than invented.

**course_code normalization.** The join to `courses.course_code` is exact string
equality, so the scrape must already emit the catalog's format:

    <SCHOOL> <DEPT> <NUMBER>        e.g. "CAS CS 330", "QST FE 101", "CAS AA 307E"

- uppercase; single ASCII space between the three parts (never a tab, en dash, or
  double space);
- school 2-4 letters, department 1-4 letters, number 3 digits with an optional
  leading or trailing letter (`307E`, `S331`);
- no trailing section, term, or credit suffix — those live on the offering.

The scraper reads this off the course page's `<h2>`, which is already in catalog
format; the slug fallback (`cas-cs-330` -> `CAS CS 330`) produces the same shape.
Codes that don't match are reported by `scripts/verify_catalog_scrape.py`
(`malformed course_codes`) rather than silently failing to join here.

**Adoption, not re-creation.** Staging already holds section-less Fall 2026
offerings that enrollments, sessions, documents and notes point at. Deleting and
re-inserting would orphan or cascade-delete those. So for each course the
existing section-less row is *adopted* by the first published section (updated in
place, id preserved) and only the remaining sections are inserted.

Idempotent: a second run matches every section by code, finds nothing to adopt,
and writes nothing. Re-running after a fresh scrape updates instructor / meeting
time / location where the registrar changed them.

Dry run by default. Run from `backend/`:

    python -m db.import_offerings                                  # dry run vs .env
    python -m db.import_offerings --apply
    dotenv -f .env.staging run -- python -m db.import_offerings --apply
    dotenv -f .env.staging run -- python -m db.import_offerings --apply --create-missing --link-school

Requires `0033_offering_section_not_null.sql` (section NOT NULL DEFAULT ''),
already in the migration chain — run `python -m db.migrate` on a database that
predates it. This script is idempotent either way, since after a run every row
carries a real section code and the second pass matches by code. But without
0033 the UNIQUE (course_id, term_id, section) stays NULL-distinct, and the
*application* path (`resolve_offering(create=True)`) can still mint duplicate
section-less offerings between imports for this script to have to adopt.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from db.connection import SUPABASE_URL, table

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_CATALOG = DATA_DIR / "bu_catalog_fall_2026.json"
PROBE_FILE = DATA_DIR / "unscraped_probe.json"

PAGE = 1000    # PostgREST default max rows per response
BATCH = 500    # insert batch size

# The real Boston University row (#280 task 3). Fixed id so re-runs and other
# ops scripts can reference it without a lookup; `slug` is the upsert key.
BU_SCHOOL = {"id": "school-bu", "name": "Boston University", "slug": "boston-university"}

# Offering columns this importer owns. Anything else on the row (syllabus_url,
# created_at, ...) is left alone so a re-run never clears data it didn't set.
OWNED = ("instructor_name", "meeting_times", "location")


def _all_rows(name: str, columns: str) -> list[dict]:
    """Read a whole table, paging past the PostgREST row cap."""
    out: list[dict] = []
    offset = 0
    while True:
        rows, total = table(name).select_with_count(
            columns, order="id.asc", limit=PAGE, offset=offset
        )
        out.extend(rows)
        offset += len(rows)
        if not rows or offset >= total:
            return out


def _resolve_term(term: str) -> dict:
    for filters in ({"id": f"eq.{term}"}, {"label": f"eq.{term}"}):
        rows = table("terms").select("id,label", filters=filters, limit=1)
        if rows:
            return rows[0]
    raise SystemExit(f"No term matches {term!r} — check the `terms` table.")


def load_catalog(path: Path, include_probe: bool) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Missing {path} — run scripts/scrape_bu_catalog.py first.")
    catalog: list[dict] = json.loads(path.read_text(encoding="utf-8"))

    # Courses the listing crawl could not reach (index orphans, prefixes with no
    # school section) but that probe_unscraped_courses.py confirmed by direct URL.
    # Same record shape as the scrape, so they merge straight in.
    if include_probe:
        if not PROBE_FILE.exists():
            raise SystemExit(
                f"--include-probe: missing {PROBE_FILE.name}. "
                "Run scripts/probe_unscraped_courses.py first."
            )
        extra = json.loads(PROBE_FILE.read_text(encoding="utf-8")).get("offered") or []
        catalog = catalog + extra
        print(f"--include-probe: +{len(extra):,} directly-probed courses")
    return catalog


# Registrar placeholders for "no room assigned". The scrape keeps the page text
# verbatim; mapping them to NULL is the importer's job, same as Staff/TBA.
_NO_LOCATION = {"no room", "tba", "tbd", "arr", ""}


def _merge_meetings(rows: list[dict]) -> dict:
    """Collapse the meeting patterns BU publishes for one section into one row.

    A section is not always one meeting: CAS MA 123 A1 is a MWF 9:05 lecture in
    STO B50 *and* a Thursday 6:30 exam block, published as two rows under the same
    section code. `course_offerings` is one row per section
    (UNIQUE (course_id, term_id, section)) with a single free-text `meeting_times`,
    so the patterns are joined rather than dropped — 308 sections in the Fall 2026
    scrape have more than one, and keeping only the first loses a real meeting.

    Instructor is the first non-null: verified across the whole scrape that no
    multi-meeting section lists two different instructors.
    """
    instructor = next((s.get("instructor_name") for s in rows if s.get("instructor_name")), None)
    times: list[str] = []
    locations: list[str] = []
    for s in rows:
        t = (s.get("meeting_times") or "").strip()
        if t and t not in times:
            times.append(t)
        loc = (s.get("location") or "").strip()
        if loc and loc.lower() not in _NO_LOCATION and loc not in locations:
            locations.append(loc)
    return {
        "section": rows[0]["section"],
        "instructor_name": instructor,
        "meeting_times": "; ".join(times) or None,
        "location": "; ".join(locations) or None,
    }


def desired_sections(catalog: list[dict], label: str) -> dict[str, list[dict]]:
    """course_code -> its published sections for `label`, in registrar order.

    Cross-listed courses (BU lists CAS graduate courses under GRS too) appear
    twice in the scrape with the same code and the same sections; the first
    record wins so the same section isn't queued twice.
    """
    by_code: dict[str, list[dict]] = {}
    for course in catalog:
        code = (course.get("course_code") or "").strip()
        if not code or code in by_code:
            continue
        # Group by section code first, preserving page order, then collapse each
        # group's meeting patterns into the single row the schema allows.
        grouped: dict[str, list[dict]] = {}
        for s in course.get("sections") or []:
            if s.get("term") != label:
                continue
            section = (s.get("section") or "").strip()
            if not section:
                continue
            grouped.setdefault(section, []).append({**s, "section": section})
        if grouped:
            by_code[code] = [_merge_meetings(rows) for rows in grouped.values()]
    return by_code


def create_missing_courses(codes: list[str], catalog: list[dict], apply: bool) -> dict[str, str]:
    """Insert catalog rows for scraped codes with no `courses` row. Returns code -> id."""
    first: dict[str, dict] = {}
    for c in catalog:
        first.setdefault((c.get("course_code") or "").strip(), c)

    new_courses = []
    fractional = 0
    for code in codes:
        src = first.get(code, {})
        parts = code.split()
        # `courses.credits` is INTEGER (0020) but BU lists half-unit courses (CFA
        # music, 0.5), which PostgREST rejects with a 400. Store NULL rather than
        # rounding: GPA is credit-weighted, so 0.5 -> 0 would drop the course from
        # the average and 0.5 -> 1 would double its weight. NULL means "unknown",
        # which is what the bulk of existing catalog rows already are.
        credits = src.get("credits")
        if isinstance(credits, float) and credits != int(credits):
            credits = None
            fractional += 1
        elif credits is not None:
            credits = int(credits)
        new_courses.append({
            "id": str(uuid.uuid4()),
            # school_id stays NULL here; --link-school sets it for the whole catalog
            # in one pass after the duplicate-code precheck.
            "school_id": None,
            "course_code": code,
            "course_name": src.get("title") or code,
            "department": parts[1] if len(parts) > 2 else None,
            "credits": credits,
            "description": src.get("description") or None,
        })

    print(f"--create-missing: {len(new_courses):,} new catalog courses")
    if fractional:
        print(f"  ({fractional:,} had fractional credits -> stored as NULL)")
    if apply:
        for i in range(0, len(new_courses), BATCH):
            table("courses").insert(new_courses[i : i + BATCH])
            print(f"  courses inserted {min(i + BATCH, len(new_courses)):,}/{len(new_courses):,}", flush=True)
    return {c["course_code"]: c["id"] for c in new_courses}


def link_school(apply: bool) -> None:
    """Create the Boston University school row and link the catalog to it (#280 task 3).

    `courses` is UNIQUE (school_id, course_code) and NULL school_ids make that
    constraint NULL-distinct, so duplicate codes can hide in the catalog today and
    would collide the moment school_id is set. This refuses to link if any exist
    rather than failing halfway through with a 409 and a partially-linked catalog.
    Merging duplicates is not automated: `courses.id` is the knowledge-graph key
    and is referenced by a dozen tables, so collapsing two rows is a migration,
    not a batch update.
    """
    print("\n--link-school: Boston University")
    courses = _all_rows("courses", "id,course_code,school_id")

    by_code: dict[str, list[dict]] = {}
    for c in courses:
        by_code.setdefault(c.get("course_code") or "", []).append(c)
    dupes = {code: rows for code, rows in by_code.items() if len(rows) > 1}
    if dupes:
        print(f"  [FAIL] {len(dupes)} duplicate course_code(s) would collide on "
              "UNIQUE (school_id, course_code):")
        for code, rows in list(dupes.items())[:10]:
            print(f"         {code}: {[r['id'] for r in rows]}")
        print("  Resolve these first (merge the rows and repoint course_id references); "
              "nothing was linked.")
        return

    demo = [c for c in courses if c.get("school_id") and c["school_id"] != BU_SCHOOL["id"]]
    todo = [c for c in courses if not c.get("school_id")]
    print(f"  {len(todo):,} unlinked courses; {len(demo)} already belong to another school (left alone)")
    if not apply:
        print("  dry run — school row and links not written.")
        return

    table("schools").upsert(BU_SCHOOL, on_conflict="slug")
    for i in range(0, len(todo), BATCH):
        window = todo[i : i + BATCH]
        table("courses").update(
            {"school_id": BU_SCHOOL["id"]},
            filters={"id": f"in.({','.join(c['id'] for c in window)})"},
        )
        print(f"  linked {min(i + BATCH, len(todo)):,}/{len(todo):,}", flush=True)


def run(
    term: str,
    apply: bool,
    catalog_path: Path,
    create_missing: bool = False,
    include_probe: bool = False,
    do_link_school: bool = False,
) -> None:
    target = _resolve_term(term)
    term_id, label = target["id"], target["label"]
    catalog = load_catalog(catalog_path, include_probe)
    wanted = desired_sections(catalog, label)
    total_sections = sum(len(v) for v in wanted.values())

    print(f"target term: {label} ({term_id})")
    print(f"project:     {SUPABASE_URL or '(SUPABASE_URL unset)'}")
    print(f"mode:        {'APPLY' if apply else 'dry run'}")
    print(f"catalog:     {len(catalog):,} scraped courses")
    print(f"published:   {len(wanted):,} courses / {total_sections:,} sections in {label}\n")

    if not wanted:
        print(
            "No sections found. Either the scrape predates the per-section parser "
            "(`sections` absent on every record — re-run scripts/scrape_bu_catalog.py "
            f"--rescan) or bu.edu no longer publishes {label}."
        )
        return

    # code -> abstract course id
    courses = _all_rows("courses", "id,course_code")
    by_code = {c["course_code"]: c["id"] for c in courses if c.get("course_code")}
    print(f"{len(by_code):,} courses in the catalog table")

    missing = sorted(code for code in wanted if code not in by_code)
    if missing:
        if create_missing:
            by_code.update(create_missing_courses(missing, catalog, apply))
        else:
            print(f"{len(missing):,} scraped codes have no catalog row and will be SKIPPED "
                  f"(pass --create-missing to add them): e.g. {missing[:5]}")

    # Existing offerings in the target term, grouped by course.
    existing: dict[str, list[dict]] = {}
    for o in _all_rows("course_offerings", "id,course_id,term_id,section,instructor_name,meeting_times,location"):
        if o.get("term_id") == term_id:
            existing.setdefault(o["course_id"], []).append(o)
    print(f"{sum(len(v) for v in existing.values()):,} existing {label} offerings "
          f"across {len(existing):,} courses\n")

    to_insert: list[dict] = []
    to_update: list[tuple[str, dict]] = []   # (offering_id, patch)
    adopted = unchanged = skipped_codes = 0

    for code, sections in sorted(wanted.items()):
        course_id = by_code.get(code)
        if not course_id:
            skipped_codes += 1
            continue

        rows = existing.get(course_id, [])
        by_section = {(r.get("section") or ""): r for r in rows}
        # Section-less rows are the hollow legacy offerings; the first published
        # section adopts one (in place, keeping its id) so enrollments/sessions
        # that already point at it survive. Oldest-first keeps the choice stable.
        hollow = sorted((r for r in rows if not (r.get("section") or "")), key=lambda r: r["id"])

        for want in sections:
            row = by_section.get(want["section"])
            if row is None and hollow:
                row = hollow.pop(0)
                to_update.append((row["id"], {"section": want["section"], **{k: want[k] for k in OWNED}}))
                adopted += 1
                continue
            if row is None:
                to_insert.append({
                    "id": str(uuid.uuid4()),
                    "course_id": course_id,
                    "term_id": term_id,
                    "section": want["section"],
                    **{k: want[k] for k in OWNED},
                })
                continue
            patch = {k: want[k] for k in OWNED if row.get(k) != want[k]}
            if patch:
                to_update.append((row["id"], patch))
            else:
                unchanged += 1

    # Offerings in this term the scrape no longer publishes. Reported, never
    # deleted: enrollments/sessions may reference them, and a partial scrape must
    # not be able to wipe a term. Only counted for courses the scrape *does*
    # cover — a course missing from the scrape entirely is silence, not a signal.
    published_by_course: dict[str, set[str]] = {
        by_code[code]: {s["section"] for s in sections}
        for code, sections in wanted.items()
        if code in by_code
    }
    adopted_ids = {oid for oid, _ in to_update}
    stale = sum(
        1
        for course_id, rows in existing.items()
        if course_id in published_by_course
        for r in rows
        if r["id"] not in adopted_ids
        and (r.get("section") or "") not in published_by_course[course_id]
    )

    print(f"insert:    {len(to_insert):,} new section offerings")
    print(f"adopt:     {adopted:,} hollow offerings upgraded in place (ids preserved)")
    print(f"update:    {len(to_update) - adopted:,} existing sections with changed instructor/time/location")
    print(f"unchanged: {unchanged:,}")
    if skipped_codes:
        print(f"skipped:   {skipped_codes:,} courses with no catalog row")
    if stale:
        print(f"stale:     {stale:,} offerings in {label} the scrape no longer lists (left alone)")

    if not to_insert and not to_update:
        print("\nNothing to do — already in sync.")
        return
    if not apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        if do_link_school:
            link_school(apply=False)
        return

    for i in range(0, len(to_insert), BATCH):
        table("course_offerings").insert(to_insert[i : i + BATCH])
        print(f"  inserted {min(i + BATCH, len(to_insert)):,}/{len(to_insert):,}", flush=True)

    for n, (offering_id, patch) in enumerate(to_update, 1):
        table("course_offerings").update(patch, filters={"id": f"eq.{offering_id}"})
        if n % BATCH == 0:
            print(f"  updated {n:,}/{len(to_update):,}", flush=True)

    print(f"\nDone: {len(to_insert):,} inserted, {len(to_update):,} updated in {label}.")

    if do_link_school:
        link_school(apply=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--term", default="fall-2026", help="term id or label (default fall-2026)")
    p.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="scrape JSON to import")
    p.add_argument("--create-missing", dest="create_missing", action="store_true",
                   help="insert scraped courses that have no `courses` row, then give them offerings")
    p.add_argument("--include-probe", dest="include_probe", action="store_true",
                   help="also use data/unscraped_probe.json (courses found by direct URL)")
    p.add_argument("--link-school", dest="link_school", action="store_true",
                   help="create the Boston University school row and link unlinked catalog courses to it")
    a = p.parse_args()
    run(a.term, a.apply, a.catalog, a.create_missing, a.include_probe, a.link_school)


if __name__ == "__main__":
    sys.exit(main())
