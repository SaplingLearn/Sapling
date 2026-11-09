"""Grouping for the admin db_user_scope report (`GET /api/admin/analytics/db-scope`).

docs/security/db-user-scope-rollout.md: the "read the report" step. The route
groups the db.* events every worker wrote to ``events`` by one key —
:func:`key_of`, the same normalisation ``db/scope_report.py`` uses for this
process's in-memory tally, so one divergence has one key in both views.

Two sources for the same groups:

* :func:`group_rpc_rows` -- the ``db_scope_divergences()`` SQL function
  (migration 20261109023455) groups in Postgres by the RAW payload values the
  key is built from; this applies :func:`key_of` to each raw group and merges
  any that normalise to the same key. No scan cap, no window cap of its own.
* :func:`group_rows` -- the fallback before that migration: the route's capped
  scan of event rows, grouped here.

Both return ``{key: {"count", "users": set, "first", "last", "rids"}}``;
:func:`ranked` turns that into the report's ``top`` list.
"""
from __future__ import annotations

from db import scope_report

#: The raw-key layout of `db_scope_divergences()`'s `k` array (see migration).
_RAW_FIELDS = ("event_type", "kind", "mode", "method", "route", "table", "op",
               "status", "code", "service_count", "scoped_count")
_SAMPLE_RIDS = 3


def _as_int(value) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def key_of(event_type: str, payload: dict) -> tuple:
    """The grouping key for one db.* event row — `scope_report.key_of`, the
    same key the in-process tally uses. Rows written before the report
    existed carry no kind/method/op (and `error` where newer rows carry
    `status`); derive what they imply."""
    status = payload.get("status", payload.get("error"))
    kind = payload.get("kind")
    if not kind:
        if event_type == "db.unscoped_query":
            kind = "no_subject"
        elif event_type == "db.rls_denied":
            kind = "denied"
        elif status is not None:
            kind = "error"
        else:
            svc, scp = _as_int(payload.get("service_count")), _as_int(payload.get("scoped_count"))
            kind = "fewer_rows" if scp < svc else "more_rows" if scp > svc else "different_ids"
    mode = payload.get("mode") or {"db.rls_shadow_divergence": "shadow",
                                   "db.rls_denied": "enforce"}.get(event_type, "?")
    # Same defaults as scope_report.record: "?" for an unknown method/route/
    # target/op, None for an absent status/code.
    return scope_report.key_of({
        "event": event_type, "kind": kind, "mode": mode,
        "method": payload.get("method") or "?", "route": payload.get("route") or "?",
        "target": payload.get("table") or "?", "op": payload.get("op") or "?",
        "status": status, "code": payload.get("code"),
    })


def _new_group() -> dict:
    return {"count": 0, "users": set(), "first": None, "last": None, "rids": []}


def _span(g: dict, first, last) -> None:
    if first:
        g["first"] = first if g["first"] is None or first < g["first"] else g["first"]
    if last:
        g["last"] = last if g["last"] is None or last > g["last"] else g["last"]


def group_rows(rows: list[dict]) -> dict[tuple, dict]:
    """Group scanned event rows (newest first) — the pre-migration path."""
    groups: dict[tuple, dict] = {}
    for r in rows:
        payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
        g = groups.setdefault(key_of(r.get("event_type") or "?", payload), _new_group())
        g["count"] += 1
        if r.get("user_id"):
            g["users"].add(r["user_id"])
        at = r.get("created_at")
        _span(g, at, at)
        rid = r.get("request_id")
        if rid and len(g["rids"]) < _SAMPLE_RIDS and rid not in g["rids"]:
            g["rids"].append(rid)
    return groups


def group_rpc_rows(rows: list[dict]) -> tuple[dict[tuple, dict], int]:
    """Groups and the event total from `db_scope_divergences()` rows. Raises
    on a malformed answer (the caller falls back to the scan)."""
    groups: dict[tuple, dict] = {}
    samples: dict[tuple, list[tuple[str, str]]] = {}
    total = 0
    for row in rows:
        raw = row["k"]
        if not isinstance(raw, list) or len(raw) != len(_RAW_FIELDS):
            raise ValueError("db_scope_divergences: unexpected key shape")
        fields = dict(zip(_RAW_FIELDS, raw))
        event_type = fields.pop("event_type") or "?"
        key = key_of(event_type, fields)
        g = groups.setdefault(key, _new_group())
        n = int(row["n"])
        g["count"] += n
        total += n
        g["users"].update(u for u in row.get("users") or [] if u)
        _span(g, row.get("first_seen"), row.get("last_seen"))
        samples.setdefault(key, []).extend(
            (s.get("at") or "", s["id"]) for s in row.get("request_ids") or [] if s.get("id"))
    for key, pairs in samples.items():
        seen: list[str] = []
        for _at, rid in sorted(pairs, key=lambda p: p[0], reverse=True):
            if rid not in seen:
                seen.append(rid)
            if len(seen) == _SAMPLE_RIDS:
                break
        groups[key]["rids"] = seen
    return groups, total


def ranked(groups: dict[tuple, dict], limit: int) -> list[dict]:
    """The report's `top`: most events first (ties by route, then target)."""
    order = sorted(groups.items(), key=lambda kv: (-kv[1]["count"], kv[0][4], kv[0][5]))
    return [
        {**dict(zip(scope_report.KEY_FIELDS, key)), "count": g["count"], "users": len(g["users"]),
         "first_seen": g["first"], "last_seen": g["last"], "sample_request_ids": g["rids"]}
        for key, g in order[:limit]
    ]
