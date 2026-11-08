"""scripts/export_learning_trial.py: the trial's de-identified long table.
No raw id and no text leaves (every id a per-export salted pseudonym, no
concept name, item, answer or timestamp); the post-test states, exclusions and
arms follow A112/A113 and learning/arms.py; dry run by default. Hermetic: the
database reads run against an in-memory fake."""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import scripts.export_learning_trial as export
from learning import arms
from learning.evidence import Evidence, planning_observation
from learning_trial.deidentify import Pseudonymizer
from learning_trial.table import CONTROL, TREATMENT, read_csv, write_csv

LABEL = "trial-2027s"
AS_OF = datetime(2026, 12, 1, tzinfo=timezone.utc)
U1, U2 = "user_109876543210987654321", "user_555000111222333444555"
COURSE = "course-7d1e2f3a-5b6c"
N = {name: f"node-{name}-0f3a9c1e" for name in ("open", "load", "load_dup", "tomb", "probe", "chain", "legacy")}
QH = {name: f"qh-{name}-deadbeefcafe" for name in ("a", "b", "c", "d", "e", "f")}
NAMES = {
    N["open"]: "Open Addressing",
    N["load"]: "Load Factor",
    N["load_dup"]: "  load   FACTOR ",  # the same course concept once normalized
    N["tomb"]: "Tombstone Deletion",
    N["probe"]: "Linear Probing",
    N["chain"]: "Separate Chaining",
    N["legacy"]: "Rehashing Strategy",
}
OWNER = {N["open"]: U1, N["load"]: U1, N["load_dup"]: U1, N["tomb"]: U1,
         N["probe"]: U2, N["chain"]: U2, N["legacy"]: U2}


def _at(day, hour=0):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def _iso(ts):
    return ts.isoformat().replace("+00:00", "Z")


def _pose(node, window, qh, *, posed, answered=None, correct=None, rung=None, delay=9.04):
    return {
        "node_id": node, "course_id": COURSE, "window_days": window, "question_hash": qh,
        "posed_at": _iso(posed), "answered_at": _iso(answered) if answered else None,
        "correct": correct, "max_rung": rung, "anchor_event_id": f"ev-{node}", "days_since_evidence": delay,
    }


def _data():
    spans = {
        N["open"]: (f"ev-{N['open']}", _at(1)),  # both windows due by AS_OF
        N["load"]: (f"ev-{N['load']}", _at(20)),  # 7-day due, 28-day not yet
        N["load_dup"]: (f"ev-{N['load_dup']}", _at(21)),  # a later duplicate: dropped
        N["tomb"]: (f"ev-{N['tomb']}", _at(30)),  # nothing due yet
        N["probe"]: (f"ev-{N['probe']}", _at(1)),
        N["chain"]: (f"ev-{N['chain']}", _at(1)),
        N["legacy"]: (f"ev-{N['legacy']}", _at(1)),
    }
    poses = {
        (N["open"], 7): _pose(N["open"], 7, QH["a"], posed=_at(8), answered=_at(8, 1), correct=True, rung=0),
        (N["open"], 28): _pose(N["open"], 28, QH["b"], posed=_at(29), answered=_at(29, 1), correct=False, rung=2),
        (N["load"], 7): _pose(N["load"], 7, QH["c"], posed=_at(30, 12)),  # 12 h before AS_OF: open
        (N["probe"], 7): _pose(N["probe"], 7, QH["d"], posed=_at(9)),  # never answered: expired
        # answered only after the data lock: as of AS_OF it was posed and expired
        (N["chain"], 7): _pose(N["chain"], 7, QH["e"], posed=_at(9), answered=AS_OF + timedelta(days=1),
                               correct=True, rung=0),
        (N["chain"], 28): _pose(N["chain"], 28, QH["f"], posed=_at(29, 6), answered=_at(29, 7), correct=True, rung=0),
        (N["legacy"], 7): _pose(N["legacy"], 7, QH["a"], posed=_at(9), answered=_at(9, 1)),  # pre-A112: no outcome
    }
    return export.TrialData(
        students=[U1, U2],
        nodes=[{"id": n, "user_id": OWNER[n], "course_id": COURSE, "concept_name": NAMES[n]} for n in N.values()],
        spans=spans,
        poses=poses,
        pretests={f"ev-{N['open']}": False, f"ev-{N['chain']}": True},
        retired={(COURSE, QH["a"])},
        reported={(COURSE, QH["f"])},
    )


def _build(pseudonymize=None, treatment_variant="A"):
    return export.build_rows(
        _data(),
        label=LABEL,
        treatment_variant=treatment_variant,
        as_of=AS_OF,
        pseudonymize=pseudonymize or Pseudonymizer(),
    )


