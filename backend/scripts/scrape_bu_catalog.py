#!/usr/bin/env python3
"""
Layer 0: BU Course Catalog Scraper
Crawls bu.edu/academics/{school}/courses/ for all 22 schools,
extracts course data, and writes to backend/data/bu_catalog_{semester}.json

Run from repo root:
    python backend/scripts/scrape_bu_catalog.py

Resume: re-running skips already-scraped URLs automatically.
"""

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

import httpx
from bs4 import BeautifulSoup

# -- Config ---------------------------------------------------------------------

SCHOOLS = [
    "cas",
    "com",
    "eng",
    "cfa",
    "cgs",
    "cds",
    "camed",
    "khc",
    "gms",
    "grs",
    "sdm",
    "met",
    "questrom",
    "sar",
    "sha",
    "law",
    "sph",
    "ssw",
    "sth",
    "wheelock",
    "frederick-s-pardee-school-of-global-studies",
]

BASE_URL = "https://www.bu.edu"
SEMESTER_TAG = "fall_2026"

# bu.edu/robots.txt asks for `Crawl-delay: 15` on the wildcard agent (/academics/
# is not disallowed). Defaults honor that: one worker, 15s between requests — a
# full ~7k-page crawl takes many hours, so it's meant to run unattended.
# Override for a faster (less polite) crawl, e.g. BU_CONCURRENCY=4 BU_PAGE_DELAY=1.
CONCURRENCY = int(os.getenv("BU_CONCURRENCY", "1"))     # parallel course-page fetches
PAGE_DELAY  = float(os.getenv("BU_PAGE_DELAY", "15"))   # seconds between requests per worker

OUTPUT_DIR   = Path(__file__).parent.parent / "data"
OUTPUT_FILE  = OUTPUT_DIR / f"bu_catalog_{SEMESTER_TAG}.json"
SUMMARY_FILE = OUTPUT_DIR / "scrape_summary.json"

HEADERS = {
    "User-Agent": "SaplingEduBot/1.0 (educational research tool; contact jackhe@honorsocietyofcinematicarts.org)",
    "Accept": "text/html,application/xhtml+xml",
}

# -- State ----------------------------------------------------------------------

_sem    = None   # initialized in main()
_errors: list[dict] = []

# Distinguishes "this page does not exist" (404 -> None) from "we could not fetch
# it" (timeout / retries exhausted -> FETCH_FAILED). The listing walk must not
# treat a transient failure as the end of pagination — doing so silently truncated
# the previous crawl at CAS page ~21 of 113 (416 courses instead of 2,253).
class _FetchFailed:
    """Sentinel type for `fetch`. Compared by identity against FETCH_FAILED."""
    __slots__ = ()


FETCH_FAILED = _FetchFailed()

FetchResult = Union[str, _FetchFailed, None]

# -- HTTP -----------------------------------------------------------------------

async def fetch(client: httpx.AsyncClient, url: str, retries: int = 2) -> FetchResult:
    async with _sem:
        for attempt in range(retries + 1):
            try:
                r = await client.get(url, headers=HEADERS, timeout=20.0, follow_redirects=True)
                await asyncio.sleep(PAGE_DELAY)
                if r.status_code == 200:
                    return r.text
                if r.status_code == 404:
                    return None
                # Other HTTP errors — retry
                if attempt < retries:
                    await asyncio.sleep(5)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt < retries:
                    await asyncio.sleep(5)
                else:
                    _errors.append({"url": url, "error": str(exc)})
        return FETCH_FAILED

# -- Listing page parser --------------------------------------------------------

def parse_listing(html: str, school: str) -> list[str]:
    """Return absolute course-detail URLs from one listing page."""
    soup = BeautifulSoup(html, "html.parser")
    # Match course slugs but exclude pure-numeric pagination slugs like /courses/2/
    pattern = re.compile(rf"^/academics/{re.escape(school)}/courses/(?!\d+$)([^/]+)/$")
    seen: set[str] = set()
    urls: list[str] = []
    for a in soup.find_all("a", href=pattern):
        href = a["href"]
        if href not in seen:
            seen.add(href)
            urls.append(BASE_URL + href)
    return urls

