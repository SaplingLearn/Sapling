#!/usr/bin/env python3
"""Probe catalog courses the listing crawl never reached.

`scrape_bu_catalog.py` walks `/academics/{school}/courses/` listing pages, so it
can only find courses BU links from its own index. Two kinds of course escape it:

  1. **Index orphans** — the course page exists and is current (verified: CAS CH
     303 / 365 / 401 all run in Fall 2026) but no listing page links to it.
  2. **Prefixes with no school section** — e.g. HUB, which is a Hub-requirement
     prefix rather than a school, so `/academics/hub/courses/` does not exist.

Both are invisible to a crawl but visible to a direct URL, because the course
code determines the slug (`CAS CH 303` -> `/academics/cas/courses/cas-ch-303/`).
This script takes every `courses` row absent from the scrape and fetches it
directly, sorting each into: still-offered / exists-but-not-this-term / retired /
unreachable (every candidate URL failed in transport, so no verdict was reached —
never treat these as retired).

Output is written to `data/unscraped_probe.json` so the offering sync can consume
it, and so the retired list is available for a separate cleanup decision.

Run (from `backend/`):

    BU_ENV=.env.staging python scripts/probe_unscraped_courses.py
    BU_ENV=.env.staging python scripts/probe_unscraped_courses.py --limit 50
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

load_dotenv(BACKEND_DIR / os.getenv("BU_ENV", ".env"), override=True)

from db.connection import table  # noqa: E402
from scrape_bu_catalog import HEADERS, parse_course  # noqa: E402

CATALOG_FILE = BACKEND_DIR / "data" / "bu_catalog_fall_2026.json"
OUT_FILE = BACKEND_DIR / "data" / "unscraped_probe.json"
TARGET_LABEL = "Fall 2026"

# course-code prefix -> /academics/<slug>/. Prefixes absent here have no school
# section on bu.edu (HUB, MED, ...); we still try `cas` for them because some
# non-school prefixes are served under the CAS tree.
SLUG = {
    "CAS": "cas", "GRS": "grs", "MET": "met", "ENG": "eng", "CFA": "cfa",
    "COM": "com", "QST": "questrom", "SAR": "sar", "SPH": "sph", "SSW": "ssw",
    "STH": "sth", "SDM": "sdm", "LAW": "law", "GMS": "gms", "CDS": "cds",
    "KHC": "khc", "CGS": "cgs", "SHA": "sha", "WED": "wheelock", "CAMED": "camed",
    "MED": "camed", "HUB": "cas", "XC": "cas",
}
# Same host and same robots.txt as the crawler, so the same policy applies:
# bu.edu asks for `Crawl-delay: 15`, and scrape_bu_catalog.py honors it with one
# worker. Override for a faster (less polite) probe, e.g.
# BU_CONCURRENCY=4 BU_PAGE_DELAY=1.5 — the env var names are shared deliberately.
CONCURRENCY = int(os.getenv("BU_CONCURRENCY", "1"))
DELAY = float(os.getenv("BU_PAGE_DELAY", "15"))

PAGE = 1000    # PostgREST default max rows per response


def _all_rows(name: str, columns: str) -> list[dict]:
    """Read a whole table, paging past the PostgREST row cap.

    Terminates on a short page and treats the count as advisory, for the same
    reason as db/import_offerings.py::_all_rows: `select_with_count` reports
    `total = 0` when Content-Range is missing or unparseable, and `offset >= total`
    then reads `1000 >= 0` — silently returning page one as the whole table. Here
    that would make the probe invent "unscraped" courses out of rows it never read.
    """
    out: list[dict] = []
    offset = 0
    while True:
        rows, total = table(name).select_with_count(
            columns, order="id.asc", limit=PAGE, offset=offset
        )
        out.extend(rows)
        offset += len(rows)
        if len(rows) < PAGE or (total and offset >= total):
            return out


def candidate_urls(code: str) -> list[str]:
    """Plausible page URLs for a course code (school slug is not always 1:1)."""
    slug = code.lower().replace(" ", "-")
    prefix = code.split()[0]
    schools = [SLUG.get(prefix)] if SLUG.get(prefix) else []
    # GRS cross-lists CAS graduate courses, and vice versa.
    for extra in ("cas", "grs"):
        if extra not in schools:
            schools.append(extra)
    return [f"https://www.bu.edu/academics/{s}/courses/{slug}/" for s in schools if s]


async def probe(codes: list[str]) -> dict:
    sem = asyncio.Semaphore(CONCURRENCY)
    offered: list[dict] = []
    exists_other: list[str] = []
    retired: list[str] = []
    unreachable: list[str] = []
    done = 0

    async def one(client: httpx.AsyncClient, code: str) -> None:
        nonlocal done
        async with sem:
            # A code is only "retired" if every candidate URL actually answered and
            # none was a valid page for it. If every attempt died in transport we
            # learned nothing, and calling that retired would invite a cleanup pass
            # to delete courses over a flaky network.
            answered = False
            for url in candidate_urls(code):
                try:
                    r = await client.get(url, headers=HEADERS, timeout=20.0)
                except httpx.HTTPError:
                    continue
                finally:
                    await asyncio.sleep(DELAY)
                answered = True
                if r.status_code != 200:
                    continue
                parsed = parse_course(r.text, url, url.split("/")[4])
                if not parsed:
                    continue
                # The page must be for the code we asked about — a bad slug can
                # redirect to an unrelated page.
                if parsed.get("course_code", "").strip() != code:
                    continue
                if TARGET_LABEL in (parsed.get("semester_offered") or []):
                    offered.append(parsed)
                else:
                    exists_other.append(code)
                break
            else:
                (retired if answered else unreachable).append(code)
        done += 1
        if done % 50 == 0:
            print(f"  probed {done}/{len(codes)} — offered={len(offered)} "
                  f"exists={len(exists_other)} retired={len(retired)} "
                  f"unreachable={len(unreachable)}", flush=True)

    async with httpx.AsyncClient(follow_redirects=True,
                                 limits=httpx.Limits(max_connections=20)) as client:
        await asyncio.gather(*[one(client, c) for c in codes])

    return {
        "offered": offered,
        "exists_other_term": exists_other,
        "retired": retired,
        "unreachable": unreachable,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=0, help="probe only the first N (testing)")
    a = p.parse_args()

    db_codes = {
        c["course_code"] for c in _all_rows("courses", "id,course_code") if c.get("course_code")
    }
    scraped = {c["course_code"] for c in json.loads(CATALOG_FILE.read_text(encoding="utf-8"))}
    missing = sorted(db_codes - scraped)
    if a.limit:
        missing = missing[: a.limit]

    print(f"{len(db_codes):,} catalog courses; {len(missing):,} absent from the scrape")
    print(f"probing directly at {CONCURRENCY} workers / {DELAY}s\n")

    result = asyncio.run(probe(missing))
    result["probed"] = len(missing)
    OUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'=' * 50}")
    print(f"  offered in {TARGET_LABEL} : {len(result['offered']):,}")
    print(f"  exists, other term      : {len(result['exists_other_term']):,}")
    print(f"  retired (404)           : {len(result['retired']):,}")
    print(f"  unreachable (network)   : {len(result['unreachable']):,}")
    if result["unreachable"]:
        print("    ^ not a verdict — these never answered; re-probe before acting on them")
    print(f"  -> {OUT_FILE}")
