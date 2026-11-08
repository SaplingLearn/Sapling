"""An in-memory learning store behind the single graph writer's RPCs (spec §13
A123 tests): the evidence snapshot/commit/receipt and the void
pending/snapshot/commit, emulating migration 20261108072715's SQL — ownership,
graph and learner_state versions bumped on every write, the topology compare,
the staff-retire refusal under the item's lock, the void row-set checks, writes
only where a value differs, misconception closure.

Hermetic: it proves what the Python writer and replay compute and send, never
PostgreSQL's locks or rollbacks (tests/integration/test_learning_evidence_void_db.py
runs the real functions). Values are stored as the plan carries them: a
float/ISO-timestamp round trip through Postgres and PostgREST is exact, so this
is what the next snapshot would read back.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from learning.learner_state import _parse_ts

_STATE_KEYS = (
    "user_id", "node_id", "p_known", "n_strong_unassisted", "streak_unassisted",
    "max_streak_unassisted", "opps", "fsrs_d", "fsrs_s", "fsrs_last_review_at",
    "fsrs_due_at", "last_evidence_at", "updated_at",
)
_STATE_COMPARE = _STATE_KEYS[2:]


def _ts(value):
    return _parse_ts(value) if value is not None else None


def _same_state(a: dict, b: dict) -> bool:
    for key in _STATE_COMPARE:
        x, y = a.get(key), b.get(key)
        if key.endswith("_at"):
            x, y = _ts(x), _ts(y)
        if x != y:
            return False
    return True


class Clock:
    """A settable UTC clock for evidence_transaction's `datetime.now`."""

    def __init__(self, start: datetime | None = None):
        self.now_value = start or datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)

    def advance(self, **delta) -> datetime:
        self.now_value = self.now_value + timedelta(**delta)
        return self.now_value

    def now(self, tz=None):  # the datetime.now signature evidence_transaction calls
        return self.now_value


class _Select:
    def __init__(self, db: "LearningJournalDB", name: str):
        self.db, self.name = db, name

    def select(self, columns="*", filters=None, **kwargs):
        filters = filters or {}
        if self.name != "graph_nodes":
            return []
        user = (filters.get("user_id") or "eq.")[3:]
        course = filters.get("course_id")
        rows = [n for n in self.db.nodes.values() if n["user_id"] == user]
        if course:
            rows = [n for n in rows if n["course_id"] == course[3:]]
        return [deepcopy(n) for n in sorted(rows, key=lambda n: n["id"])]


