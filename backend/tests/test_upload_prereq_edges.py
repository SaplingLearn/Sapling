"""Upload prerequisite edges (learning loop spec §13 A118).

A live walkthrough uploaded a 10-slide hash-tables deck: nine concept nodes,
zero `graph_edges`, and a learning plan that put Collision Resolution first and
Hash Table / Hash Function 3rd and 5th — the planner's fringe falls back to node
id order when there are no prerequisites. Pins, in order:

- the flag: `upload_prereq_edges` is resolved ONCE per upload, for the
  uploading student (off with no student), and passed down;
- the extraction: flag off, the model request is byte-identical to the
  pre-A118 one (system prompt, schema, message — pinned) and nothing reads the
  course's concepts; flag on, the prerequisite instructions, schema and
  course-concepts context. The relation list is a default-empty field with a
  LOCAL cap (clip, never a retry);
- `resolve_prerequisites`: scope, self-loops, the document rule, duplicates,
  already-present edges, the canonical-order cycle break, the transitive
  reduction and the per-document cap;
- `write_document_prerequisites`: writes through `apply_graph_update`, oriented
  by EDGE_PREREQ_SOURCE_IS_PREREQ, without reading the flag; a re-upload is
  idempotent; the write is serialized per (student, course);
- both upload routes wire the resolution, the variant and the write;
- the planner orders a prerequisite before its dependent once the edges exist.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import itertools
import json
import logging
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart

import services.concept_prereqs as cp
from agents import WORKER_LIMITS
from agents._providers import clear_function_handlers, model_for, register_function_handler
from agents.concept_extraction import (
    EXISTING_CONCEPTS_PROMPT_MAX,
    MAX_PREREQUISITE_RELATIONS,
    PREREQUISITE_INSTRUCTIONS,
    BaseConceptList,
    Concept,
    ConceptList,
    PrerequisiteRelation,
    build_message,
    concept_extraction_agent,
    extraction_run_args,
)
from agents.deps import SaplingDeps
from learning import planner
from learning.params import BKT_L0, BKT_PROFICIENT
from main import app

client = TestClient(app)

FLAG_ENV = "SAPLING_FLAG_UPLOAD_PREREQ_EDGES"
USER, COURSE = "u1", "c-1"

# The concept extraction request as it was before A118, captured from
# cf9dc75c (the commit before it) by running that agent in function mode: the
# flag-off variant must send exactly this. Change these only with a recorded
# eval behind the change.
PRE_A118_SYSTEM_PROMPT = (
    "You extract key concepts from a student document. Each concept becomes a "
    "node in the student's knowledge graph and must read as a standalone topic."
    "\n\n- name: short Title Case noun phrase ('Linear Regression', 'Big-O "
    "Analysis'). Never a problem number, week label, or administrative item.\n"
    "- description: 1-2 sentences in the document's context.\n"
    "- importance in [0, 1]; order the list by importance desc.\n"
    "- 1-30 concepts. Prefer 4-12 for lectures/readings/study guides, up to ~15 "
    "for whole-course syllabi, 1-8 for narrow assignments."
)
PRE_A118_PROMPT_SHA256 = "80a7962e078a1faeddfb6b66227853f8fb43f707ad47499a9ea77c4c2a35957b"
PRE_A118_PROMPT_VERSION = "80a7962e078a"  # the agent metadata: the sha's first 12
PRE_A118_OUTPUT_TOOL = ("final_result", "The final response which ends this conversation")
# sha256 of the output tool's JSON schema (json.dumps, sort_keys=True).
PRE_A118_SCHEMA_SHA256 = "28cd48497ca87a194eb030d792e56453c582e4985769938571da1bcf1f21763f"
# The flag-on instructions, pinned so an edit to them is a deliberate one.
PREREQUISITE_INSTRUCTIONS_SHA256 = "ce6710fb00f9aa7fe8e3ecd278d30e57a9a54cafc1731ebf7f2fc5189e8d14ee"
PREREQ_PROMPT_VERSION = "5703f01ef1f6"  # sha256(system prompt + "\n\n" + instructions)[:12]

# The walkthrough deck: (name, importance as the extraction scored it, node id).
# The ids sort Collision Resolution 1st, Hash Table 3rd and Hash Function 5th —
# the order the edge-less plan showed.
DECK = [
    ("Hash Table", 0.95, "n3-ht"),
    ("Hash Function", 0.9, "n5-hf"),
    ("Collision Resolution", 0.85, "n1-cr"),
    ("Load Factor", 0.75, "n4-lf"),
    ("Separate Chaining", 0.7, "n2-sc"),
    ("Open Addressing", 0.7, "n6-oa"),
    ("Linear Probing", 0.6, "n7-lp"),
    ("Resizing and Rehashing", 0.55, "n8-rr"),
    ("Tombstone Deletion", 0.4, "n9-td"),
]
# What a model plausibly sends for it: nine sound direct links plus the noise
# the rules exist for.
DECK_RELATIONS = [
    ("Hash Function", "Hash Table"),
    ("Hash Table", "Collision Resolution"),
    ("Hash Table", "Load Factor"),
    ("Collision Resolution", "Separate Chaining"),
    ("Collision Resolution", "Open Addressing"),
    ("Open Addressing", "Linear Probing"),
    ("Linear Probing", "Tombstone Deletion"),
    ("Load Factor", "Resizing and Rehashing"),
    ("Hash Function", "Resizing and Rehashing"),  # redundant: HF->HT->LF->RR
    ("Hash Table", "Linear Probing"),  # redundant: HT->CR->OA->LP
    ("Collision Resolution", "Hash Table"),  # contradicts HT->CR: a cycle
    ("Hashing Basics", "Hash Table"),  # names no concept: unknown
    ("load factor", " Load  Factor "),  # the same concept twice: a self-loop
]
DECK_EDGES = (
    ("Hash Table", "Collision Resolution"),
    ("Hash Table", "Load Factor"),
    ("Hash Function", "Hash Table"),
    ("Collision Resolution", "Open Addressing"),
    ("Collision Resolution", "Separate Chaining"),
    ("Load Factor", "Resizing and Rehashing"),
    ("Open Addressing", "Linear Probing"),
    ("Linear Probing", "Tombstone Deletion"),
)


def _concepts(pairs, relations=()) -> ConceptList:
    return ConceptList(
        concepts=[Concept(name=n, description="d", importance=i) for n, i, *_ in pairs],
        prerequisites=[PrerequisiteRelation(prerequisite=p, dependent=d) for p, d in relations],
    )


def _resolve(relations, pairs=DECK, *, course=None, existing=(), max_edges=None):
    kw = {} if max_edges is None else {"max_edges": max_edges}
    return cp.resolve_prerequisites(
        relations,
        document_concepts=[(n, i) for n, i, *_ in pairs],
        course_concepts=course if course is not None else [n for n, *_ in pairs],
        existing_edges=existing,
        **kw,
    )


def _reasons(res) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for reason, _, _ in res.dropped:
        out[reason] += 1
    return dict(out)


# ── An in-memory PostgREST stand-in ──────────────────────────────────────────


class _FakeDB:
    """graph_nodes / graph_edges with the semantics the code relies on: eq/neq
    filters, `order`, limit/offset paging, and an upsert that MERGES on the
    conflict columns the way PostgREST's merge-duplicates does — every payload
    column overwritten, the id included. That last part is what makes a
    rewritten edge observable (its id changes)."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self.upserts: dict[str, list[dict]] = defaultdict(list)
        self._clock = itertools.count()

    def add_node(self, node_id: str, name: str, *, user=USER, course=COURSE, tier="unexplored"):
        self.rows["graph_nodes"].append({
            "id": node_id, "user_id": user, "course_id": course, "concept_name": name,
            "mastery_score": 0.0, "mastery_tier": tier, "times_studied": 0,
            "created_at": f"2026-11-07T00:00:{next(self._clock):02d}",
        })

    def table(self, name: str):
        return _FakeTable(self, name)

    def edges(self, user=USER) -> list[dict]:
        return [e for e in self.rows["graph_edges"] if e["user_id"] == user]


