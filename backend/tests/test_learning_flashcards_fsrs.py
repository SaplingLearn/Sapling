"""PKG-11: FSRS state on flashcards + the quiz/flashcard gate seams.

Route tests mock `table` (tests/test_graph_service.py::_mock_table style) and
patch the gate at the route module (`routes.flashcards.learning_loop_active`).
FSRS maths is PKG-02's (tests/test_learning_fsrs.py); here `next_state`,
`interval` and `order_due` are patched at the route module so these tests
prove WIRING — what the route reads, what it writes, in what order — not
the curve. Flag-off tests snapshot the exact legacy query strings and
payload key sets: the pre-series behaviour must be byte-identical.
"""

from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
USER_ID = "user_test"

LEGACY_LIST_COLS = (
    "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,last_reviewed_at,created_at"
)
LEGACY_RATE_COLS = "id,times_reviewed"
LEGACY_RATE_KEYS = {"times_reviewed", "last_rating", "last_reviewed_at"}
# rate_card's select and update filters, identical on both paths: the select is
# owner-scoped, the update targets the one card by id.
RATE_SELECT_KWARGS = {"filters": {"id": "eq.card-1", "user_id": f"eq.{USER_ID}"}, "limit": 1}
RATE_UPDATE_KWARGS = {"filters": {"id": "eq.card-1"}}
FSRS_COLS = ",fsrs_d,fsrs_s,due_at,reps,lapses"
FSRS_KEYS = {"fsrs_d", "fsrs_s", "due_at", "reps", "lapses"}


# ── Migration ────────────────────────────────────────────────────────────────


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_flashcards_fsrs.sql"))
    assert len(hits) == 1, f"expected exactly one learning_flashcards_fsrs migration, got {hits}"
    return hits[0].read_text()


class TestMigration:
    def test_prefix_is_a_utc_timestamp(self):
        hits = sorted(MIG_DIR.glob("*_learning_flashcards_fsrs.sql"))
        assert hits, "no learning_flashcards_fsrs migration"
        assert re.fullmatch(r"\d{14}_learning_flashcards_fsrs\.sql", hits[0].name), hits[0].name

    @pytest.mark.parametrize(
        "col,decl",
        [
            ("fsrs_d", r"double precision"),
            ("fsrs_s", r"double precision"),
            ("due_at", r"timestamptz"),
            ("reps", r"int\s+NOT NULL\s+DEFAULT\s+0"),
            ("lapses", r"int\s+NOT NULL\s+DEFAULT\s+0"),
        ],
    )
    def test_columns_are_declared_per_spec(self, col, decl):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS\s+{col}\s+{decl}", _migration()), col

    def test_due_index_is_user_scoped(self):
        assert re.search(
            r"CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards \(user_id, due_at\)",
            _migration(),
        )

    def test_only_touches_flashcards(self):
        sql = _migration()
        assert "ALTER TABLE flashcards" in sql
        assert not re.search(r"ALTER TABLE (?!flashcards)", sql)
        assert "DROP" not in sql.upper()


# ── rate_card ────────────────────────────────────────────────────────────────

# Real "now" at import: the route reads the clock itself, so due/elapsed
# fixtures are relative to it (a run takes seconds; tolerances are minutes).
NOW = datetime.now(timezone.utc)
TWO_DAYS_AGO = (NOW - timedelta(days=2)).isoformat()


def _rate_tables(row: dict):
    """table() stand-in for rate_card: one select hit, an update that records
    its payload and its filters on `calls`."""
    calls: dict = {}

    def _select(cols, **kw):
        calls["select_cols"] = cols
        calls["select_kwargs"] = kw
        return [dict(row)]

    def _update(payload, **kw):
        calls["update"] = payload
        calls["update_kwargs"] = kw
        return [{"id": row["id"]}]

    def side_effect(name):
        m = MagicMock()
        if name == "flashcards":
            m.select.side_effect = _select
            m.update.side_effect = _update
        else:
            m.select.return_value = []
        return m

    return side_effect, calls