class LearningJournalDB:
    """One course graph per student, its learner_state, the evidence journal,
    the void record, the A113 review decisions and the misconceptions."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []  # {user_id, source, target}
        self.states: dict[tuple[str, str], dict] = {}
        self.journal: list[dict] = []
        self.voids: dict[str, dict] = {}
        self.reviews: dict[tuple[str, str], str] = {}
        self.misconceptions: dict[str, dict] = {}
        self.attempts: list[dict] = []
        self.receipts: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.void_commits: list[dict] = []

    # ── setup ──────────────────────────────────────────────────────────────
    def add_node(self, user_id: str, course_id: str, node_id: str, name: str | None = None) -> None:
        self.nodes[node_id] = {
            "id": node_id, "user_id": user_id, "course_id": course_id,
            "concept_name": name or node_id, "mastery_score": 0.0,
            "mastery_tier": "unexplored", "times_studied": 0, "evidence_version": 0,
        }

    def add_prereq(self, user_id: str, prereq: str, dependent: str) -> None:
        self.edges.append({"user_id": user_id, "source": prereq, "target": dependent})

    def retire(self, course_id: str, question_hash: str, status: str = "retired") -> None:
        self.reviews[(course_id, question_hash)] = status

    def table(self, name: str):
        return _Select(self, name)

    # ── reads the tests assert on ──────────────────────────────────────────
    def state(self, user_id: str, node_id: str) -> dict | None:
        row = self.states.get((user_id, node_id))
        return deepcopy(row) if row is not None else None

    def node_rows(self, user_id: str, course_id: str) -> list[str]:
        return sorted(
            n for n, row in self.nodes.items()
            if row["user_id"] == user_id and row["course_id"] == course_id
        )

    def _course_edges(self, user_id: str, course_id: str | None, touching=None) -> list[dict]:
        out = []
        for e in self.edges:
            s, t = self.nodes.get(e["source"]), self.nodes.get(e["target"])
            if (
                e["user_id"] != user_id or s is None or t is None
                or s["user_id"] != user_id or t["user_id"] != user_id
                or s["course_id"] != t["course_id"]
                or (course_id is not None and s["course_id"] != course_id)
            ):
                continue
            if touching is not None and not ({e["source"], e["target"]} & touching):
                continue
            out.append({"source": e["source"], "target": e["target"]})
        return sorted(out, key=lambda e: (e["source"], e["target"]))

    def _user_rows(self, user_id: str) -> list[dict]:
        return [r for r in self.journal if self.nodes[r["node_id"]]["user_id"] == user_id]

    def _write_state(self, row: dict, *, touch: bool) -> bool:
        key = (row["user_id"], row["node_id"])
        old = self.states.get(key)
        if old is not None and _same_state(old, row):
            return False
        new = {k: deepcopy(row.get(k)) for k in _STATE_KEYS}
        new.update({"htc_k": None, "unassisted_next": None, "assist_gap": None, "in_zone": None})
        new["evidence_version"] = (old["evidence_version"] + 1) if old is not None else 0
        touch_at = old.get("evidence_touch_at") if old is not None else None
        if touch:
            touch_at = max(filter(None, (_ts(touch_at), _ts(row["updated_at"]))), default=None)
            touch_at = touch_at.isoformat() if touch_at else None
        new["evidence_touch_at"] = touch_at
        self.states[key] = new
        return True

    def _write_mirror(self, user_id: str, mirror: dict) -> bool:
        node = self.nodes[mirror["id"]]
        assert node["user_id"] == user_id
        changed = {k: v for k, v in mirror.items() if k != "id" and node.get(k) != v}
        if not changed:
            return False
        node.update(deepcopy(changed))
        node["evidence_version"] += 1
        return True

    # ── the RPCs ───────────────────────────────────────────────────────────
    def rpc(self, name: str, params: dict):
        self.calls.append((name, deepcopy(params)))
        return getattr(self, "_" + name)(deepcopy(params))

    def _learning_evidence_receipt(self, p):
        r = self.receipts.get(p["p_operation_id"])
        if r is None:
            return {"status": "missing"}
        if r["user_id"] != p["p_user_id"]:
            return {"status": "conflict"}
        return {"status": "committed", "receipt": deepcopy(r)}

    def _learning_evidence_snapshot(self, p):
        user, course, node_ids = p["p_user_id"], p["p_course_id"], set(p["p_node_ids"])
        for n in node_ids:
            row = self.nodes.get(n)
            if row is None or row["user_id"] != user or (course is not None and row["course_id"] != course):
                return {"status": "ownership"}
        es = self._course_edges(user, course, touching=node_ids)
        ids = sorted(node_ids | {e["source"] for e in es} | {e["target"] for e in es})
        rows = self._user_rows(user)
        checks = [
            {**c,
             "count": sum(r.get("session_id") == c["session_id"] and r.get("question_hash") == c["question_hash"] for r in rows),
             "global_count": sum(r.get("question_hash") == c["question_hash"] for r in rows)}
            for c in sorted(p["p_checks"], key=lambda c: (c["session_id"], c["question_hash"]))
        ]
        return {
            "status": "snapshot",
            "nodes": [
                {k: deepcopy(self.nodes[n][k]) for k in
                 ("id", "user_id", "course_id", "concept_name", "mastery_score", "times_studied", "evidence_version")}
                for n in ids
            ],
            "states": [deepcopy(self.states[(user, n)]) for n in ids if (user, n) in self.states],
            "edges": es,
            "checks": checks,
        }

    def _learning_evidence_commit(self, p):
        user, course, op, plan = p["p_user_id"], p["p_course_id"], p["p_operation_id"], p["p_plan"]
        if op in self.receipts:
            r = self.receipts[op]
            if r["plan"] != plan or r["input_fingerprint"] != p["p_input_fingerprint"]:
                return {"status": "conflict"}
            return {"status": "replay", "receipt": {k: deepcopy(v) for k, v in r.items() if k != "plan"}}
        retired = sorted({
            (self.nodes[e["node_id"]]["course_id"], e["question_hash"])
            for e in plan["events"]
            if isinstance(e.get("check_item_id"), str) and isinstance(e.get("question_hash"), str)
            and self.reviews.get((self.nodes[e["node_id"]]["course_id"], e["question_hash"])) == "retired"
        })
        if retired:
            return {"status": "retired", "items": [{"course_id": c, "question_hash": q} for c, q in retired]}
        ids = sorted(n["id"] for n in plan["nodes"])
        grade_ids = {e["node_id"] for e in plan["events"]}
        for n in ids:
            row = self.nodes.get(n)
            if row is None or row["user_id"] != user or (course is not None and row["course_id"] != course):
                return {"status": "ownership"}
        for n in plan["nodes"]:
            if self.nodes[n["id"]]["evidence_version"] != n["version"]:
                return {"status": "stale"}
        if self._course_edges(user, course, touching=grade_ids) != plan["edges"]:
            return {"status": "stale"}
        for s in plan["states_expected"]:
            current = self.states.get((user, s["node_id"]))
            if (current["evidence_version"] if current else None) != s["version"]:
                return {"status": "stale"}
        rows = self._user_rows(user)
        for c in plan["checks"]:
            if sum(r.get("session_id") == c["session_id"] and r.get("question_hash") == c["question_hash"] for r in rows) != c["count"]:
                return {"status": "stale"}
            if sum(r.get("question_hash") == c["question_hash"] for r in rows) != c["global_count"]:
                return {"status": "stale"}
        for s in plan["state_rows"]:
            self._write_state(s, touch=True)
        for m in plan["mirrors"]:
            self._write_mirror(user, m)
        for e in plan["events"]:
            row = {k: deepcopy(v) for k, v in e.items()}
            for key in ("retention", "same_session_recheck", "propagated_to", "planning_observation"):
                row.setdefault(key, None)
            self.journal.append(row)
        receipt = {
            "operation_id": op, "user_id": user, "course_id": course,
            "input_fingerprint": p["p_input_fingerprint"], "changes": deepcopy(plan["changes"]),
            "posteriors": {m["id"]: m["mastery_score"] for m in plan["mirrors"]},
            "observations": [deepcopy(e["planning_observation"]) for e in plan["events"]
                             if isinstance(e.get("planning_observation"), dict)],
        }
        self.receipts[op] = {**receipt, "plan": deepcopy(plan)}
        return {"status": "committed", "receipt": receipt}

    # ── A123 ───────────────────────────────────────────────────────────────
    def _item_rows(self, user: str | None, course: str, qh: str) -> list[dict]:
        return [
            r for r in self.journal
            if self.nodes[r["node_id"]]["course_id"] == course and r.get("question_hash") == qh
            and r.get("check_item_id") and (user is None or self.nodes[r["node_id"]]["user_id"] == user)
        ]

    def _learning_evidence_void_pending(self, p):
        users: dict[str, int] = {}
        for r in self._item_rows(None, p["p_course_id"], p["p_question_hash"]):
            if r["id"] not in self.voids:
                u = self.nodes[r["node_id"]]["user_id"]
                users[u] = users.get(u, 0) + 1
        return {"status": "pending", "users": users}

    def _journal_order(self, row):
        seq = row.get("evidence_seq")
        return (_ts(row["created_at"]), seq is None, seq if seq is not None else 0, row["id"])

    def _learning_evidence_void_snapshot(self, p):
        user, course, qh = p["p_user_id"], p["p_course_id"], p["p_question_hash"]
        ids = self.node_rows(user, course)
        journal = []
        for r in sorted((r for r in self.journal if r["node_id"] in ids), key=self._journal_order):
            obs = r.get("planning_observation")
            journal.append({
                **{k: deepcopy(r.get(k)) for k in (
                    "id", "node_id", "created_at", "evidence_seq", "channel", "correct", "weight",
                    "assisted", "max_rung", "reason", "confidence", "session_id", "question_hash",
                    "check_item_id", "same_session_recheck", "retention", "propagated_to")},
                "planning_recheck": obs.get("same_session_recheck") if isinstance(obs, dict) else None,
                "void": r["id"] in self.voids,
            })
        misconceptions = []
        for mid in sorted(self.misconceptions):
            m = self.misconceptions[mid]
            if m["user_id"] == user and m["node_id"] in ids and m["resolved_at"] is None:
                misconceptions.append({
                    "id": mid, "node_id": m["node_id"], "count": m["count"],
                    "check_item_id": m["check_item_id"],
                    "attempts": [
                        {k: a[k] for k in ("course_id", "question_hash", "check_item_id")}
                        for a in self.attempts if a["misconception_id"] == mid
                    ],
                })
        return {
            "status": "snapshot",
            "retired": self.reviews.get((course, qh)) == "retired",
            "nodes": [
                {k: deepcopy(self.nodes[n][k]) for k in
                 ("id", "concept_name", "mastery_score", "mastery_tier", "evidence_version")}
                for n in ids
            ],
            "states": [deepcopy(self.states[(user, n)]) for n in ids if (user, n) in self.states],
            "edges": self._course_edges(user, course),
            "journal": journal,
            "retired_hashes": sorted(q for (c, q), s in self.reviews.items() if c == course and s == "retired"),
            "misconceptions": misconceptions,
        }

    def _learning_evidence_void_commit(self, p):
        user, course, qh, op, plan = (
            p["p_user_id"], p["p_course_id"], p["p_question_hash"], p["p_operation_id"], p["p_plan"]
        )
        assert sorted(plan) == sorted(
            ["voids", "nodes", "states_expected", "edges", "state_rows", "mirrors", "misconceptions"]
        )
        if self.reviews.get((course, qh)) != "retired":
            return {"status": "not_retired"}
        item_rows = {r["id"]: r for r in self._item_rows(user, course, qh)}
        void_ids = sorted(set(plan["voids"]))
        assert all(v in item_rows for v in void_ids), "a void names a row outside the item"
        if set(item_rows) - set(void_ids):
            return {"status": "stale"}
        ids = sorted(n["id"] for n in plan["nodes"])
        assert ids == sorted(s["node_id"] for s in plan["state_rows"]) == sorted(m["id"] for m in plan["mirrors"])
        for n in plan["nodes"]:
            row = self.nodes.get(n["id"])
            if row is None or row["user_id"] != user or row["course_id"] != course:
                return {"status": "ownership"}
            if row["evidence_version"] != n["version"]:
                return {"status": "stale"}
        if self._course_edges(user, course) != plan["edges"]:
            return {"status": "stale"}
        for s in plan["states_expected"]:
            current = self.states.get((user, s["node_id"]))
            if (current["evidence_version"] if current else None) != s["version"]:
                return {"status": "stale"}
        for m in plan["misconceptions"]:
            row = self.misconceptions.get(m["id"])
            if row is None or row["user_id"] != user or row["resolved_at"] is not None or row["count"] != m["count"]:
                return {"status": "stale"}
        voided = 0
        for v in void_ids:
            if v not in self.voids:
                r = item_rows[v]
                self.voids[v] = {
                    "event_id": v, "user_id": user, "node_id": r["node_id"], "course_id": course,
                    "question_hash": qh, "check_item_id": r["check_item_id"],
                    "session_id": r.get("session_id"), "event_created_at": r["created_at"],
                    "reason": "item_retired", "operation_id": op,
                }
                voided += 1
        states = sum(self._write_state(s, touch=False) for s in plan["state_rows"])
        mirrors = sum(self._write_mirror(user, m) for m in plan["mirrors"])
        closed = 0
        for m in plan["misconceptions"]:
            row = self.misconceptions[m["id"]]
            if row["resolved_at"] is None:
                row["resolved_at"], row["resolved_reason"] = "closed", "evidence_void"
                closed += 1
        out = {"status": "committed", "voided": voided, "states": states, "mirrors": mirrors,
               "misconceptions": closed}
        self.void_commits.append(out)
        return out


def install(monkeypatch, db: LearningJournalDB, clock: Clock | None = None) -> None:
    """Route the single writer's RPCs and graph_nodes read through `db`, and
    silence its post-commit side effects (streak, achievements, offerings)."""
    import services.academics as academics
    import services.achievement_service as achievements
    import services.graph_service as gs
    from learning import evidence_transaction as tx

    monkeypatch.setattr(tx, "rpc", db.rpc)
    monkeypatch.setattr(gs, "table", db.table)
    monkeypatch.setattr(gs, "touch_streak_safe", lambda user_id: None)
    monkeypatch.setattr(achievements, "check_achievements", lambda *a, **k: None)
    monkeypatch.setattr(academics, "user_offering_ids_for_course", lambda *a, **k: [])
    if clock is not None:
        monkeypatch.setattr(tx, "datetime", clock)