class _FakeTable:
    def __init__(self, db: _FakeDB, name: str) -> None:
        self.db, self.name = db, name

    @staticmethod
    def _matches(row: dict, filters: dict | None) -> bool:
        for col, cond in (filters or {}).items():
            op, _, value = cond.partition(".")
            have = "" if row.get(col) is None else str(row.get(col))
            if (op == "eq" and have != value) or (op == "neq" and have == value):
                return False
        return True

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None, timeout=None):
        rows = [dict(r) for r in self.db.rows[self.name] if self._matches(r, filters)]
        for part in reversed((order or "").split(",")):
            if part:
                col, _, direction = part.partition(".")
                rows.sort(key=lambda r: str(r.get(col) or ""), reverse=direction == "desc")
        rows = rows[offset or 0:]
        return rows[:limit] if limit else rows

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None,
                          timeout=None):
        everything = self.select(columns, filters, order)
        page = everything[offset or 0:]
        return (page[:limit] if limit else page), len(everything)

    def upsert(self, data, on_conflict="id", **_kw):
        keys = on_conflict.split(",")
        out = []
        for row in data if isinstance(data, list) else [data]:
            self.db.upserts[self.name].append(dict(row))
            hit = next((r for r in self.db.rows[self.name]
                        if all(r.get(k) == row.get(k) for k in keys)), None)
            if hit is None:
                hit = dict(row)
                self.db.rows[self.name].append(hit)
            else:
                hit.update(row)
            out.append(dict(hit))
        return out


@pytest.fixture
def db(monkeypatch):
    """One fake behind every reader and writer on the path: this module, the
    graph service (apply_graph_update) and the loop route's plan reader."""
    import routes.learn_loop as learn_loop
    import services.graph_service as gs

    fake = _FakeDB()
    for module in (cp, gs, learn_loop):
        monkeypatch.setattr(module, "table", fake.table)
    return fake


def _seed_deck(fake: _FakeDB, pairs=DECK) -> None:
    for name, _imp, node_id in pairs:
        fake.add_node(node_id, name)


def _named_edges(fake: _FakeDB) -> set[tuple[str, str]]:
    names = {n["id"]: n["concept_name"] for n in fake.rows["graph_nodes"]}
    return {
        (names[e["source_node_id"]], names[e["target_node_id"]])
        for e in fake.edges() if e["relationship_type"] == "prerequisite"
    }