def _rate(rating: int, *, gate: bool, row: dict, next_state=None, interval=None, check=None):
    side_effect, calls = _rate_tables(row)
    ns = next_state or MagicMock(return_value=(4.5, 9.0))
    iv = interval or MagicMock(return_value=8.0)
    with (
        patch("routes.flashcards.table", side_effect=side_effect),
        patch("routes.flashcards.learning_loop_active", return_value=gate),
        patch("routes.flashcards.next_state", new=ns),
        patch("routes.flashcards.interval", new=iv),
        patch("routes.flashcards.check_achievements", new=check or MagicMock()),
    ):
        r = client.post(
            "/api/flashcards/rate",
            json={"user_id": USER_ID, "card_id": "card-1", "rating": rating},
        )
    return r, calls, ns, iv


FRESH_ROW = {
    "id": "card-1",
    "times_reviewed": 0,
    "last_reviewed_at": None,
    "fsrs_d": None,
    "fsrs_s": None,
    "reps": 0,
    "lapses": 0,
}
SEEN_ROW = {
    "id": "card-1",
    "times_reviewed": 3,
    "last_reviewed_at": TWO_DAYS_AGO,
    "fsrs_d": 5.2,
    "fsrs_s": 3.1,
    "reps": 3,
    "lapses": 1,
}


