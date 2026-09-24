"""Parser tests for scripts/scrape_bu_catalog.py — the #280 section contract.

The markup below is the real bu.edu structure, reduced: verified 2026-07-31
against /academics/cas/courses/cas-cs-330/ and re-checked across cas, com, eng,
cfa, cgs, cds, camed, and khc — all eight serve the identical
``Section | Instructor | Location | Schedule | Notes`` header row, with each
section in its own <table> under an ``<h4>FALL 2026 Schedule</h4>`` heading.

These tests exist because the previous parser flattened that table into a bare
list of instructor names, silently discarding section / location / meeting time —
the exact fields #280 ingests. A regression here is invisible in the scrape output
(you get a plausible file with an empty operational layer), so it has to be caught
at the parser.
"""
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from bs4 import BeautifulSoup  # noqa: E402

from scrape_bu_catalog import (  # noqa: E402
    _derive_schedule,
    _extract_sections,
    parse_course,
    scrape_school,
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# Two sections of one course, exactly as bu.edu serves them.
REAL_SHAPE = """
<h4><strong>FALL 2026</strong> Schedule</h4>
<table>
  <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
  <tr><td>A1</td><td>Erdos</td><td>LSE B01</td><td>TR 2:00 pm-3:15 pm</td><td>Lecture + lab required.</td></tr>
</table>
<h4><strong>FALL 2026</strong> Schedule</h4>
<table>
  <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
  <tr><td>A2</td><td>Erdos</td><td>EPC 207</td><td>TR 3:30 pm-4:45 pm</td><td></td></tr>
</table>
"""


def test_extracts_one_record_per_section():
    sections = _extract_sections(_soup(REAL_SHAPE))
    assert [s["section"] for s in sections] == ["A1", "A2"]
    assert sections[0] == {
        "term": "Fall 2026",
        "section": "A1",
        "instructor_name": "Erdos",
        "meeting_times": "TR 2:00 pm-3:15 pm",
        "location": "LSE B01",
        "notes": "Lecture + lab required.",
    }


def test_term_comes_from_the_preceding_heading():
    """The term is in the <h4>, never in the table — a <th>-based search finds nothing."""
    assert all(s["term"] == "Fall 2026" for s in _extract_sections(_soup(REAL_SHAPE)))


def test_multiple_rows_in_one_table():
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>R1</td><td>Deese</td><td>CGS 523</td><td>TR 11:15 am-12:05 pm</td><td></td></tr>
      <tr><td>R2</td><td>Deese</td><td>CGS 527</td><td>TR 1:25 pm-2:15 pm</td><td></td></tr>
    </table>
    """
    assert [s["section"] for s in _extract_sections(_soup(html))] == ["R1", "R2"]


def test_column_lookup_is_header_driven_not_positional():
    """A reordered / short header row must not shift instructor into location.

    Positional indexing is the failure mode this guards: it would read "STO B50"
    as the instructor here.
    """
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Location</th><th>Instructor</th></tr>
      <tr><td>B1</td><td>STO B50</td><td>Grundy</td></tr>
    </table>
    """
    (s,) = _extract_sections(_soup(html))
    assert s["instructor_name"] == "Grundy"
    assert s["location"] == "STO B50"
    assert s["meeting_times"] is None      # no Schedule column on this page


def test_placeholder_instructors_become_none():
    """"Staff"/"TBA" mean *unassigned*; storing the literal string would show it to students."""
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>A1</td><td>Staff</td><td>CAS 226</td><td>MWF 9:05 am</td><td></td></tr>
      <tr><td>A2</td><td>TBA</td><td>CAS 226</td><td>MWF 10:10 am</td><td></td></tr>
      <tr><td>A3</td><td>Naya</td><td>CAS 226</td><td>MWF 11:15 am</td><td></td></tr>
    </table>
    """
    sections = _extract_sections(_soup(html))
    assert [s["instructor_name"] for s in sections] == [None, None, "Naya"]


def test_empty_cells_become_none_not_empty_string():
    """ARR ("arranged") courses have no room; NULL is the honest value for the DB."""
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>O1</td><td>Von Korff</td><td></td><td>ARR 12:00 am-12:00 am</td><td></td></tr>
    </table>
    """
    (s,) = _extract_sections(_soup(html))
    assert s["location"] is None
    assert s["notes"] is None
    # "ARR 12:00 am-12:00 am" is the registrar's placeholder for "arranged", not a
    # real midnight class — storing it verbatim would show students a fake time.
    assert s["meeting_times"] is None


def test_placeholder_schedules_become_none():
    """The Schedule column's "Staff": ARR/TBA mean no meeting time was published."""
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>A1</td><td>Erdos</td><td>CAS 226</td><td>ARR</td><td></td></tr>
      <tr><td>A2</td><td>Erdos</td><td>CAS 226</td><td>TBA</td><td></td></tr>
      <tr><td>A3</td><td>Erdos</td><td>CAS 226</td><td>MWF 9:05 am-9:55 am</td><td></td></tr>
    </table>
    """
    sections = _extract_sections(_soup(html))
    assert [s["meeting_times"] for s in sections] == [None, None, "MWF 9:05 am-9:55 am"]


def test_a_real_pattern_after_arr_is_kept():
    """The placeholder check is deliberately narrow: only time text may follow it.

    A cell that pairs the token with a genuine pattern still carries a meeting the
    students need, so nulling it would lose data the scrape is here to collect.
    """
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>A1</td><td>Erdos</td><td>CAS 226</td><td>ARR TR 2:00 pm-3:15 pm</td><td></td></tr>
    </table>
    """
    (s,) = _extract_sections(_soup(html))
    assert s["meeting_times"] == "ARR TR 2:00 pm-3:15 pm"


def test_non_schedule_tables_are_skipped():
    html = """
    <table>
      <tr><th>Prerequisite</th><th>Units</th></tr>
      <tr><td>CAS CS 111</td><td>4</td></tr>
    </table>
    """
    assert _extract_sections(_soup(html)) == []


def test_header_only_table_yields_nothing():
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
    </table>
    """
    assert _extract_sections(_soup(html)) == []


def test_repeated_header_row_does_not_shift_columns():
    """Some pages repeat the header row mid-table.

    Headers are read from the first <th> row only. Collecting every <th> in the
    table would map each name to its LAST index, shifting instructor into
    location and silently corrupting every row below the repeat.
    """
    html = """
    <h4>FALL 2026 Schedule</h4>
    <table>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>A1</td><td>Erdos</td><td>LSE B01</td><td>TR 2:00 pm-3:15 pm</td><td></td></tr>
      <tr><th>Section</th><th>Instructor</th><th>Location</th><th>Schedule</th><th>Notes</th></tr>
      <tr><td>B1</td><td>Naya</td><td>EPC 207</td><td>MWF 9:05 am-9:55 am</td><td></td></tr>
    </table>
    """
    sections = _extract_sections(_soup(html))
    assert [s["section"] for s in sections] == ["A1", "B1"]
    assert sections[1]["instructor_name"] == "Naya"
    assert sections[1]["location"] == "EPC 207"
    assert sections[1]["meeting_times"] == "MWF 9:05 am-9:55 am"


def test_page_with_no_schedule_is_not_offered():
    """A catalog page with no schedule block means the course isn't taught that term."""
    sections = _extract_sections(_soup("<h1>Some Course</h1><p>Description.</p>"))
    assert sections == []
    assert _derive_schedule(sections) == ([], [])


# ─── Course-level rollups (what the importer filters on) ─────────────────────


def test_derive_schedule_dedupes_and_preserves_order():
    sections = [
        {"term": "Fall 2026", "instructor_name": "Erdos"},
        {"term": "Fall 2026", "instructor_name": "Erdos"},
        {"term": "Fall 2026", "instructor_name": None},
        {"term": "Fall 2026", "instructor_name": "Naya"},
    ]
    semesters, instructors = _derive_schedule(sections)
    assert semesters == ["Fall 2026"]
    assert instructors == ["Erdos", "Naya"]      # deduped, None dropped, order kept


def test_derive_schedule_skips_blank_terms():
    semesters, _ = _derive_schedule([{"term": "", "instructor_name": "X"}])
    assert semesters == []


# ─── Whole-record integration ────────────────────────────────────────────────


def test_parse_course_carries_sections_and_rollups():
    html = f"""
    <h1>Boston University Academics</h1>
    <h1>Introduction to Analysis of Algorithms</h1>
    <h2>CAS CS 330</h2>
    <dl><dt>Units:</dt><dd>4</dd></dl>
    <p>Undergraduate Prerequisites: CAS CS 112. - Covers algorithm design. Effective Fall 2020, this course carries a Hub unit.</p>
    {REAL_SHAPE}
    """
    rec = parse_course(html, "https://www.bu.edu/academics/cas/courses/cas-cs-330/", "cas")

    assert rec["course_code"] == "CAS CS 330"
    assert rec["credits"] == 4
    assert len(rec["sections"]) == 2
    # Rollups stay consistent with the sections they're derived from — the
    # importer picks courses by semester_offered and would otherwise skip a
    # course whose sections it can see.
    assert rec["semester_offered"] == ["Fall 2026"]
    assert rec["instructors"] == ["Erdos"]
    assert "Effective Fall 2020" not in rec["description"]


# ─── Truncated-crawl regression ──────────────────────────────────────────────


class _TimeoutClient:
    """Stands in for httpx.AsyncClient; every request times out."""

    def __init__(self):
        self.urls: list[str] = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        raise httpx.TimeoutException("timed out", request=None)


def test_listing_timeout_is_recorded_as_truncated_not_end_of_pagination(monkeypatch):
    """A transient listing failure must not read as "past the last page".

    Treating it that way is what silently truncated the previous crawl at CAS
    page ~21 of 113 — 416 courses instead of 2,253, with no error surfaced. The
    FETCH_FAILED sentinel exists to keep those two cases apart.
    """
    async def _no_sleep(_seconds):
        return None

    errors: list[dict] = []
    monkeypatch.setattr("scrape_bu_catalog.asyncio.sleep", _no_sleep)
    monkeypatch.setattr("scrape_bu_catalog._sem", asyncio.Semaphore(1))
    monkeypatch.setattr("scrape_bu_catalog._errors", errors)

    client = _TimeoutClient()
    courses = asyncio.run(scrape_school(client, "cas", seen=set()))

    assert courses == []
    # Two records: the exhausted retries from fetch(), then the loud TRUNCATED
    # marker from the listing walk that refused to call it end-of-pagination.
    assert any("TRUNCATED" in e["error"] for e in errors)
    # Every attempt was against page 1; the walk stopped instead of advancing.
    assert all(u.endswith("/academics/cas/courses/") for u in client.urls)