# ── The flag: one resolution per upload ──────────────────────────────────────


@pytest.fixture
def flag_reads(monkeypatch):
    """Every resolution of upload_prereq_edges, by user id: a spy on
    feature_flags.explain, which every flag_on/flag_variant goes through."""
    from services import feature_flags as ff

    real, reads = ff.explain, []

    def spy(key, user_id, *args, **kwargs):
        if key == cp.UPLOAD_PREREQ_EDGES_FLAG:
            reads.append(user_id)
        return real(key, user_id, *args, **kwargs)

    monkeypatch.setattr(ff, "explain", spy)
    return reads


def test_the_flag_is_per_student_and_off_without_one(monkeypatch, flag_reads):
    from services import feature_flags as ff

    monkeypatch.setenv(FLAG_ENV, "on")
    assert cp.upload_prereqs_on("u1") is True
    # No student is known: off, without even asking the flag store.
    assert cp.upload_prereqs_on(None) is False
    assert cp.upload_prereqs_on("") is False
    assert flag_reads == ["u1"]

    monkeypatch.delenv(FLAG_ENV)
    snap = ff.Snapshot(  # default on, one user ruled off
        flags={"upload_prereq_edges": {"key": "upload_prereq_edges", "default_variant": "on",
                                       "rollout_percent": 0, "rollout_variant": None}},
        targets={"upload_prereq_edges": [{"flag_key": "upload_prereq_edges", "target_type": "user",
                                          "target_id": "u-out", "variant": "off"}]},
    )
    monkeypatch.setattr(ff, "_get_snapshot", lambda fresh=False: snap)
    assert cp.upload_prereqs_on("u1") is True
    assert cp.upload_prereqs_on("u-out") is False
    assert cp.upload_prereqs_on(None) is False  # a stored default never reaches no-one


# ── The extraction request, per variant ──────────────────────────────────────

_TEXT = (
    "Hash tables. This sample body gives the upload fixture enough extracted "
    "text to look like a document that was actually read successfully."
)


