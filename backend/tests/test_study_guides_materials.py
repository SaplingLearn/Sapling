"""The documents a guide is made from (services/study_guides/materials.py).

The pure functions are tested directly. The reads run against an in-memory
`documents` stand-in that honours the filters, order and columns the module
sends, holding rows encrypted the way the upload pipeline writes them.
"""
import asyncio
import logging

import pytest

from models.study_guide import MaterialOption
from services.encryption import encrypt, encrypt_json
from services.study_guides import materials
from services.study_guides.scopes import WHOLE_COURSE, Scope

ME, OTHER = "user_me", "user_other"
OFFERING, OTHER_OFFERING = "off-cs", "off-bio"


# ── A tiny PostgREST stand-in ─────────────────────────────────────────────────


def _matches(row: dict, filters: dict) -> bool:
    for column, condition in filters.items():
        value = row.get(column)
        if condition == "is.null":
            if value is not None:
                return False
        elif condition.startswith("eq."):
            if str(value) != condition[3:]:
                return False
        elif condition.startswith("in.("):
            if str(value) not in [v.strip('"') for v in condition[4:-1].split(",")]:
                return False
        else:
            raise AssertionError(f"filter {column}={condition} not modelled")
    return True


class _Documents:
    def __init__(self):
        self.rows: list[dict] = []
        self.selects: list[str] = []
        self.filters: list[dict] = []

    def add(self, doc_id, *, created_at, user_id=ME, offering_id=OFFERING, file_name=None,
            category="lecture_notes", summary=None, concepts=None, text=None, deleted_at=None):
        self.rows.append({
            "id": doc_id, "user_id": user_id, "offering_id": offering_id,
            "file_name": file_name or f"{doc_id}.pdf", "category": category,
            "created_at": created_at, "deleted_at": deleted_at,
            "summary": encrypt(summary) if summary else None,
            "concept_notes": encrypt_json(concepts) if concepts is not None else None,
            "extracted_text": encrypt(text) if text else None,
        })

    async def aselect(self, columns="*", filters=None, order=None, limit=None, **_):
        self.selects.append(columns)
        self.filters.append(filters)
        rows = [r for r in self.rows if _matches(r, filters or {})]
        for part in reversed((order or "").split(",")):
            column = part.split(".")[0]
            if column:
                rows.sort(key=lambda r: r[column])
        return [{c: r.get(c) for c in columns.split(",")} for r in rows][:limit]


@pytest.fixture
def docs(monkeypatch):
    documents = _Documents()

    def table(name):
        assert name == "documents"
        return documents

    monkeypatch.setattr(materials, "table", table)
    return documents


def run(coro):
    return asyncio.run(coro)


def _notes(*names):
    return [{"name": name, "description": f"About {name}."} for name in names]


# ── The class's materials ─────────────────────────────────────────────────────


def test_materials_are_the_students_live_documents_in_the_class_oldest_first(docs):
    docs.add("d-new", created_at="2026-10-02T09:00:00+00:00", category="slides")
    docs.add("d-old", created_at="2026-09-01T09:00:00+00:00", file_name="Week 1.pdf")
    docs.add("d-theirs", created_at="2026-09-02T09:00:00+00:00", user_id=OTHER)
    docs.add("d-bio", created_at="2026-09-03T09:00:00+00:00", offering_id=OTHER_OFFERING)
    docs.add("d-gone", created_at="2026-09-04T09:00:00+00:00",
             deleted_at="2026-09-05T00:00:00+00:00")
    listed = run(materials.alist_materials(ME, OFFERING))
    assert listed == [
        MaterialOption(id="d-old", file_name="Week 1.pdf", category="lecture_notes",
                       created_at="2026-09-01T09:00:00+00:00"),
        MaterialOption(id="d-new", file_name="d-new.pdf", category="slides",
                       created_at="2026-10-02T09:00:00+00:00"),
    ]
    assert docs.selects == ["id,file_name,category,created_at"]  # nothing encrypted


# ── The suggested set (pure) ──────────────────────────────────────────────────


def _material(doc_id, day, category="lecture_notes"):
    return MaterialOption(
        id=doc_id, file_name=f"{doc_id}.pdf", category=category,
        created_at=f"{day}T15:30:00+00:00",
    )


MIDTERM_1 = Scope(kind="exam", id="e1", title="Midterm 1", due_date="2026-09-30")
MIDTERM_2 = Scope(kind="exam", id="e2", title="Midterm 2", due_date="2026-10-30")
HOMEWORK = Scope(kind="assignment", id="h1", title="Homework 4", due_date="2026-10-20")
UNDATED = Scope(kind="assignment", id="h2", title="Reading log", due_date=None)
SCOPES = [WHOLE_COURSE, MIDTERM_1, HOMEWORK, MIDTERM_2, UNDATED]
SHELF = [
    _material("syllabus", "2026-09-01", "syllabus"),
    _material("week1", "2026-09-05"),
    _material("on-midterm-1", "2026-09-30"),
    _material("after-midterm-1", "2026-10-01"),
    _material("on-midterm-2", "2026-10-30", "slides"),
    _material("after-midterm-2", "2026-10-31"),
]


