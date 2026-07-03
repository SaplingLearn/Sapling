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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
CONCURRENCY = 8       # parallel course-page fetches
PAGE_DELAY  = 0.4     # seconds between requests per worker

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

# -- HTTP -----------------------------------------------------------------------

async def fetch(client: httpx.AsyncClient, url: str, retries: int = 2) -> Optional[str]:
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
        return None

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


def _extract_schedule(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    # Semester labels are in <h4>FALL 2025Schedule</h4> (text = "FALL 2025" + "Schedule")
    semesters: list[str] = []
    for h4 in soup.find_all("h4"):
        m = _SEM_RE.search(h4.get_text(strip=True))
        if m:
            label = m.group(0).strip().title()
            if label not in semesters:
                semesters.append(label)

    # Instructors from all section tables
    instructors: list[str] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "instructor" not in headers:
            continue
        idx = headers.index("instructor")
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) > idx:
                name = cells[idx].get_text(strip=True)
                if name and name not in ("TBA", "Staff", "") and name not in instructors:
                    instructors.append(name)

    return semesters, instructors


def _extract_schedule(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    semesters: list[str] = []
    instructors: list[str] = []
    sem_pattern = re.compile(
        r'^(FALL|SPRING|SPRG|SUMMER|SUMM|SUM|WINTER|WINT)\s+\d{4}$', re.I
    )
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        for h in headers:
            if sem_pattern.match(h.strip()) and h not in semesters:
                semesters.append(h.strip().title())

        # Instructor column
        lower_headers = [h.lower() for h in headers]
        if "instructor" in lower_headers:
            idx = lower_headers.index("instructor")
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) > idx:
                    name = cells[idx].get_text(strip=True)
                    if name and name not in ("TBA", "Staff", "") and name not in instructors:
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
    semesters, instructors = _extract_schedule(soup)

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
        if not html:
            break
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
        if not html:
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

# -- Main -----------------------------------------------------------------------

async def main() -> None:
    global _sem
    _sem = asyncio.Semaphore(CONCURRENCY)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Resume: load whatever was scraped in a previous run
    existing: dict[str, dict] = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for c in json.load(f):
                existing[c["source_url"]] = c
        print(f"Resuming — {len(existing)} courses already in {OUTPUT_FILE.name}")

    seen_urls: set[str]  = set(existing.keys())
    all_courses: list[dict] = list(existing.values())
    start = datetime.now(timezone.utc)

    def save_checkpoint(batch: list[dict]) -> None:
        all_courses.extend(batch)
        seen_urls.update(c["source_url"] for c in batch)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(all_courses, f, indent=2, ensure_ascii=False)
        print(f"    checkpoint: {len(all_courses)} courses saved", flush=True)

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=20)) as client:
        for school in SCHOOLS:
            print(f"\n>> {school}", flush=True)
            before = len(all_courses)
            school_courses = await scrape_school(client, school, seen_urls, on_batch=save_checkpoint)
            print(f"  [{school}] +{len(all_courses) - before} -> total {len(all_courses)}", flush=True)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    summary = {
        "total_courses":  len(all_courses),
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
    print(f"Done: {len(all_courses):,} courses  |  {len(_errors)} errors  |  {round(elapsed/60)} min")
    print(f"   Output -> {OUTPUT_FILE}")
    print(f"   Summary -> {SUMMARY_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