def _sha256(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _deck_payload() -> dict:
    """What a model (or the E2E handler) answers: the deck and its relations.
    The same payload serves both variants, as the E2E handler's does."""
    return {
        "concepts": [{"name": n, "description": "d", "importance": i} for n, i, _ in DECK],
        "prerequisites": [{"prerequisite": p, "dependent": d} for p, d in DECK_RELATIONS],
    }


def _request(monkeypatch, *, prerequisites: bool, existing=()):
    """Run the real agent in function mode and capture what it sends the model:
    system prompt parts, user prompt, run instructions, output tool + schema."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    seen: dict = {}

    def handler(messages, info):
        parts = [p for m in messages for p in getattr(m, "parts", [])]
        tool = info.output_tools[0]
        seen.update(
            system=[p.content for p in parts if p.part_kind == "system-prompt"],
            user=[p.content for p in parts if p.part_kind == "user-prompt"],
            instructions=info.instructions,
            tool=(tool.name, tool.description),
            schema=tool.parameters_json_schema,
        )
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=_deck_payload())])

    clear_function_handlers()
    register_function_handler("concepts", handler)
    try:
        with concept_extraction_agent.override(model=model_for("concepts")):
            result = concept_extraction_agent.run_sync(
                **extraction_run_args(
                    _TEXT, prerequisites=prerequisites, existing_concepts=existing,
                ),
                deps=SaplingDeps(user_id=USER, course_id=COURSE, supabase=None, request_id="r"),
            )
    finally:
        clear_function_handlers()
    return seen, result


def test_flag_off_request_is_byte_identical_to_pre_a118(monkeypatch):
    seen, result = _request(monkeypatch, prerequisites=False, existing=["Arrays"])
    assert seen["system"] == [PRE_A118_SYSTEM_PROMPT]
    assert _sha256(seen["system"][0]) == PRE_A118_PROMPT_SHA256
    assert seen["instructions"] is None
    assert seen["user"] == [_TEXT]  # the bare text: the course's concepts are not sent
    assert seen["tool"] == PRE_A118_OUTPUT_TOOL
    assert _sha256(seen["schema"]) == PRE_A118_SCHEMA_SHA256
    assert result.metadata == {"prompt_version": PRE_A118_PROMPT_VERSION,
                               "agent": "concept_extraction"}
    # The answer is read through the pre-A118 schema: relations are not kept.
    assert type(result.output) is BaseConceptList
    assert not hasattr(result.output, "prerequisites")
    assert extraction_run_args(_TEXT, prerequisites=False, existing_concepts=["Arrays"]) == {
        "user_prompt": _TEXT,
    }


def test_flag_on_request_adds_the_instructions_the_schema_and_the_context(monkeypatch):
    seen, result = _request(monkeypatch, prerequisites=True, existing=["Linked Lists", "Arrays"])
    assert seen["system"] == [PRE_A118_SYSTEM_PROMPT]  # the instructions come after it
    assert seen["instructions"] == PREREQUISITE_INSTRUCTIONS
    assert _sha256(PREREQUISITE_INSTRUCTIONS) == PREREQUISITE_INSTRUCTIONS_SHA256
    assert seen["user"] == [build_message(_TEXT, ["Linked Lists", "Arrays"])]
    assert "\n- Arrays\n- Linked Lists\n\nDocument:\n" + _TEXT in seen["user"][0]
    assert set(seen["schema"]["properties"]) == {"concepts", "prerequisites"}
    assert _sha256(seen["schema"]) != PRE_A118_SCHEMA_SHA256
    assert result.metadata == {"prompt_version": PREREQ_PROMPT_VERSION,
                               "agent": "concept_extraction"}
    assert type(result.output) is ConceptList
    assert [(r.prerequisite, r.dependent) for r in result.output.prerequisites] == DECK_RELATIONS


# ── The extraction output and message ────────────────────────────────────────


def test_relations_default_to_empty_so_pre_a118_payloads_still_validate():
    """Every recorded concept_extraction cassette predates the field."""
    c = ConceptList(concepts=[{"name": "A", "description": "d", "importance": 0.5}])
    assert c.prerequisites == []


def test_the_relation_list_cap_is_a_local_clip_not_a_retry(caplog):
    many = [{"prerequisite": f"A{i}", "dependent": f"B{i}"}
            for i in range(MAX_PREREQUISITE_RELATIONS + 5)]
    with caplog.at_level(logging.WARNING, logger="sapling.agents.bounded"):
        c = ConceptList(concepts=[{"name": "A", "description": "d", "importance": 0.5}],
                        prerequisites=many)
    assert len(c.prerequisites) == MAX_PREREQUISITE_RELATIONS
    assert c.prerequisites[0].prerequisite == "A0"  # model order, like a decode-time cap
    assert "concepts.prerequisites" in caplog.text


def test_message_is_the_bare_text_without_existing_concepts():
    assert build_message("doc text") == "doc text"
    assert build_message("doc text", ["", "   "]) == "doc text"


def test_message_lists_existing_concepts_deduped_sorted_and_capped():
    names = ["Zeta", "alpha", "Alpha", "  Mid\n Term  "] + [f"C{i:03d}" for i in range(200)]
    msg = build_message("doc text", names)
    listed = [line[2:] for line in msg.splitlines() if line.startswith("- ")]
    assert len(listed) == EXISTING_CONCEPTS_PROMPT_MAX
    # The caller's order picks WHICH (most recent first); the listing is sorted.
    assert {"Zeta", "alpha", "Mid Term"} <= set(listed)
    assert "Alpha" not in listed and "C199" not in listed
    assert listed == sorted(listed, key=str.casefold)
    assert msg.endswith("\n\nDocument:\ndoc text")


def test_existing_concept_read_is_most_recent_first_and_skips_the_subject_root(db):
    db.add_node("n-old", "Arrays")
    db.add_node("n-root", "CS101", tier="subject_root")
    db.add_node("n-new", "Linked Lists")
    db.add_node("n-other", "Elsewhere", course="c-2")
    assert cp.course_concept_names(USER, COURSE) == ["Linked Lists", "Arrays"]
    assert cp.course_concept_names(USER, None) == []


def test_existing_concept_read_failure_means_no_context_not_a_failed_upload(monkeypatch):
    def boom(_name):
        raise RuntimeError("db down")

    monkeypatch.setattr(cp, "table", boom)
    assert cp.course_concept_names(USER, COURSE) == []


# ── resolve_prerequisites: the rules ─────────────────────────────────────────


def test_the_walkthrough_deck_resolves_to_its_direct_prerequisites():
    res = _resolve(DECK_RELATIONS)
    assert res.edges == DECK_EDGES
    assert res.already_present == ()
    assert _reasons(res) == {"unknown": 1, "self_loop": 1, "cycle": 1, "redundant": 2}
    assert ("cycle", "Collision Resolution", "Hash Table") in res.dropped


def test_unknown_names_are_dropped_and_names_resolve_like_graph_dedup():
    res = _resolve([("hash  TABLE", "linear probing"), ("Ghost", "Hash Table"),
                    ("Hash Table", "")])
    assert res.edges == (("Hash Table", "Linear Probing"),)  # the graph's stored names
    assert res.dropped == (("unknown", "Ghost", "Hash Table"), ("unknown", "Hash Table", ""))


def test_self_loops_are_dropped():
    res = _resolve([("Hash Table", "hash table")])
    assert res.edges == () and _reasons(res) == {"self_loop": 1}


def test_existing_course_concepts_are_endpoints_but_one_side_must_be_this_document():
    doc = [("Linked Lists", 0.9)]
    course = ["Arrays", "Pointers", "Linked Lists"]
    res = _resolve([("Arrays", "Linked Lists"), ("Pointers", "Arrays")], doc, course=course)
    assert res.edges == (("Arrays", "Linked Lists"),)  # attaches the upload to earlier material
    assert res.dropped == (("off_document", "Pointers", "Arrays"),)


def test_duplicates_are_dropped():
    res = _resolve([("Hash Table", "Load Factor"), ("hash table", "load factor")])
    assert res.edges == (("Hash Table", "Load Factor"),) and _reasons(res) == {"duplicate": 1}


def test_a_two_cycle_keeps_the_more_foundational_prerequisite_in_either_model_order():
    for relations in (
        [("Hash Table", "Hash Function"), ("Hash Function", "Hash Table")],
        [("Hash Function", "Hash Table"), ("Hash Table", "Hash Function")],
    ):
        res = _resolve(relations)
        assert res.edges == (("Hash Table", "Hash Function"),)  # 0.95 outranks 0.9
        assert res.dropped == (("cycle", "Hash Function", "Hash Table"),)


def test_a_three_cycle_drops_the_edge_out_of_the_least_central_concept():
    res = _resolve([("Load Factor", "Hash Table"), ("Hash Table", "Hash Function"),
                    ("Hash Function", "Load Factor")])
    assert res.edges == (("Hash Table", "Hash Function"), ("Hash Function", "Load Factor"))
    assert res.dropped == (("cycle", "Load Factor", "Hash Table"),)


def test_a_cycle_through_an_earlier_course_concept_keeps_it_the_prerequisite():
    """Earlier course material outranks every concept of the new document,
    however central the document says its own concept is."""
    doc = [("Linked Lists", 1.0)]
    course = ["Arrays", "Linked Lists"]
    for relations in ([("Linked Lists", "Arrays"), ("Arrays", "Linked Lists")],
                      [("Arrays", "Linked Lists"), ("Linked Lists", "Arrays")]):
        res = _resolve(relations, doc, course=course)
        assert res.edges == (("Arrays", "Linked Lists"),)
        assert res.dropped == (("cycle", "Linked Lists", "Arrays"),)


def test_an_existing_edge_wins_over_a_new_contradiction():
    res = _resolve([("Load Factor", "Hash Table")], existing=[("Hash Table", "Load Factor")])
    assert res.edges == () and res.dropped == (("cycle", "Load Factor", "Hash Table"),)


def test_the_outcome_depends_on_the_set_of_relations_not_their_order():
    relations = DECK_RELATIONS[:11]
    expected = _resolve(relations)
    for permutation in (relations[::-1], relations[3:] + relations[:3], sorted(relations)):
        assert _resolve(permutation).edges == expected.edges


def test_a_shortcut_implied_by_a_longer_path_is_redundant():
    res = _resolve([("Hash Table", "Collision Resolution"), ("Hash Table", "Open Addressing"),
                    ("Collision Resolution", "Open Addressing")])
    assert res.edges == (("Hash Table", "Collision Resolution"),
                         ("Collision Resolution", "Open Addressing"))
    assert res.dropped == (("redundant", "Hash Table", "Open Addressing"),)


def test_redundancy_counts_the_course_existing_edges_too():
    res = _resolve([("Hash Table", "Open Addressing")],
                   existing=[("Hash Table", "Collision Resolution"),
                             ("Collision Resolution", "Open Addressing")])
    assert res.edges == () and _reasons(res) == {"redundant": 1}


def test_an_edge_the_course_already_has_is_not_rewritten():
    res = _resolve([("Hash Table", "Load Factor"), ("Load Factor", "Resizing and Rehashing")],
                   existing=[("hash table", "LOAD FACTOR")])
    assert res.already_present == (("Hash Table", "Load Factor"),)
    assert res.edges == (("Load Factor", "Resizing and Rehashing"),)
    assert res.dropped == ()


def test_the_cap_keeps_the_highest_ranked_edges():
    relations = [("Tombstone Deletion", "Separate Chaining"), ("Hash Table", "Load Factor"),
                 ("Hash Function", "Linear Probing")]
    res = _resolve(relations, max_edges=2)
    assert res.edges == (("Hash Table", "Load Factor"), ("Hash Function", "Linear Probing"))
    assert res.dropped == (("cap", "Tombstone Deletion", "Separate Chaining"),)
    assert cp.MAX_PREREQ_EDGES_PER_DOCUMENT == 30


def test_the_default_cap_binds_a_runaway_output():
    names = [(f"Concept {i:02d}", 1 - i / 100) for i in range(31)]
    chain = [(names[i][0], names[i + 1][0]) for i in range(30)]
    res = _resolve(chain + [chain[0]], names)
    assert len(res.edges) == cp.MAX_PREREQ_EDGES_PER_DOCUMENT
    assert _reasons(res) == {"duplicate": 1}  # 30 links fit; nothing past the cap
    longer = [(f"Concept {i:02d}", 1 - i / 100) for i in range(40)]
    res = _resolve([(longer[i][0], longer[i + 1][0]) for i in range(39)], longer)
    assert len(res.edges) == 30 and _reasons(res) == {"cap": 9}


# ── write_document_prerequisites ─────────────────────────────────────────────


@pytest.mark.parametrize("source_is_prereq", [True, False])
def test_edge_payload_follows_edge_prereq_source_is_prereq(monkeypatch, source_is_prereq):
    monkeypatch.setattr(cp, "EDGE_PREREQ_SOURCE_IS_PREREQ", source_is_prereq)
    edge = cp.edge_payload("Hash Function", "Hash Table")
    expected = ("Hash Function", "Hash Table") if source_is_prereq else ("Hash Table", "Hash Function")
    assert (edge["source"], edge["target"]) == expected
    assert edge["relationship_type"] == "prerequisite"
    assert edge["strength"] == cp.UPLOAD_PREREQ_STRENGTH


def test_the_write_never_reads_the_flag(db, monkeypatch):
    """The upload resolved upload_prereq_edges once, before extraction; the
    write is only called when that answer was yes and must not ask again."""
    _seed_deck(db)
    with patch.object(cp, "flag_on", side_effect=AssertionError("re-read")) as flag:
        assert cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS)) == 8
    flag.assert_not_called()


def test_the_write_goes_through_apply_graph_update_oriented(db):
    _seed_deck(db)
    with patch.object(cp, "apply_graph_update", wraps=cp.apply_graph_update) as agu:
        written = cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS))
    assert written == 8
    agu.assert_called_once()
    (user, update), kwargs = agu.call_args
    assert user == USER and kwargs == {"course_id": COURSE}
    assert set(update) == {"new_edges"}
    assert [(e["source"], e["target"]) for e in update["new_edges"]] == list(DECK_EDGES)
    # In the table: source = prerequisite, target = dependent (spec §3.1).
    ids = {name: node_id for name, _imp, node_id in DECK}
    rows = {(e["source_node_id"], e["target_node_id"]) for e in db.edges()}
    assert rows == {(ids[p], ids[d]) for p, d in DECK_EDGES}
    assert {e["relationship_type"] for e in db.edges()} == {"prerequisite"}


def test_with_the_convention_flipped_the_write_puts_the_dependent_first(db, monkeypatch):
    monkeypatch.setattr(cp, "EDGE_PREREQ_SOURCE_IS_PREREQ", False)
    _seed_deck(db)
    cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, [("Hash Function", "Hash Table")]))
    [edge] = db.edges()
    assert (edge["source_node_id"], edge["target_node_id"]) == ("n3-ht", "n5-hf")


def test_reupload_is_idempotent(db, monkeypatch):
    _seed_deck(db)
    concepts = _concepts(DECK, DECK_RELATIONS)
    assert cp.write_document_prerequisites(USER, COURSE, concepts) == 8
    first = sorted((e["id"], e["source_node_id"], e["target_node_id"]) for e in db.edges())
    upserts = len(db.upserts["graph_edges"])

    with patch.object(cp, "apply_graph_update", wraps=cp.apply_graph_update) as agu:
        assert cp.write_document_prerequisites(USER, COURSE, concepts) == 0
    agu.assert_not_called()  # nothing new: the merge-upsert would have re-keyed the rows
    assert len(db.upserts["graph_edges"]) == upserts
    assert sorted((e["id"], e["source_node_id"], e["target_node_id"]) for e in db.edges()) == first


def test_a_second_document_attaches_to_the_first_and_never_contradicts_it(db, monkeypatch):
    _seed_deck(db)
    cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS))
    db.add_node("n10-cuckoo", "Cuckoo Hashing")
    later = _concepts([("Cuckoo Hashing", 0.9), ("Linear Probing", 0.5)],
                      [("Open Addressing", "Cuckoo Hashing"),  # an earlier concept, not in this doc
                       ("Linear Probing", "Open Addressing"),  # contradicts the first doc's OA->LP
                       ("Hash Table", "Cuckoo Hashing")])  # implied: HT->CR->OA->Cuckoo
    assert cp.write_document_prerequisites(USER, COURSE, later) == 1
    assert _named_edges(db) == set(DECK_EDGES) | {("Open Addressing", "Cuckoo Hashing")}


def test_the_write_holds_the_course_lock(db, monkeypatch):
    """Two documents uploaded together must not both pass the cycle check."""
    _seed_deck(db)
    held = []

    def spy(*args, **kwargs):
        held.append(cp._lock_for(USER, COURSE).locked())

    with patch.object(cp, "apply_graph_update", side_effect=spy):
        cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS))
    assert held == [True]
    assert not cp._lock_for(USER, COURSE).locked()


def test_a_failed_write_is_logged_never_raised(db, monkeypatch, caplog):
    _seed_deck(db)
    with patch.object(cp, "apply_graph_update", side_effect=RuntimeError("pgrst down")), \
         caplog.at_level(logging.ERROR, logger=cp.__name__):
        assert cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS)) == 0
    assert "upload prerequisites failed" in caplog.text
    assert not cp._lock_for(USER, COURSE).locked()


def test_drops_are_logged_with_a_sample(db, monkeypatch, caplog):
    _seed_deck(db)
    with caplog.at_level(logging.INFO, logger=cp.__name__):
        cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS))
    [record] = [r for r in caplog.records if r.name == cp.__name__]
    assert record.levelno == logging.WARNING
    assert "wrote 8" in record.message and "dropped 5" in record.message
    assert "unknown: 'Hashing Basics' -> 'Hash Table'" in record.message


def test_a_clean_write_logs_one_info_line(db, monkeypatch, caplog):
    _seed_deck(db)
    with caplog.at_level(logging.INFO, logger=cp.__name__):
        cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_EDGES))
    [record] = [r for r in caplog.records if r.name == cp.__name__]
    assert record.levelno == logging.INFO
    assert record.message.endswith("wrote 8, already present 0, dropped 0")


def test_no_relations_or_no_course_costs_nothing():
    with patch.object(cp, "flag_on") as flag, patch.object(cp, "table") as t:
        assert cp.write_document_prerequisites(USER, COURSE, _concepts(DECK)) == 0
        assert cp.write_document_prerequisites(USER, None, _concepts(DECK, DECK_RELATIONS)) == 0
        legacy = SimpleNamespace(concepts=_concepts(DECK).concepts)  # pre-A118 DBOS checkpoint
        assert cp.write_document_prerequisites(USER, COURSE, legacy) == 0
    flag.assert_not_called()
    t.assert_not_called()


# ── The planner, once the edges exist ────────────────────────────────────────


def _learning_order(states: dict[str, float], edges) -> list[str]:
    """Learn the head of the outer fringe until nothing is left to learn."""
    states, order = dict(states), []
    while fringe := planner.outer_fringe(states, edges):
        order.append(fringe[0])
        states[fringe[0]] = BKT_PROFICIENT
    return order


def test_the_planner_orders_prerequisites_before_dependents_once_edges_exist(db, monkeypatch):
    from routes.learn_loop import _plan_prereq_edges

    _seed_deck(db)
    names = {node_id: name for name, _imp, node_id in DECK}
    states = {node_id: BKT_L0 for node_id in names}

    # Before: no edges, so the fringe is the whole deck in node-id order — the
    # walkthrough's plan, Collision Resolution 1st, Hash Table 3rd, Hash Function 5th.
    before = [names[n] for n in planner.outer_fringe(states, _plan_prereq_edges(USER, list(names)))]
    assert before.index("Collision Resolution") == 0
    assert (before.index("Hash Table"), before.index("Hash Function")) == (2, 4)

    cp.write_document_prerequisites(USER, COURSE, _concepts(DECK, DECK_RELATIONS))
    # The loop route's own reader orients the rows (EDGE_PREREQ_SOURCE_IS_PREREQ).
    edges = _plan_prereq_edges(USER, list(names))
    assert {(names[p], names[d]) for p, d in edges} == set(DECK_EDGES)

    fringe = planner.outer_fringe(states, edges)
    assert [names[n] for n in fringe] == ["Hash Function"]
    proposal = planner.plan(fringe, [], lambda _n: [], None)
    assert [(names[c.node_id], c.kind) for c in proposal.concepts] == [("Hash Function", "new")]

    order = [names[n] for n in _learning_order(states, edges)]
    assert order[:3] == ["Hash Function", "Hash Table", "Collision Resolution"]
    assert sorted(order) == sorted(names.values())
    for prerequisite, dependent in DECK_EDGES:
        assert order.index(prerequisite) < order.index(dependent), (prerequisite, dependent)


# ── The upload routes ────────────────────────────────────────────────────────


def _agent_runs():
    """Mocks for the three agents an upload runs. The concepts one answers like
    pydantic-ai: the deck payload read through the output type the run asked
    for — the pre-A118 BaseConceptList unless the flag-on variant passed
    ConceptList."""
    from agents.classifier import DocumentClassification
    from agents.summary import Summary

    cls = DocumentClassification(category="slides", is_syllabus=False, confidence=0.9,
                                 rationale="t")
    summary = Summary(headline="h", abstract="Hash tables.", key_points=["a", "b", "c"])

    def concepts(*_args, **kwargs):
        output_type = kwargs.get("output_type") or BaseConceptList
        return SimpleNamespace(output=output_type.model_validate(_deck_payload()))

    return (
        AsyncMock(return_value=SimpleNamespace(output=cls)),
        AsyncMock(return_value=SimpleNamespace(output=summary)),
        AsyncMock(side_effect=concepts),
    )


def _sse_result(body: str) -> dict:
    """The `result` event's data off an SSE body (CRLF-framed)."""
    for block in body.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if fields.get("event") == "result":
            return json.loads(fields["data"])["data"]
    raise AssertionError(f"no result event in {body!r}")


def _stream_upload():
    cls_run, sum_run, cpt_run = _agent_runs()
    with (
        patch("routes.documents._validate_user"),
        patch("routes.documents.extract_text_from_file", return_value=_TEXT),
        patch("routes.documents.classifier_agent.run", cls_run),
        patch("routes.documents.summary_agent.run", sum_run),
        patch("routes.documents.concept_extraction_agent.run", cpt_run),
        patch("routes.documents.apply_concepts_to_graph", AsyncMock(return_value=9)),
        patch("routes.documents.table") as t,
        patch("routes.documents._spawn_post_roll"),
        patch("routes.documents.write_document_prerequisites",
              wraps=cp.write_document_prerequisites) as write,
        patch.object(cp, "apply_graph_update") as agu,
    ):
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "doc-1"}]
        with client.stream(
            "POST", "/api/documents/upload",
            files={"file": ("deck.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
            data={"course_id": COURSE, "user_id": USER},
        ) as r:
            assert r.status_code == 200
            body = r.read().decode()
    assert '"step": "done"' in body or '"step":"done"' in body, body
    return cpt_run, agu, write, _sse_result(body)


def _sync_upload():
    cls_run, sum_run, cpt_run = _agent_runs()
    with (
        patch("routes.documents._validate_user"),
        patch("routes.documents.extract_text_from_file", return_value=_TEXT),
        patch("agents.classifier.classifier_agent.run", cls_run),
        patch("agents.summary.summary_agent.run", sum_run),
        patch("agents.concept_extraction.concept_extraction_agent.run", cpt_run),
        patch("agents.document.apply_concepts_to_graph", AsyncMock(return_value=9)),
        patch("routes.documents.table") as t,
        patch("routes.documents._index_then_check_items"),
        patch("routes.documents.index_document"),
        patch("agents.document.write_document_prerequisites",
              wraps=cp.write_document_prerequisites) as write,
        patch.object(cp, "apply_graph_update") as agu,
    ):
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "doc-1"}]
        r = client.post(
            "/api/documents/upload/sync",
            files={"file": ("deck.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")},
            data={"course_id": COURSE, "user_id": USER},
        )
    assert r.status_code == 200, r.text
    return cpt_run, agu, write, None  # the sync response is the documents row: no concepts payload