RAW = [U1, U2, COURSE, *N.values(), *QH.values(), *(f"ev-{n}" for n in N.values())]
WORDS = ["addressing", "factor", "tombstone", "probing", "chaining", "rehashing", "2026-11", "2026-12"]


def _assert_nothing_raw(text: str) -> None:
    for raw in RAW:
        assert raw not in text, f"raw id {raw!r} leaked"
    lowered = text.lower()
    for word in WORDS:
        assert word not in lowered, f"text {word!r} leaked"


def test_the_export_carries_no_raw_id_and_no_text():
    rows, summary = _build()
    buf = io.StringIO()
    write_csv(rows, buf)
    _assert_nothing_raw(buf.getvalue())
    _assert_nothing_raw(summary.render())
    ids = {"student": r"s_[0-9a-f]{16}", "course": r"c_[0-9a-f]{16}", "concept": r"k_[0-9a-f]{16}",
           "item": r"(i_[0-9a-f]{16})?"}
    for row in read_csv(io.StringIO(buf.getvalue())):
        for column, pattern in ids.items():
            assert re.fullmatch(pattern, getattr(row, column)), (column, getattr(row, column))


def test_rows_follow_the_post_test_windows_states_and_exclusions():
    p = Pseudonymizer(b"k" * 32)
    rows, summary = _build(p)
    by = {(r.concept, r.window): r for r in rows}

    def row(node, window):
        return by.get((p("concept", COURSE, export.concept_key(NAMES[node])), window))

    assert row(N["open"], 7).status == "rung0" and row(N["open"], 7).posttest is True
    assert row(N["open"], 7).exclusion == "retired_item"  # the item was retired (A113)
    assert row(N["open"], 7).pretest is False and row(N["open"], 7).days_since_evidence == 9.0
    assert row(N["open"], 28).status == "assisted" and row(N["open"], 28).posttest is None
    assert row(N["load"], 7).status == "open" and row(N["load"], 28) is None  # not yet due
    assert row(N["tomb"], 7) is None  # anchored the day before: nothing due
    assert row(N["probe"], 7).status == "expired" and row(N["probe"], 28).status == "not_posed"
    assert row(N["chain"], 7).status == "expired"  # its answer came after the data lock
    assert row(N["chain"], 28).exclusion == "reported_item" and row(N["chain"], 7).pretest is True
    assert row(N["legacy"], 7).status == "unrecorded"
    assert summary.notes["duplicate_concept_nodes_dropped"] == 1
    assert summary.students_labelled == 2 and summary.students_exported == 2
    assert [(r.student, r.concept, r.window) for r in rows] == sorted((r.student, r.concept, r.window) for r in rows)


@pytest.mark.parametrize("treatment_variant", ["A", "B"])
def test_arms_are_the_products_variant_for_under_the_label(treatment_variant):
    p = Pseudonymizer(b"k" * 32)
    rows, _ = _build(p, treatment_variant)
    for node, name in NAMES.items():
        if node == N["load_dup"]:
            continue
        expected = TREATMENT if arms.variant_for(OWNER[node], node, LABEL) == treatment_variant else CONTROL
        for r in rows:
            if r.concept == p("concept", COURSE, export.concept_key(name)) and r.student == p("student", OWNER[node]):
                assert r.arm == expected


def test_each_export_gets_its_own_salt():
    first, _ = _build()
    second, _ = _build()
    assert {r.student for r in first}.isdisjoint({r.student for r in second})
    assert len({r.student for r in first}) == 2
    same_salt = Pseudonymizer(b"z" * 32)
    assert _build(same_salt)[0] == _build(same_salt)[0]
    assert "salt" not in repr(Pseudonymizer()).replace("salt=<hidden>", "")
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(Pseudonymizer())