# -- Course detail page parser --------------------------------------------------
# Confirmed BU course page structure:
#   <h1>Boston University Academics</h1>   <- skip (nav)
#   <h1>Introduction to Analysis of Algorithms</h1>  <- TITLE
#   <h2>CAS CS 330</h2>                    <- COURSE CODE
#   <dl><dt>Units:</dt><dd>4</dd></dl>     <- CREDITS
#   <p>Prerequisites: X. - Description. Effective Fall YYYY, ...</p>  <- split on " - "
#   <h4>FALL 2025Schedule</h4>             <- semester labels (strip "Schedule")

_CODE_RE = re.compile(r'\b([A-Z]{2,4}\s+[A-Z]{1,4}\s+[A-Z]?\d{3}[A-Z]?)\b')
_SEM_RE  = re.compile(r'(FALL|SPRING|SPRG|SUMMER|SUMM|WINTER|WINT)\s+\d{4}', re.I)
# Strip BU Hub boilerplate from description tail
_HUB_RE  = re.compile(r'\s*Effective (Fall|Spring|Summer|Winter)\s+\d{4}.*', re.S | re.I)
_BOILER  = re.compile(
    r'Boston University is accredited|javascript|cookie|copyright|privacy|'
    r'listed here|guarantee|portal|register|accredited by|terms of use', re.I
)


def _extract_code_and_title(soup: BeautifulSoup, slug: str) -> tuple[str, str]:
    # Title: second <h1> (first is the site nav "Boston University Academics")
    title = ""
    h1s = soup.find_all("h1")
    for h1 in h1s:
        t = h1.get_text(strip=True)
        if t and "Boston University" not in t:
            title = t
            break

    # Code: first <h2> that matches a course code pattern
    code = ""
    for h2 in soup.find_all("h2"):
        t = h2.get_text(strip=True)
        if _CODE_RE.search(t):
            code = t
            break

    if not code:
        code = slug.upper().replace("-", " ")
    if not title:
        pt = soup.find("title")
        title = pt.get_text(strip=True).split("|")[0].strip() if pt else ""

    return code, title


def _extract_credits(soup: BeautifulSoup) -> Optional[int]:
    # Structure: <dl><dt>Units:</dt><dd>4</dd></dl>
    for dt in soup.find_all("dt"):
        if re.search(r'units?', dt.get_text(), re.I):
            dd = dt.find_next_sibling("dd")
            if dd:
                m = re.search(r'\d+(?:\.\d+)?', dd.get_text())
                if m:
                    val = float(m.group())
                    return int(val) if val == int(val) else val
    return None


def _extract_prereq_and_desc(soup: BeautifulSoup) -> tuple[str, str]:
    # BU embeds description in prereq paragraph: "Prerequisites: X. - Description. Effective..."
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if re.match(r'(Undergraduate\s+)?Prerequisites?:', text, re.I):
            # Split on " - " to separate prereq list from course description
            parts = re.split(r'\s+-\s+', text, maxsplit=1)
            prereq = parts[0].strip()
            desc   = _HUB_RE.sub("", parts[1]).strip() if len(parts) > 1 else ""
            return prereq, desc
    # No prereq paragraph — look for standalone description paragraph
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) > 80 and not _BOILER.search(text):
            return "", _HUB_RE.sub("", text).strip()
    return "", ""


# Registrar placeholders for "no instructor assigned yet". Kept out of
# `instructor_name` so the DB stores NULL rather than the literal string "Staff".
_NO_INSTRUCTOR = {"tba", "tbd", "staff", "instructor", ""}