UPLOADS = {"sse": _stream_upload, "sync": _sync_upload}


@pytest.fixture
def graph_reads(db, monkeypatch):
    """Every graph table this module reads (the course-concepts context, the
    write's node and edge reads), by table name."""
    spy = MagicMock(side_effect=db.table)
    monkeypatch.setattr(cp, "table", spy)
    return spy


@pytest.mark.parametrize("route", sorted(UPLOADS))
def test_upload_flag_off_is_the_pre_a118_upload(db, graph_reads, flag_reads, monkeypatch, route):
    monkeypatch.delenv(FLAG_ENV, raising=False)
    _seed_deck(db)
    cpt_run, agu, write, result = UPLOADS[route]()
    # The pre-A118 call, argument for argument: the bare text, the agent's own
    # prompt and schema — no instructions, no output_type, no context.
    assert cpt_run.call_args_list == [
        call(user_prompt=_TEXT, deps=ANY, usage_limits=WORKER_LIMITS),
    ]
    graph_reads.assert_not_called()  # no course-concepts read, no edge read
    write.assert_not_called()  # not even a no-op step: the pre-A118 sequence
    agu.assert_not_called()
    assert flag_reads == [USER]  # resolved once, for the uploader
    if result is not None:  # the SSE result serializes exactly as before A118
        assert set(result["concepts"]) == {"concepts"}