class TestRateCard:
    @pytest.mark.parametrize("ui_rating,fsrs_rating", [(1, 1), (2, 2), (3, 3)])
    def test_rating_map_forgot_hard_easy_to_again_hard_good(self, ui_rating, fsrs_rating):
        from learning.params import FLASHCARD_RATING_TO_FSRS

        assert FLASHCARD_RATING_TO_FSRS[ui_rating] == fsrs_rating
        r, calls, ns, _ = _rate(ui_rating, gate=True, row=SEEN_ROW)
        assert r.status_code == 200, r.text
        assert ns.call_args[0][2] == fsrs_rating

    def test_easy_is_never_emitted(self):
        from learning.params import FLASHCARD_RATING_TO_FSRS

        assert 4 not in FLASHCARD_RATING_TO_FSRS.values()

    def test_map_values_are_pkg02_rating_grades(self):
        """params.py cannot import learning.fsrs (fsrs imports params), so the
        map holds plain ints; they must be PKG-02's Rating grades."""
        from learning.fsrs import Rating
        from learning.params import FLASHCARD_RATING_TO_FSRS

        assert FLASHCARD_RATING_TO_FSRS == {1: Rating.AGAIN, 2: Rating.HARD, 3: Rating.GOOD}

    def test_gate_on_selects_the_fsrs_columns(self):
        _, calls, _, _ = _rate(3, gate=True, row=SEEN_ROW)
        assert (
            calls["select_cols"] == "id,times_reviewed,last_reviewed_at,fsrs_d,fsrs_s,reps,lapses"
        )

    def test_gate_on_writes_state_beside_the_legacy_columns(self):
        r, calls, ns, iv = _rate(3, gate=True, row=SEEN_ROW)
        payload = calls["update"]
        assert set(payload) == LEGACY_RATE_KEYS | FSRS_KEYS
        assert calls["select_kwargs"] == RATE_SELECT_KWARGS
        assert calls["update_kwargs"] == RATE_UPDATE_KWARGS, "one update, scoped to the card"
        assert payload["times_reviewed"] == 4 and payload["last_rating"] == 3
        assert payload["fsrs_d"] == 4.5 and payload["fsrs_s"] == 9.0
        assert payload["reps"] == 4 and payload["lapses"] == 1
        iv.assert_called_once()
        retention, s = iv.call_args[0]
        from learning.params import FSRS_RETENTION_DEFAULT

        assert retention == FSRS_RETENTION_DEFAULT and s == 9.0
        due = datetime.fromisoformat(payload["due_at"])
        written = datetime.fromisoformat(payload["last_reviewed_at"])
        assert abs((due - written) - timedelta(days=8.0)) < timedelta(seconds=1)
        assert r.json()["due_at"] == payload["due_at"]
        assert r.json()["fsrs_rating"] == 3

    def test_gate_on_passes_prior_state_and_elapsed_days(self):
        _, _, ns, _ = _rate(2, gate=True, row=SEEN_ROW)
        d, s, rating, days_since = ns.call_args[0]
        assert (d, s, rating) == (5.2, 3.1, 2)
        assert days_since == pytest.approx(2.0, abs=0.01)
        assert ns.call_args.kwargs == {"same_day": False}

    def test_gate_on_review_within_a_day_takes_the_same_day_branch(self):
        """HANDOFF-02 next_state(..., *, same_day): same rule as PKG-03's
        graph_service._fsrs_after — less than one day since the last review."""
        row = {**SEEN_ROW, "last_reviewed_at": (NOW - timedelta(hours=2)).isoformat()}
        _, _, ns, _ = _rate(3, gate=True, row=row)
        assert ns.call_args[0][3] == pytest.approx(2 / 24, abs=0.01)
        assert ns.call_args.kwargs == {"same_day": True}

    def test_gate_on_first_review_passes_none_state_and_zero_days(self):
        _, calls, ns, _ = _rate(3, gate=True, row=FRESH_ROW)
        d, s, _, days_since = ns.call_args[0]
        assert d is None and s is None and days_since == 0.0
        assert ns.call_args.kwargs == {"same_day": False}
        assert calls["update"]["reps"] == 1 and calls["update"]["lapses"] == 0

    def test_again_increments_lapses(self):
        _, calls, _, _ = _rate(1, gate=True, row=SEEN_ROW)
        assert calls["update"]["lapses"] == 2

    def test_gate_on_rejects_a_rating_outside_the_map_before_any_write(self):
        r, calls, ns, _ = _rate(5, gate=True, row=SEEN_ROW)
        assert r.status_code == 422
        assert "update" not in calls
        ns.assert_not_called()

    def test_gate_on_fsrs_failure_is_not_swallowed_into_a_legacy_write(self):
        """Spec §Error semantics: the card stays unchanged and the client sees
        the error (TestClient re-raises it; the server answers 500)."""
        boom = MagicMock(side_effect=ValueError("corrupt stored stability"))
        side_effect, calls = _rate_tables(SEEN_ROW)
        with (
            patch("routes.flashcards.table", side_effect=side_effect),
            patch("routes.flashcards.learning_loop_active", return_value=True),
            patch("routes.flashcards.next_state", new=boom),
        ):
            with pytest.raises(ValueError, match="corrupt stored stability"):
                client.post(
                    "/api/flashcards/rate",
                    json={"user_id": USER_ID, "card_id": "card-1", "rating": 3},
                )
        assert "update" not in calls, "the legacy columns must not move without the FSRS state"

    def test_gate_on_keeps_the_achievement_dispatch(self):
        check = MagicMock()
        r, _, _, _ = _rate(3, gate=True, row=SEEN_ROW, check=check)
        assert r.status_code == 200
        check.assert_called_once_with(USER_ID, "flashcards_reviewed", {})

    def test_gate_is_evaluated_once_per_rating(self):
        side_effect, _ = _rate_tables(SEEN_ROW)
        gate = MagicMock(return_value=True)
        with (
            patch("routes.flashcards.table", side_effect=side_effect),
            patch("routes.flashcards.learning_loop_active", new=gate),
            patch("routes.flashcards.check_achievements"),
        ):
            client.post(
                "/api/flashcards/rate",
                json={"user_id": USER_ID, "card_id": "card-1", "rating": 3},
            )
        gate.assert_called_once_with(USER_ID)

    def test_gate_off_is_byte_identical(self):
        r, calls, ns, iv = _rate(5, gate=False, row=SEEN_ROW)  # legacy accepts any int
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert calls["select_cols"] == LEGACY_RATE_COLS
        assert calls["select_kwargs"] == RATE_SELECT_KWARGS
        assert set(calls["update"]) == LEGACY_RATE_KEYS
        assert calls["update_kwargs"] == RATE_UPDATE_KWARGS
        assert calls["update"]["times_reviewed"] == 4 and calls["update"]["last_rating"] == 5
        ns.assert_not_called()
        iv.assert_not_called()