def _extract_sections(soup: BeautifulSoup) -> list[dict]:
    """One record per scheduled **section** — the operational layer of #280.

    Verified against live markup (2026-07-31, e.g. /academics/cas/courses/cas-cs-330/):
    each section is its own ``<table>`` whose header row is
    ``Section | Instructor | Location | Schedule | Notes``, preceded by an
    ``<h4><strong>FALL 2026</strong> Schedule</h4>`` heading that carries the term.

    Column lookup is **header-driven**, not positional: BU omits columns on some
    pages (a few schools drop Notes, GRS drops Location), so indexing by position
    would shift instructor into location. A table with no ``Section`` header is
    not a schedule table and is skipped.

    An earlier version of this parser collapsed all of this into a bare list of
    instructor names, discarding section/location/schedule — the fields #280
    exists to ingest. Don't collapse it again.

    Note bu.edu publishes only the *upcoming* term, so in practice every section
    here carries one label (currently "Fall 2026"). Past terms are not
    recoverable from this source.
    """
    sections: list[dict] = []
    for tbl in soup.find_all("table"):
        # Headers come from the FIRST row that has any <th>, not from every <th> in
        # the table. A table that repeats its header row mid-way would otherwise
        # yield ["section", ..., "section", ...], and since a dict comprehension
        # keeps the LAST index for a repeated key, every column would shift.
        header_row = next((r for r in tbl.find_all("tr") if r.find("th")), None)
        if header_row is None:
            continue
        headers = [th.get_text(" ", strip=True).lower() for th in header_row.find_all("th")]
        if "section" not in headers:
            continue
        col = {name: i for i, name in enumerate(headers)}

        # The term lives in the nearest preceding <h4>, not in the table itself.
        h4 = tbl.find_previous("h4")
        m = _SEM_RE.search(h4.get_text(" ", strip=True)) if h4 else None
        term = m.group(0).strip().title() if m else ""

        for row in tbl.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue        # the header row

            def cell(name: str, _cells=cells, _col=col) -> str:
                i = _col.get(name)
                return _cells[i].get_text(" ", strip=True) if i is not None and i < len(_cells) else ""

            code = cell("section")
            if not code:
                continue
            instructor = cell("instructor")
            sections.append({
                "term":            term,
                "section":         code,
                "instructor_name": None if instructor.lower() in _NO_INSTRUCTOR else instructor,
                "meeting_times":   cell("schedule") or None,
                "location":        cell("location") or None,
                "notes":           cell("notes") or None,
            })

    return sections


def _derive_schedule(sections: list[dict]) -> tuple[list[str], list[str]]:
    """Course-level rollups kept for back-compat: distinct terms, distinct instructors.

    `semester_offered` is what the importer filters on to decide which courses run
    in the target term; `instructors` is what the pre-#280 consumers read.
    """
    semesters: list[str] = []
    instructors: list[str] = []
    for s in sections:
        if s["term"] and s["term"] not in semesters:
            semesters.append(s["term"])
        name = s["instructor_name"]
        if name and name not in instructors:
            instructors.append(name)
    return semesters, instructors


def parse_course(html: str, url: str, school: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "html.parser")
    slug = url.rstrip("/").split("/")[-1]

    code, title = _extract_code_and_title(soup, slug)
    if not code:
        return None

    prerequisites, description = _extract_prereq_and_desc(soup)
    credits = _extract_credits(soup)
    sections = _extract_sections(soup)
    semesters, instructors = _derive_schedule(sections)

    return {
        "course_code":      code,
        "course_slug":      slug,
        "title":            title,
        "school":           school,
        "description":      description,
        "credits":          credits,
        "prerequisites":    prerequisites,
        "semester_offered": semesters,
        "instructors":      instructors,
        "sections":         sections,
        "source_url":       url,
        "scraped_at":       datetime.now(timezone.utc).isoformat(),
        "semester_tag":     SEMESTER_TAG,
    }

# -- School scraper -------------------------------------------------------------