@pytest.mark.parametrize("route", sorted(UPLOADS))
def test_upload_flag_on_extracts_with_context_and_writes_oriented_edges(
    db, graph_reads, flag_reads, monkeypatch, route,
):
    monkeypatch.setenv(FLAG_ENV, "on")
    _seed_deck(db)
    db.add_node("n-arrays", "Arrays")
    cpt_run, agu, write, result = UPLOADS[route]()

    cpt_run.assert_called_once()
    kwargs = cpt_run.call_args.kwargs
    assert kwargs["instructions"] == PREREQUISITE_INSTRUCTIONS
    assert kwargs["output_type"] is ConceptList
    assert kwargs["user_prompt"] == build_message(_TEXT, cp.course_concept_names(USER, COURSE))
    assert "\n- Arrays\n" in kwargs["user_prompt"]
    assert kwargs["user_prompt"].endswith("Document:\n" + _TEXT)

    write.assert_called_once()
    agu.assert_called_once()
    (user, update), agu_kwargs = agu.call_args
    assert (user, agu_kwargs) == (USER, {"course_id": COURSE})
    assert [(e["source"], e["target"], e["relationship_type"]) for e in update["new_edges"]] == [
        (p, d, "prerequisite") for p, d in DECK_EDGES
    ]
    assert flag_reads == [USER]  # once: the write does not ask again
    if result is not None:
        assert len(result["concepts"]["prerequisites"]) == len(DECK_RELATIONS)