# ── get_flashcards ───────────────────────────────────────────────────────────


def _card(cid, *, created, due=None, s=None, d=None, reps=0, lapses=0, last=None):
    return {
        "id": cid,
        "user_id": USER_ID,
        "topic": "T",
        "offering_id": None,
        "front": "q",
        "back": "a",
        "times_reviewed": reps,
        "last_rating": None,
        "last_reviewed_at": last,
        "created_at": created,
        "fsrs_d": d,
        "fsrs_s": s,
        "due_at": due,
        "reps": reps,
        "lapses": lapses,
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# Query order is created_at.desc (newest first), as the route requests it.
LIST_ROWS = [
    _card(
        "later-b",
        created="2026-09-26T00:00:00Z",
        due=_iso(NOW + timedelta(days=3)),
        s=6.0,
        d=5.0,
        reps=2,
    ),
    _card("fresh-new", created="2026-09-25T00:00:00Z"),
    _card(
        "due-old",
        created="2026-09-24T00:00:00Z",
        due=_iso(NOW - timedelta(days=2)),
        s=2.0,
        d=5.0,
        reps=1,
    ),
    _card("fresh-older", created="2026-09-23T00:00:00Z"),
    _card(
        "due-recent",
        created="2026-09-22T00:00:00Z",
        due=_iso(NOW - timedelta(hours=1)),
        s=4.0,
        d=5.0,
        reps=3,
    ),
    _card(
        "later-a",
        created="2026-09-21T00:00:00Z",
        due=_iso(NOW + timedelta(days=1)),
        s=6.0,
        d=5.0,
        reps=2,
    ),
]


def _list(*, gate: bool, query: str = "", order_due=None, rows=None):
    calls: dict = {}
    source = LIST_ROWS if rows is None else rows

    def side_effect(name):
        m = MagicMock()
        if name == "flashcards":

            def _select(cols, **kw):
                calls["select_cols"] = cols
                calls["select_kwargs"] = kw
                # PostgREST returns exactly the named columns: a column the
                # route does not select is absent from its rows.
                names = cols.split(",")
                return [{c: r[c] for c in names} for r in source]

            m.select.side_effect = _select
        else:
            m.select.return_value = []
        return m

    # HANDOFF-02: order_due(items, now, *, stability_key, last_review_key).
    od = order_due or MagicMock(side_effect=lambda rows, now, **kw: list(reversed(rows)))
    with (
        patch("routes.flashcards.table", side_effect=side_effect),
        patch("routes.flashcards.learning_loop_active", return_value=gate),
        patch("routes.flashcards.order_due", new=od),
    ):
        r = client.get(f"/api/flashcards/user/{USER_ID}{query}")
    return r, calls, od


class TestListFlashcards:
    def test_gate_on_selects_fsrs_columns_with_the_same_query(self):
        r, calls, _ = _list(gate=True)
        assert r.status_code == 200, r.text
        assert calls["select_cols"] == LEGACY_LIST_COLS + FSRS_COLS
        assert calls["select_kwargs"] == {
            "filters": {"user_id": f"eq.{USER_ID}"},
            "order": "created_at.desc",
        }

    def test_gate_on_orders_due_then_fresh_then_later(self):
        r, _, od = _list(gate=True)
        ids = [c["id"] for c in r.json()["flashcards"]]
        # order_due is patched to REVERSE its input, proving the route honours
        # its output rather than the query order.
        assert ids == ["due-recent", "due-old", "fresh-new", "fresh-older", "later-a", "later-b"]
        od.assert_called_once()
        passed_ids = [c["id"] for c in od.call_args[0][0]]
        assert passed_ids == ["due-old", "due-recent"]
        # Flashcards keep their last review in last_reviewed_at (HANDOFF-02).
        assert od.call_args.kwargs == {"last_review_key": "last_reviewed_at"}
        assert r.json()["due_count"] == 2

    def test_gate_on_due_only_returns_the_due_bucket_only(self):
        r, _, _ = _list(gate=True, query="?due_only=true")
        ids = [c["id"] for c in r.json()["flashcards"]]
        assert ids == ["due-recent", "due-old"]
        assert r.json()["due_count"] == 2

    def test_gate_on_a_null_due_at_is_not_due(self):
        r, _, _ = _list(gate=True, query="?due_only=true")
        assert not any(c["id"].startswith("fresh") for c in r.json()["flashcards"])

    def test_gate_on_response_rows_carry_the_fsrs_columns(self):
        """The stub projects each row onto the selected columns, so the FSRS
        keys reach the response only because the route selects them."""
        r, _, _ = _list(gate=True)
        rows = r.json()["flashcards"]
        assert rows and all(FSRS_KEYS <= set(c) for c in rows)

    def test_gate_on_real_order_due_ranks_by_distance_from_threshold(self):
        """Unpatched learning.fsrs.order_due through the adapter: the due card
        whose recall probability is nearest REVIEW_ORDER_THRESHOLD comes first."""
        from learning import fsrs

        rows = [
            # reviewed 4 d ago at S = 4 d: R = 0.9, just due (newest, so first
            # in the query's created_at.desc order)
            _card(
                "just-due",
                created="2026-09-24T00:00:00Z",
                s=4.0,
                d=5.0,
                reps=1,
                due=_iso(NOW - timedelta(minutes=5)),
                last=_iso(NOW - timedelta(days=4)),
            ),
            # reviewed 10 d ago at S = 2 d: R ≈ 0.76, nearer the threshold
            _card(
                "long-overdue",
                created="2026-09-23T00:00:00Z",
                s=2.0,
                d=5.0,
                reps=1,
                due=_iso(NOW - timedelta(days=8)),
                last=_iso(NOW - timedelta(days=10)),
            ),
        ]
        dist = {
            row["id"]: abs(
                fsrs.item_retrievability(row, NOW, last_review_key="last_reviewed_at")
                - fsrs.REVIEW_ORDER_THRESHOLD
            )
            for row in rows
        }
        assert dist["long-overdue"] < dist["just-due"]
        r, _, _ = _list(gate=True, rows=rows, order_due=fsrs.order_due)
        body = r.json()
        assert [c["id"] for c in body["flashcards"]] == ["long-overdue", "just-due"]
        assert body["due_count"] == 2

    def test_gate_off_is_byte_identical(self):
        r, calls, od = _list(gate=False, query="?due_only=true")
        assert r.status_code == 200
        assert calls["select_cols"] == LEGACY_LIST_COLS
        assert calls["select_kwargs"] == {
            "filters": {"user_id": f"eq.{USER_ID}"},
            "order": "created_at.desc",
        }
        body = r.json()
        assert set(body) == {"flashcards"}, "no due_count on the legacy path"
        assert [c["id"] for c in body["flashcards"]] == [c["id"] for c in LIST_ROWS]
        assert all(set(c) == set(LEGACY_LIST_COLS.split(",")) for c in body["flashcards"])
        od.assert_not_called()

    def test_gate_off_topic_filter_unchanged(self):
        r, calls, _ = _list(gate=False, query="?topic=T")
        assert calls["select_kwargs"]["filters"] == {"user_id": f"eq.{USER_ID}", "topic": "eq.T"}