async def scrape_school(
    client: httpx.AsyncClient,
    school: str,
    seen: set[str],
    on_batch=None,   # callable(batch: list[dict]) — called every 100 courses
) -> list[dict]:
    # Phase 1: collect all course URLs by walking paginated listing.
    # BU wraps pagination (serves page 1 again past the last page) instead of
    # 404-ing, so we stop as soon as a page yields zero URLs we haven't seen
    # in this school's current crawl.
    crawl_seen: set[str] = set()   # URLs found in this school's listing walk
    page = 1
    while True:
        listing_url = (
            f"{BASE_URL}/academics/{school}/courses/"
            if page == 1
            else f"{BASE_URL}/academics/{school}/courses/{page}/"
        )
        html = await fetch(client, listing_url)
        if html is FETCH_FAILED:
            # Loud, recorded, and NOT confused with the end of pagination.
            msg = f"listing fetch failed at page {page} — {school} is TRUNCATED"
            _errors.append({"url": listing_url, "error": msg})
            print(f"  [{school}] !! {msg}", flush=True)
            break
        if not html:
            break   # genuine 404 — past the last page
        urls = parse_listing(html, school)
        fresh = [u for u in urls if u not in crawl_seen]
        if not fresh:
            break   # pagination wrapped or past last page
        crawl_seen.update(fresh)
        page += 1
        if page > 250:   # absolute safety limit
            break

    new_urls = [u for u in crawl_seen if u not in seen]
    print(f"  [{school}] {page - 1} listing pages | {len(crawl_seen)} total | {len(new_urls)} new", flush=True)

    # Phase 2: fetch + parse course detail pages in batches of 100.
    # on_batch is called after each batch so the caller can save a checkpoint.
    BATCH = 100
    courses: list[dict] = []

    async def _fetch_one(url: str) -> Optional[dict]:
        html = await fetch(client, url)
        if html is FETCH_FAILED or not html:
            _errors.append({"url": url, "error": "empty response"})
            return None
        result = parse_course(html, url, school)
        if result is None:
            _errors.append({"url": url, "error": "parse failed"})
        return result

    for i in range(0, len(new_urls), BATCH):
        batch_results = await asyncio.gather(*[_fetch_one(u) for u in new_urls[i:i + BATCH]])
        batch_courses = [r for r in batch_results if r is not None]
        courses.extend(batch_courses)
        if on_batch:
            on_batch(batch_courses)

    return courses

# -- Rescan ---------------------------------------------------------------------

async def rescan(
    client: httpx.AsyncClient,
    records: list[dict],
    on_checkpoint=None,   # callable() — called every batch
) -> tuple[int, int]:
    """Refetch course pages already in the JSON and re-parse them **in place**.

    The listing walk is skipped entirely: every URL we want is already recorded,
    including the index orphans that only probe_unscraped_courses.py could reach
    (a fresh crawl would silently drop those). This is the cheap way to upgrade an
    existing scrape after a parser change — e.g. adding `sections` (#280), which
    the previous parser threw away and no amount of re-reading the JSON recovers.

    A page that fails to fetch or parse leaves its record untouched rather than
    blanking it, so a flaky rescan degrades to "some records still stale" instead
    of data loss. Returns (updated, failed).
    """
    BATCH = 100
    updated = failed = 0

    async def _refetch(rec: dict) -> Optional[dict]:
        url = rec["source_url"]
        html = await fetch(client, url)
        if html is FETCH_FAILED or not html:
            _errors.append({"url": url, "error": "rescan: empty response"})
            return None
        fresh = parse_course(html, url, rec.get("school", ""))
        if fresh is None:
            _errors.append({"url": url, "error": "rescan: parse failed"})
            return None
        # `fetch` follows redirects, so a retired slug can serve an unrelated
        # course's page. parse_course stamps source_url from the URL we asked for,
        # so the only tell is the code on the page. Overwriting the record here
        # would replace one course's data with another's.
        old_code = (rec.get("course_code") or "").strip()
        new_code = (fresh.get("course_code") or "").strip()
        if old_code and new_code != old_code:
            _errors.append(
                {"url": url, "error": f"rescan: redirected to {new_code!r}, expected {old_code!r}"}
            )
            return None
        return fresh

    for i in range(0, len(records), BATCH):
        window = records[i : i + BATCH]
        results = await asyncio.gather(*[_refetch(r) for r in window])
        for rec, fresh in zip(window, results):
            if fresh is None:
                failed += 1
                continue
            rec.clear()
            rec.update(fresh)
            updated += 1
        if on_checkpoint:
            on_checkpoint()
        print(f"    rescanned {min(i + BATCH, len(records)):,}/{len(records):,} "
              f"({updated:,} updated, {failed:,} failed)", flush=True)

    return updated, failed