def test_a_pipeline_run_with_no_resolution_is_the_pre_a118_pipeline(
    db, graph_reads, flag_reads, monkeypatch,
):
    """process_document without `prerequisites` (no student-scoped resolution
    behind it) runs flag-off even with the flag on everywhere, and never reads
    the flag itself."""
    from agents.document import process_document

    monkeypatch.setenv(FLAG_ENV, "on")
    _seed_deck(db)
    cls_run, sum_run, cpt_run = _agent_runs()
    deps = SaplingDeps(user_id=USER, course_id=COURSE, supabase=None, request_id="r")
    with (
        patch("agents.classifier.classifier_agent.run", cls_run),
        patch("agents.summary.summary_agent.run", sum_run),
        patch("agents.concept_extraction.concept_extraction_agent.run", cpt_run),
        patch("agents.document.apply_concepts_to_graph", AsyncMock(return_value=9)),
        patch("agents.document.write_document_prerequisites") as write,
        patch.object(cp, "apply_graph_update") as agu,
    ):
        result = asyncio.run(process_document(_TEXT, deps))
    assert cpt_run.call_args_list == [
        call(user_prompt=_TEXT, deps=deps, usage_limits=WORKER_LIMITS),
    ]
    assert result.model_dump()["concepts"].keys() == {"concepts"}
    graph_reads.assert_not_called()
    write.assert_not_called()
    agu.assert_not_called()
    assert flag_reads == []