def test_the_whole_course_suggests_every_material():
    assert materials.suggest_materials(SHELF, WHOLE_COURSE, SCOPES) == [m.id for m in SHELF]


def test_the_first_exam_suggests_everything_up_to_its_date_but_the_syllabus():
    assert materials.suggest_materials(SHELF, MIDTERM_1, SCOPES) == ["week1", "on-midterm-1"]


def test_a_later_exam_suggests_what_came_after_the_exam_before_it():
    # The day of the earlier exam is out, the day after is in; the due day
    # itself is in, the day after is out.
    assert materials.suggest_materials(SHELF, MIDTERM_2, SCOPES) == [
        "after-midterm-1", "on-midterm-2",
    ]


def test_the_window_starts_at_the_latest_earlier_exam():
    final = Scope(kind="exam", id="e3", title="Final", due_date="2026-12-15")
    assert materials.suggest_materials(SHELF, final, [*SCOPES, final]) == ["after-midterm-2"]


def test_an_earlier_assignment_does_not_start_the_window():
    # Homework 4 is due between the midterms: only an exam bounds the window.
    assert materials.suggest_materials(SHELF, MIDTERM_2, SCOPES)[0] == "after-midterm-1"
    assert materials.suggest_materials(SHELF, HOMEWORK, SCOPES) == ["after-midterm-1"]


def test_an_empty_window_suggests_every_material_but_the_syllabus():
    early = Scope(kind="exam", id="e0", title="Placement quiz", due_date="2026-08-20")
    everything = [m.id for m in SHELF if m.category != "syllabus"]
    assert materials.suggest_materials(SHELF, early, [*SCOPES, early]) == everything


def test_a_scope_with_no_date_suggests_every_material_but_the_syllabus():
    everything = [m.id for m in SHELF if m.category != "syllabus"]
    assert materials.suggest_materials(SHELF, UNDATED, SCOPES) == everything


def test_the_syllabus_is_never_suggested_for_an_exam_even_inside_the_window():
    shelf = [_material("syllabus", "2026-09-10", "syllabus"), _material("week2", "2026-09-12")]
    assert materials.suggest_materials(shelf, MIDTERM_1, SCOPES) == ["week2"]
    assert materials.suggest_materials([shelf[0]], MIDTERM_1, SCOPES) == []


# ── Source text ───────────────────────────────────────────────────────────────


def test_sources_are_decrypted_labelled_and_in_upload_order(docs):
    docs.add("d2", created_at="2026-09-08T09:00:00+00:00", file_name="Week 2 slides.PPTX",
             summary="Loops repeat work.", concepts=_notes("Loops"), text="for i in range(3)")
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", file_name="Week 1.pdf",
             summary="Variables hold values.",
             concepts=[{"name": "Variables", "description": "Named storage."},
                       {"name": "Types"}, {"description": "no name"}, "not a note"],
             text="x = 1 assigns one to x")
    first, second = run(materials.aload_sources(ME, OFFERING, ["d2", "d1"]))
    assert (first.label, second.label) == ("S1", "S2")
    assert first.source.model_dump() == {"id": "document:d1", "name": "Week 1.pdf", "kind": "PDF"}
    assert second.source.kind == "PPTX"
    assert first.concepts == ["Variables", "Types"]
    assert first.text == (
        "Summary: Variables hold values.\n\n"
        "Key concepts:\n- Variables: Named storage.\n- Types\n\n"
        "x = 1 assigns one to x"
    )
    assert "Loops repeat work." in second.text and "for i in range(3)" in second.text


def test_a_document_that_is_not_the_students_in_this_class_is_left_out(docs):
    docs.add("d-mine", created_at="2026-09-01T09:00:00+00:00", summary="Mine.")
    docs.add("d-theirs", created_at="2026-09-02T09:00:00+00:00", user_id=OTHER, summary="Theirs.")
    docs.add("d-bio", created_at="2026-09-03T09:00:00+00:00", offering_id=OTHER_OFFERING,
             summary="Another class.")
    docs.add("d-gone", created_at="2026-09-04T09:00:00+00:00", summary="Deleted.",
             deleted_at="2026-09-05T00:00:00+00:00")
    sources = run(materials.aload_sources(
        ME, OFFERING, ["d-theirs", "d-bio", "d-gone", "d-missing", "d-mine"],
    ))
    assert [s.source.id for s in sources] == ["document:d-mine"]
    assert sources[0].label == "S1"


