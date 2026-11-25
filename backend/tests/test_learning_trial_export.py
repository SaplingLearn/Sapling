"""scripts/export_learning_trial.py: the trial's de-identified long table.
No raw id and no text leaves (every id a per-export salted pseudonym, no
concept name, item, answer or timestamp), each export has its own salt, and
the script is a dry run by default. Hermetic: no database read."""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta, timezone

import pytest

import scripts.export_learning_trial as export
from learning_trial.deidentify import Pseudonymizer
from learning_trial.table import read_csv, write_csv

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
    """The arm label is spliced into a PostgREST filter: a filter-injection
    shaped label is refused before any read."""
    with pytest.raises(SystemExit):
        export.main(["--arm-label", "x),or(", "--treatment-variant", "A"])


def test_the_export_carries_the_pose_record_and_the_skip_reasons():
    """A126's record of each pose leaves as enums, rounded durations and a count:
    how the item matched the pretest item and where it came from, and the answer
    latency and page-hidden stats of an answer given by the data lock (an
    answer after it exports none). A due window with nothing posed carries the
    skip reason recorded by the lock. No timestamp leaves, so the export stays
    de-identified; the table reads back the same."""
    data = _data()
    a126 = {"item_match": "exact", "item_source": "reserve", "answer_latency_s": 12.34,
            "hidden_count": 2, "hidden_s": 3.21, "served_at": _iso(_at(8))}
    data.poses[(N["open"], 7)].update(a126)
    data.poses[(N["chain"], 7)].update({**a126, "item_match": "difficulty", "item_source": "fallback"})
    data.poses[(N["open"], 28)].update({"item_match": "bogus", "hidden_count": True})  # out of schema
    data.skips = {
        (N["probe"], 28): ("exhausted", _at(30)),  # recorded by the lock
        (N["legacy"], 28): ("reported", AS_OF + timedelta(hours=1)),  # after the lock
        (N["open"], 7): ("no_items", _at(8)),  # a pose wins: never a skip
    }
    p = Pseudonymizer(b"k" * 32)
    rows, summary = export.build_rows(
        data, label=LABEL, treatment_variant="A", as_of=AS_OF, pseudonymize=p
    )
    by = {(r.concept, r.window): r for r in rows}

    def row(node, window):
        return by[(p("concept", COURSE, export.concept_key(NAMES[node])), window)]

    answered = row(N["open"], 7)
    assert (answered.item_match, answered.item_source) == ("exact", "reserve")
    assert (answered.answer_latency_s, answered.hidden_count, answered.hidden_s) == (12.3, 2, 3.2)
    assert answered.skip_reason == ""
    late = row(N["chain"], 7)  # answered after the lock: expired as of then
    assert late.status == "expired" and (late.item_match, late.item_source) == ("difficulty", "fallback")
    assert (late.answer_latency_s, late.hidden_count, late.hidden_s) == (None, None, None)
    odd = row(N["open"], 28)
    assert odd.item_match == "" and odd.hidden_count is None
    assert row(N["probe"], 28).status == "not_posed" and row(N["probe"], 28).skip_reason == "exhausted"
    assert row(N["legacy"], 28).skip_reason == ""
    assert summary.skipped[(28, row(N["probe"], 28).arm, "exhausted")] == 1
    buf = io.StringIO()
    write_csv(rows, buf)
    text = buf.getvalue()
    _assert_nothing_raw(text)
    _assert_nothing_raw(summary.render())
    assert "T0" not in text and ":00" not in text  # no timestamp of any kind
    back = {(r.concept, r.window): r for r in read_csv(io.StringIO(text))}
    assert back[(answered.concept, 7)] == answered
    assert back[(row(N["probe"], 28).concept, 28)].skip_reason == "exhausted"