def test_main_is_a_dry_run_by_default_and_writes_only_on_out(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(export, "read_trial", lambda label, as_of: _data())
    salts = []

    class Recording(Pseudonymizer):
        def __init__(self):
            salt = bytes(range(32))
            salts.append(salt.hex())
            super().__init__(salt)

    monkeypatch.setattr(export, "Pseudonymizer", Recording)
    argv = ["--arm-label", LABEL, "--treatment-variant", "A", "--as-of", "2026-12-01T00:00:00Z"]

    def student_part(printed: str) -> str:  # the operator's own arguments are echoed; nothing else may be
        return "\n".join(line for line in printed.splitlines() if not line.startswith("arm label"))

    assert export.main(argv) == 0
    dry = capsys.readouterr().out
    assert "dry run: nothing written" in dry and "Project:" in dry
    assert not list(tmp_path.iterdir())
    _assert_nothing_raw(student_part(dry))
    target = tmp_path / "trial.csv"
    assert export.main(argv + ["--out", str(target)]) == 0
    wet = capsys.readouterr().out
    written = target.read_text()
    _assert_nothing_raw(written)
    _assert_nothing_raw(student_part(wet))
    assert salts and all(s not in written and s not in dry + wet for s in salts), "the salt never leaves"
    assert export.main(argv + ["--out", str(target)]) == 2, "an existing file is never overwritten"
    assert len(read_csv(target)) == len(_build()[0])


def test_main_refuses_an_unsafe_label():
    with pytest.raises(SystemExit):
        export.main(["--arm-label", "x),or(", "--treatment-variant", "A"])


# ── the reads, against an in-memory PostgREST fake ─────────────────────────────


class _FakeDB:
    def __init__(self, tables):
        self.tables = tables
        self.calls = []

    def _match(self, name, filters):
        rows = list(self.tables.get(name, []))
        for key, cond in (filters or {}).items():
            if cond.startswith("eq."):
                rows = [r for r in rows if str(r.get(key)) == cond[3:]]
            elif cond.startswith("in.("):
                wanted = {v.strip('"') for v in cond[4:-1].split(",")}
                rows = [r for r in rows if str(r.get(key)) in wanted]
            elif cond == "not.is.null":
                rows = [r for r in rows if r.get(key) is not None]
            else:
                raise AssertionError(f"unexpected filter {key}={cond}")
        return [dict(r) for r in rows]

    def table(self, name):
        db = self

        def select(columns="*", filters=None, **kwargs):
            db.calls.append(("select", name, columns))
            return db._match(name, filters)

        return SimpleNamespace(name=name, select=select)

    def page_all(self, handle, columns="*", *, filters=None, order, **kwargs):
        assert order, "page_all needs a total order"
        self.calls.append(("page_all", handle.name, columns))
        return iter(self._match(handle.name, filters))


def _probe_anchor(event_id, node, qh, *, correct, at, seq=1):
    """A journal evidence row as graph_service writes it, carrying the REAL planning
    envelope; `graph_nodes.user_id` stands in for the !inner embed's filter."""
    ev = Evidence(
        node_id=node, channel="free_response", correct=correct, session_id="sess-1", check_item_id="item-1",
        question_hash=qh,
        planning_provenance={"check_item_id": "item-1", "difficulty": 2, "synthetic_idk": False,
                             "previously_seen": False},
    )
    return {
        "id": event_id, "node_id": node, "session_id": "sess-1", "question_hash": qh, "check_item_id": "item-1",
        "channel": ev.channel, "correct": ev.correct, "assisted": ev.assisted, "max_rung": ev.max_rung,
        "reason": f"evidence:{ev.channel}", "event_type": "evidence", "planning_observation": planning_observation(ev),
        "created_at": _iso(at), "evidence_seq": seq, "graph_nodes.user_id": U1,
    }


def test_read_trial_composes_the_reads(monkeypatch):
    db = _FakeDB({
        "user_settings": [{"user_id": U1, "loop_arm": LABEL}, {"user_id": U2, "loop_arm": "other"}],
        "graph_nodes": [
            {"id": N["open"], "user_id": U1, "course_id": COURSE, "concept_name": "Open Addressing"},
            {"id": N["load"], "user_id": U1, "course_id": COURSE, "concept_name": "Load Factor"},
            {"id": "node-nocourse", "user_id": U1, "course_id": None, "concept_name": "Loose"},
        ],
        "posttest_poses": [
            {**_pose(N["open"], 7, QH["a"], posed=_at(8), answered=_at(8, 1), correct=True, rung=0), "user_id": U1},
        ],
        "node_mastery_events": [  # the journal's total order: the first row of a node is its anchor
            _probe_anchor(f"ev-{N['open']}", N["open"], "q-probe", correct=True, at=_at(1)),
            _probe_anchor(f"ev-{N['load']}", N["load"], "q-check", correct=False, at=_at(2)),  # not a probe item
            _probe_anchor("ev-later", N["open"], "q-check", correct=False, at=_at(3)),  # practice: no anchor
        ],
        "sessions": [{"id": "sess-1", "history": [{"question_hash": "q-probe"}]}],
        "check_item_reviews": [{"course_id": COURSE, "question_hash": QH["a"], "status": "retired",
                                "reviewed_at": _iso(_at(10))}],
        "check_item_reports": [],
    })
    monkeypatch.setattr(export, "table", db.table)
    monkeypatch.setattr(export, "page_all", db.page_all)
    data = export.read_trial(LABEL, AS_OF)
    assert data.students == [U1]
    assert {n["id"] for n in data.nodes} == {N["open"], N["load"]}
    assert data.spans == {N["open"]: (f"ev-{N['open']}", _at(1)), N["load"]: (f"ev-{N['load']}", _at(2))}
    assert data.pretests == {f"ev-{N['open']}": True}  # the check-item anchor is no pretest
    assert set(data.poses) == {(N["open"], 7)}
    assert data.retired == {(COURSE, QH["a"])} and data.reported == set()
    assert not any(kind == "select" and name in ("posttest_poses", "graph_nodes") for kind, name, _ in db.calls), (
        "unbounded reads page"
    )


def test_the_anchor_read_is_evidence_spans_rule(monkeypatch):
    """The exporter restates A112's anchor read (scripts may not import the ZPD
    layer's loop_state_store): same journal rows in, same anchors out, same
    total order asked of PostgREST. Spec §13 A123 is part of that rule: a row
    the student's void record names never anchors, so n1 (its first row void)
    is anchored by its next row and n4 (every row void) by none."""
    from learning import loop_state_store as store
    from learning import void_store

    rows = [
        {"id": "e1", "node_id": "n1", "created_at": "2026-11-01T09:00:00Z", "evidence_seq": 1},
        {"id": "e2", "node_id": "n2", "created_at": "2026-11-01T09:00:00+00:00", "evidence_seq": 2},
        {"id": "e3", "node_id": "n1", "created_at": "2026-11-02T09:00:00Z", "evidence_seq": 3},
        {"id": "e4", "node_id": "n3", "created_at": "2026-11-03T10:30:00.123456Z", "evidence_seq": None},
        {"id": "e5", "node_id": "n4", "created_at": "2026-11-03T11:00:00Z", "evidence_seq": 5},
    ]
    orders, void_scopes = [], []

    def page_all(handle, columns="*", *, filters=None, order, **kwargs):
        orders.append(order)
        assert filters["event_type"] == "eq.evidence"
        return iter(dict(r) for r in rows)

    def voided_event_ids(**scope):
        void_scopes.append(scope)
        return {"e1", "e5"}

    monkeypatch.setattr(void_store, "voided_event_ids", voided_event_ids)
    monkeypatch.setattr(store, "page_all", page_all)
    monkeypatch.setattr(export, "page_all", page_all)
    monkeypatch.setattr(export, "table", lambda name: SimpleNamespace(name=name))
    spans = store.evidence_spans("u1", "course")
    anchors = export._anchors("u1")
    assert anchors == {node: (span.first_id, span.first_at) for node, span in spans.items()}
    assert {node: anchor_id for node, (anchor_id, _) in anchors.items()} == {
        "n1": "e3", "n2": "e2", "n3": "e4",
    }
    assert void_scopes == [{"user_id": "u1"}, {"user_id": "u1"}]  # one read each, owner-scoped
    assert orders[0] == orders[1] == export._JOURNAL_ORDER


def test_reported_means_no_staff_approval_since_the_last_report(monkeypatch):
    c, other = COURSE, "course-other"
    db = _FakeDB({
        "check_item_reviews": [
            {"course_id": c, "question_hash": "qa", "status": "retired", "reviewed_at": _iso(_at(5))},
            {"course_id": c, "question_hash": "qb", "status": "approved", "reviewed_at": _iso(_at(9))},
            {"course_id": c, "question_hash": "qc", "status": "approved", "reviewed_at": _iso(_at(5))},
        ],
        "check_item_reports": [
            {"course_id": c, "question_hash": "qb", "created_at": _iso(_at(8)), "user_id": "u1"},  # cleared
            {"course_id": c, "question_hash": "qc", "created_at": _iso(_at(7)), "user_id": "u1"},  # after approval
            {"course_id": c, "question_hash": "qd", "created_at": _iso(AS_OF + timedelta(hours=1)), "user_id": "u1"},
            {"course_id": other, "question_hash": "qe", "created_at": _iso(_at(7)), "user_id": "u1"},
        ],
    })
    monkeypatch.setattr(export, "table", db.table)
    monkeypatch.setattr(export, "page_all", db.page_all)
    items = {(c, "qa"), (c, "qb"), (c, "qc"), (c, "qd"), (c, "qe")}
    retired, reported = export._item_decisions(items, AS_OF)
    assert retired == {(c, "qa")}
    assert reported == {(c, "qc")}  # qd reported after the lock; qe's report is another course's item