def test_an_id_with_list_syntax_stays_one_quoted_value(docs):
    # Unquoted, the comma and parens would reshape the id list.
    run(materials.aload_sources(ME, OFFERING, ["d1", 'x),(y"z']))
    assert docs.filters[-1] == {
        "user_id": f"eq.{ME}",
        "deleted_at": "is.null",
        "offering_id": f"eq.{OFFERING}",
        "id": 'in.("d1","x),(y\\"z")',
    }


def test_a_row_that_does_not_decrypt_is_skipped_with_a_warning(docs, caplog):
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", summary="First.")
    docs.add("d2", created_at="2026-09-02T09:00:00+00:00", summary="Second.")
    docs.add("d3", created_at="2026-09-03T09:00:00+00:00", summary="Third.")
    docs.rows[1]["summary"] = "bm90IGNpcGhlcnRleHQgYXQgYWxsLCBqdXN0IGJhc2U2NCB0ZXh0"
    with caplog.at_level(logging.WARNING, logger=materials.logger.name):
        sources = run(materials.aload_sources(ME, OFFERING, ["d1", "d2", "d3"]))
    assert [(s.label, s.source.id) for s in sources] == [("S1", "document:d1"), ("S2", "document:d3")]
    warnings = [r for r in caplog.records if r.name == materials.logger.name]
    assert len(warnings) == 1 and "d2" in warnings[0].getMessage()
    assert warnings[0].exc_info is None  # no traceback
    assert "bm90" not in sources[0].text + sources[1].text


def test_an_old_row_without_extracted_text_still_reads(docs):
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", concepts=_notes("Recursion"))
    (source,) = run(materials.aload_sources(ME, OFFERING, ["d1"]))
    assert source.text == "Key concepts:\n- Recursion: About Recursion."
    assert source.concepts == ["Recursion"]


def test_a_document_with_nothing_to_read_is_left_out(docs):
    docs.add("d-empty", created_at="2026-09-01T09:00:00+00:00", concepts=[])
    docs.add("d-full", created_at="2026-09-02T09:00:00+00:00", summary="Something.")
    sources = run(materials.aload_sources(ME, OFFERING, ["d-empty", "d-full"]))
    assert [(s.label, s.source.id) for s in sources] == [("S1", "document:d-full")]


def test_one_source_is_cut_at_the_per_source_cap(docs):
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", text="x" * 25_000)
    (source,) = run(materials.aload_sources(ME, OFFERING, ["d1"]))
    assert len(source.text) == materials.MAX_SOURCE_CHARS == 10_000


def test_many_sources_share_the_total_budget_evenly(docs):
    for n in range(12):
        docs.add(f"d{n:02d}", created_at=f"2026-09-{n + 1:02d}T09:00:00+00:00", text="y" * 25_000)
    sources = run(materials.aload_sources(ME, OFFERING, [f"d{n:02d}" for n in range(12)]))
    assert len(sources) == 12
    assert {len(s.text) for s in sources} == {5_000}  # the last is read as much as the first
    assert sum(len(s.text) for s in sources) <= materials.MAX_TOTAL_CHARS == 60_000


def test_at_most_thirty_documents_are_read_and_the_last_given_are_the_ones_kept(docs):
    """Callers give ids oldest first, with what is new to a guide at the end:
    past the budget it is the oldest that are left out, never the new."""
    ids = [f"d{n:02d}" for n in range(40)]
    for n, doc_id in enumerate(ids):
        docs.add(doc_id, created_at=f"2026-09-01T09:{n:02d}:00+00:00", text="z" * 5_000)
    sources = run(materials.aload_sources(ME, OFFERING, ids + ids))
    assert [s.source.id for s in sources] == [f"document:{i}" for i in ids[10:]]
    assert [s.label for s in sources] == [f"S{n}" for n in range(1, 31)]
    assert sum(len(s.text) for s in sources) <= materials.MAX_TOTAL_CHARS


def test_an_id_too_long_to_be_a_document_is_never_sent_to_the_database(docs):
    longest, too_long = "d" * 100, "d" * 101
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", concepts=_notes("Loops"))
    docs.add(longest, created_at="2026-09-02T09:00:00+00:00", concepts=_notes("Functions"))

    concepts = run(materials.aload_concepts(ME, OFFERING, ["x" * 5_000, "d1", too_long, longest]))

    assert concepts == ["Loops", "Functions"]
    assert docs.filters[-1]["id"] == f'in.("d1","{longest}")'
    # Nothing but over-long ids: no read at all.
    reads = len(docs.selects)
    assert run(materials.aload_sources(ME, OFFERING, [too_long])) == []
    assert len(docs.selects) == reads