# -- Main -----------------------------------------------------------------------

async def main(mode: str = "resume") -> None:
    global _sem
    _sem = asyncio.Semaphore(CONCURRENCY)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resume: load whatever was scraped in a previous run.
    # --refresh forces a full refetch instead: resume matches on source_url, so a
    # plain re-run skips every known course and would keep stale/missing fields
    # (e.g. the empty semester_offered left by the shadowed-parser bug).
    existing: dict[str, dict] = {}
    if OUTPUT_FILE.exists() and mode == "refresh":
        backup = OUTPUT_FILE.with_suffix(".json.bak")
        OUTPUT_FILE.replace(backup)
        print(f"--refresh: previous scrape moved to {backup.name}; refetching everything")
    elif OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for c in json.load(f):
                existing[c["source_url"]] = c
        verb = "Rescanning" if mode == "rescan" else "Resuming"
        print(f"{verb} — {len(existing)} courses already in {OUTPUT_FILE.name}")
    elif mode == "rescan":
        raise SystemExit(f"--rescan needs an existing {OUTPUT_FILE.name}; run a plain scrape first.")

    seen_urls: set[str]  = set(existing.keys())
    all_courses: list[dict] = list(existing.values())
    start = datetime.now(timezone.utc)

    def write_file() -> None:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_courses, f, indent=2, ensure_ascii=False)

    def save_checkpoint(batch: list[dict]) -> None:
        all_courses.extend(batch)
        seen_urls.update(c["source_url"] for c in batch)
        write_file()
        print(f"    checkpoint: {len(all_courses)} courses saved", flush=True)

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=20)) as client:
        if mode == "rescan":
            # Back up first: rescan rewrites every record, so a bad parser change
            # would otherwise overwrite the only copy of the scrape.
            backup = OUTPUT_FILE.with_suffix(".json.prescan.bak")
            backup.write_bytes(OUTPUT_FILE.read_bytes())
            print(f"backup -> {backup.name}\n")
            updated, failed = await rescan(client, all_courses, on_checkpoint=write_file)
            print(f"\nrescan: {updated:,} updated, {failed:,} left stale")
        else:
            for school in SCHOOLS:
                print(f"\n>> {school}", flush=True)
                before = len(all_courses)
                await scrape_school(client, school, seen_urls, on_batch=save_checkpoint)
                print(f"  [{school}] +{len(all_courses) - before} -> total {len(all_courses)}", flush=True)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    with_sections = sum(1 for c in all_courses if c.get("sections"))

    summary = {
        "total_courses":  len(all_courses),
        "with_sections":  with_sections,
        "total_sections": sum(len(c.get("sections") or []) for c in all_courses),
        "mode":           mode,
        "total_errors":   len(_errors),
        "errors":         _errors[:100],
        "elapsed_seconds": round(elapsed),
        "completed_at":   datetime.now(timezone.utc).isoformat(),
        "semester_tag":   SEMESTER_TAG,
        "output_file":    str(OUTPUT_FILE),
    }
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Done: {len(all_courses):,} courses  |  {with_sections:,} with sections  "
          f"|  {len(_errors)} errors  |  {round(elapsed/60)} min")
    print(f"   Output -> {OUTPUT_FILE}")
    print(f"   Summary -> {SUMMARY_FILE}")


if __name__ == "__main__":
    import argparse

    _p = argparse.ArgumentParser(description="Scrape the BU course catalog.")
    _g = _p.add_mutually_exclusive_group()
    _g.add_argument(
        "--refresh",
        action="store_true",
        help="ignore (and back up) a previous scrape and re-crawl every school from the listings",
    )
    _g.add_argument(
        "--rescan",
        action="store_true",
        help="refetch only the course pages already in the JSON and re-parse them in place "
             "(no listing walk — use this to pick up a parser change)",
    )
    _a = _p.parse_args()
    asyncio.run(main(mode="refresh" if _a.refresh else "rescan" if _a.rescan else "resume"))