@pytest.mark.parametrize("count, expected", [(0, 10_000), (1, 10_000), (6, 10_000), (7, 8_571), (30, 2_000)])
def test_the_share_of_the_budget_per_source(count, expected):
    assert materials.source_chars(count) == expected
    assert count * materials.source_chars(count) <= materials.MAX_TOTAL_CHARS


@pytest.mark.parametrize("file_name, kind", [
    ("notes.pdf", "PDF"), ("Essay.final.docx", "DOCX"), ("Deck.PPTX", "PPTX"),
    ("README", "FILE"), ("trailing.", "FILE"), ("odd.name with spaces", "FILE"),
    ("archive.extension", "FILE"),
])
def test_a_source_kind_is_the_file_extension(docs, file_name, kind):
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", file_name=file_name, summary="Text.")
    (source,) = run(materials.aload_sources(ME, OFFERING, ["d1"]))
    assert source.source.kind == kind


def test_no_ids_reads_nothing(docs):
    assert run(materials.aload_sources(ME, OFFERING, [])) == []
    assert run(materials.aload_concepts(ME, OFFERING, [])) == []
    assert docs.selects == []


def test_concepts_come_in_upload_order_without_reading_the_text(docs):
    docs.add("d2", created_at="2026-09-08T09:00:00+00:00", concepts=_notes("Loops", "Variables"))
    docs.add("d1", created_at="2026-09-01T09:00:00+00:00", concepts=_notes("Variables", "Types"),
             text="long text")
    docs.add("d-theirs", created_at="2026-09-02T09:00:00+00:00", user_id=OTHER,
             concepts=_notes("Their concept"))
    docs.add("d-bad", created_at="2026-09-03T09:00:00+00:00", concepts=_notes("Unreadable"))
    docs.rows[-1]["concept_notes"] = "bm90IGNpcGhlcnRleHQgYXQgYWxsLCBqdXN0IGJhc2U2NCB0ZXh0"
    names = run(materials.aload_concepts(ME, OFFERING, ["d2", "d-theirs", "d-bad", "d1"]))
    assert names == ["Variables", "Types", "Loops", "Variables"]
    assert docs.selects == ["id,concept_notes"]


# ── New lectures since a guide was made ───────────────────────────────────────


def test_lecture_documents_are_the_students_live_lectures_and_slides(docs):
    docs.add("d-notes", created_at="2026-09-01T09:00:00+00:00", category="lecture_notes")
    docs.add("d-slides", created_at="2026-09-02T09:00:00+00:00", category="slides",
             offering_id=OTHER_OFFERING)
    docs.add("d-reading", created_at="2026-09-03T09:00:00+00:00", category="reading")
    docs.add("d-theirs", created_at="2026-09-04T09:00:00+00:00", user_id=OTHER)
    docs.add("d-gone", created_at="2026-09-05T09:00:00+00:00",
             deleted_at="2026-09-06T00:00:00+00:00")
    assert run(materials.alist_lecture_docs(ME)) == [
        {"id": "d-notes", "offering_id": OFFERING, "created_at": "2026-09-01T09:00:00+00:00"},
        {"id": "d-slides", "offering_id": OTHER_OFFERING, "created_at": "2026-09-02T09:00:00+00:00"},
    ]


LECTURES = [
    {"id": "before", "offering_id": OFFERING, "created_at": "2026-10-01T08:00:00+00:00"},
    {"id": "same-instant", "offering_id": OFFERING, "created_at": "2026-10-01T12:00:00+00:00"},
    {"id": "after", "offering_id": OFFERING, "created_at": "2026-10-01T12:00:00.5+00:00"},
    {"id": "after-in-guide", "offering_id": OFFERING, "created_at": "2026-10-02T08:00:00+00:00"},
    {"id": "after-other-class", "offering_id": OTHER_OFFERING, "created_at": "2026-10-03T08:00:00+00:00"},
    {"id": "later", "offering_id": OFFERING, "created_at": "2026-10-04T08:00:00+00:00"},
]


def test_new_materials_are_this_classes_lectures_added_after_the_guide():
    new = materials.new_material_ids(
        LECTURES, offering_id=OFFERING, material_ids=["before", "after-in-guide"],
        since="2026-10-01T12:00:00+00:00",
    )
    assert new == ["after", "later"]


def test_new_materials_compare_instants_not_text():
    # The same instant written in another offset: 14:00+02:00 is 12:00 UTC.
    new = materials.new_material_ids(
        LECTURES, offering_id=OFFERING, material_ids=[], since="2026-10-01T14:00:00+02:00",
    )
    assert new == ["after", "after-in-guide", "later"]


def test_a_guide_that_was_never_made_has_no_new_materials():
    assert materials.new_material_ids(
        LECTURES, offering_id=OFFERING, material_ids=[], since=None,
    ) == []
