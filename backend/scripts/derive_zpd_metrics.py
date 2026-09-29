"""
Nightly ZPD metrics (learning loop PKG-14; spec §10 rung 2, the ZPD report LOG block).

For every learner_state row with at least one opportunity (or one --user), it
recomputes the four derived columns from the node's evidence journal
(node_mastery_events rows with event_type 'evidence' and a question_hash):

  htc_k            mean max_rung over the CORRECT opportunities among the last
                   HTC_K_WINDOW (hints-to-criterion); None when none is correct
  unassisted_next  share of the last BAND_WINDOW opportunities answered
                   correctly, unassisted, at rung 0
  assist_gap       (correct share among the assisted opportunities in the last
                   BAND_WINDOW) − (correct share among the unassisted ones);
                   None when either side has no opportunity
  in_zone          assist_gap ≥ ZPD_IN_ZONE_MIN_GAP, assisted success ≥
                   ZPD_IN_ZONE_MIN_ASSISTED and unassisted_next <
                   ZPD_IN_ZONE_MAX_UNASSISTED; None when assist_gap is None

and writes them through learning.learner_state.write_metrics — an UPDATE of
those columns only (spec §13 A79; invariants 1 and 20). The values are a pure
function of the journal, so a re-run writes the same values.

Every run, --dry-run included, also prints one read-only `REPORT <json>` line
(spec §10; A15/A20/A21/A22): cost per band, per session (or per user-day when
not every loop request maps to a session), the check_items total, the tier and
grader_backend mix, cap hits, and each course's check-item coverage.

Run from backend/:
    python scripts/derive_zpd_metrics.py                  # every row, then the report
    python scripts/derive_zpd_metrics.py --dry-run        # print the would-be rows; write nothing
    python scripts/derive_zpd_metrics.py --user <id>      # one student's rows
    python scripts/derive_zpd_metrics.py --expect-rows    # exit 2 when learner_state is empty
    python scripts/derive_zpd_metrics.py --from <iso> --to <iso>   # the report window

Exit codes: 0 normal; 1 a row or a report read failed (FAIL / REPORT_FAIL
lines; the rest still runs); 2 learner_state has rows with opportunities but
the evidence read returned nothing for every one of them (a keyspace mismatch,
the silent-empty class), or --expect-rows found no rows at all.

Loads .env.staging without overriding what is already set, so run it under
`dotenv -f .env.<env> run -- ...` for any other environment, and check the
project it prints first.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
if __name__ == "__main__":  # an operator run; importing the module (tests) loads no env file
    load_dotenv(BASE / ".env.staging")

sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from learning.learner_state import opportunity_states, write_metrics  # noqa: E402
from learning.params import (  # noqa: E402
    BAND_WINDOW,
    HTC_K_WINDOW,
    KPI_TREND_WEEKS,
    ZPD_IN_ZONE_MAX_UNASSISTED,
    ZPD_IN_ZONE_MIN_ASSISTED,
    ZPD_IN_ZONE_MIN_GAP,
)
from services.check_item_service import coverage  # noqa: E402

_EVIDENCE_COLS = "id,created_at,correct,assisted,max_rung,question_hash,channel"
# spec §13 A36: rows one apply_graph_update call writes share created_at and
# carry their apply order in evidence_seq (NULL on rows written before it)
_EVIDENCE_ORDER = "created_at.desc,evidence_seq.desc.nullslast,id.desc"
_USAGE_COLS = "id,user_id,request_id,task,cost_usd,created_at"
_EVENT_COLS = "id,event_type,user_id,request_id,payload,created_at"
_REPORT_EVENTS = ("zpd.step", "ai.budget_capped", "learn.session_closed")
SERIES_SLOTS = (  # spec §8 invariant 6
    "check_items",
    "grader",
    "grader_second",
    "decision",
    "loop_tutor",
    "loop_tutor_lite",
    "loop_tutor_deep",
    "session_close",
)
_COURSE_ASSET_SLOT = "check_items"  # course assets, not a student's session
_UNKNOWN = "unknown"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── the derived columns (pure) ───────────────────────────────────────────────


def _opportunities(rows: list[dict]) -> list[dict]:
    """Evidence rows that are opportunities: they name the item answered."""
    return [r for r in rows if r.get("question_hash")]


def _share(rows: list[dict], pred) -> float | None:
    return sum(1 for r in rows if pred(r)) / len(rows) if rows else None


def _unassisted_zero(r: dict) -> bool:
    return bool(r.get("correct")) and not r.get("assisted") and int(r.get("max_rung") or 0) == 0


def compute(opps: list[dict]) -> dict:
    """The four derived values from opportunities NEWEST FIRST (already filtered)."""
    recent = opps[:HTC_K_WINDOW]
    rungs = [int(r.get("max_rung") or 0) for r in recent if r.get("correct")]
    htc_k = sum(rungs) / len(rungs) if rungs else None

    window = opps[:BAND_WINDOW]
    unassisted_next = _share(window, _unassisted_zero)
    assisted = [r for r in window if r.get("assisted")]
    unassisted = [r for r in window if not r.get("assisted")]
    assisted_rate = _share(assisted, lambda r: bool(r.get("correct")))
    unassisted_rate = _share(unassisted, lambda r: bool(r.get("correct")))
    if assisted_rate is None or unassisted_rate is None:
        assist_gap = in_zone = None
    else:
        assist_gap = assisted_rate - unassisted_rate
        in_zone = (
            assist_gap >= ZPD_IN_ZONE_MIN_GAP
            and assisted_rate >= ZPD_IN_ZONE_MIN_ASSISTED
            and unassisted_next < ZPD_IN_ZONE_MAX_UNASSISTED
        )
    return {
        "htc_k": htc_k,
        "unassisted_next": unassisted_next,
        "assist_gap": assist_gap,
        "in_zone": in_zone,
    }


def _evidence(node_id: str) -> list[dict]:
    """The node's newest evidence journal rows (node ids are per student)."""
    return (
        table("node_mastery_events").select(
            _EVIDENCE_COLS,
            filters={"node_id": f"eq.{node_id}", "event_type": "eq.evidence"},
            order=_EVIDENCE_ORDER,
            limit=BAND_WINDOW * 2,
        )
        or []
    )


# ── the cost and mix report (pure) ───────────────────────────────────────────


def _usd(value) -> float:
    return float(value) if value is not None else 0.0


def _day(raw) -> str:
    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date().isoformat()


def _count(values) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for v in values:
        out[v] += 1
    return dict(sorted(out.items()))


def report(
    usage: list[dict],
    steps: list[dict],
    caps: list[dict],
    *,
    sessions_by_request: dict[str, str],
) -> dict:
    """Spec §10's cost and mix report over one window. Never invents a band, a
    session or a zero count: an unattributable row goes under "unknown", and a
    payload key that is absent is not counted."""
    bands: dict[str, set[str]] = defaultdict(set)
    for step in steps:
        band = (step.get("payload") or {}).get("band")
        if step.get("request_id") and band:
            bands[step["request_id"]].add(band)

    loop_rows = [
        r for r in usage if r.get("task") in SERIES_SLOTS and r.get("task") != _COURSE_ASSET_SLOT
    ]
    per_band: dict[str, float] = defaultdict(float)
    for r in loop_rows:
        seen = bands.get(r.get("request_id") or "", set())
        per_band[next(iter(seen)) if len(seen) == 1 else _UNKNOWN] += _usd(r.get("cost_usd"))

    out: dict = {
        "cost_per_band": dict(sorted(per_band.items())),
        "check_items_usd": sum(
            _usd(r.get("cost_usd")) for r in usage if r.get("task") == _COURSE_ASSET_SLOT
        ),
        "tier_mix": _count(
            p["tier"] for p in ((s.get("payload") or {}) for s in steps) if "tier" in p
        ),
        "grader_backend_mix": _count(
            p["grader_backend"]
            for p in ((s.get("payload") or {}) for s in steps)
            if "grader_backend" in p
        ),
        "cap_hits": _count(
            f"{p.get('scope')}/{p.get('level')}" for p in ((c.get("payload") or {}) for c in caps)
        ),
    }
    if loop_rows and all(r.get("request_id") in sessions_by_request for r in loop_rows):
        per_session: dict[str, float] = defaultdict(float)
        for r in loop_rows:
            per_session[sessions_by_request[r["request_id"]]] += _usd(r.get("cost_usd"))
        out["cost_per_session"] = dict(sorted(per_session.items()))
    else:
        per_user_day: dict[str, float] = defaultdict(float)
        for r in loop_rows:
            key = f"{r.get('user_id') or _UNKNOWN}/{_day(r.get('created_at'))}"
            per_user_day[key] += _usd(r.get("cost_usd"))
        out["cost_per_user_day"] = dict(sorted(per_user_day.items()))
    return out


# ── the reads ────────────────────────────────────────────────────────────────


def _window_rows(name: str, cols: str, frm: str, to: str, extra: dict | None = None) -> list[dict]:
    filters = {"created_at": [f"gte.{frm}", f"lt.{to}"], **(extra or {})}
    return list(page_all(table(name), cols, filters=filters, order="created_at,id"))


class _GraphNodesRead:
    """A read-only `page_all` handle over graph_nodes (invariant 1 allows
    `table("graph_nodes")` only as a direct read; check_item_service's pattern)."""

    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


def _course_ids() -> list[str]:
    rows = page_all(
        _GraphNodesRead(), "id,course_id", filters={"course_id": "not.is.null"}, order="id"
    )
    return sorted({r["course_id"] for r in rows if r.get("course_id")})


def _report_line(frm: str, to: str) -> tuple[dict, bool]:
    """The REPORT dict and whether any of its reads failed (REPORT_FAIL lines)."""
    failed = False
    usage: list[dict] = []
    events: list[dict] = []
    try:
        usage = _window_rows("llm_usage", _USAGE_COLS, frm, to)
    except Exception as exc:
        print(f"REPORT_FAIL llm_usage {type(exc).__name__}")
        failed = True
    try:
        events = _window_rows(
            "events",
            _EVENT_COLS,
            frm,
            to,
            {"event_type": f"in.({','.join(_REPORT_EVENTS)})"},
        )
    except Exception as exc:
        print(f"REPORT_FAIL events {type(exc).__name__}")
        failed = True
    sessions_by_request = {
        e["request_id"]: (e.get("payload") or {})["session_id"]
        for e in events
        if e.get("request_id") and (e.get("payload") or {}).get("session_id")
    }
    out = report(
        usage,
        [e for e in events if e.get("event_type") == "zpd.step"],
        [e for e in events if e.get("event_type") == "ai.budget_capped"],
        sessions_by_request=sessions_by_request,
    )
    out["window"] = {"from": frm, "to": to}
    try:
        out["check_item_coverage"] = {c: list(coverage(c)) for c in _course_ids()}
    except Exception as exc:
        print(f"REPORT_FAIL check_items {type(exc).__name__}")
        failed = True
    return out, failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the would-be rows; write nothing")
    ap.add_argument("--user", help="one student's rows only")
    ap.add_argument("--expect-rows", action="store_true", help="exit 2 when there are no rows")
    ap.add_argument("--from", dest="frm", help="report window start (ISO; default to − 4 weeks)")
    ap.add_argument("--to", help="report window end, exclusive (ISO; default now)")
    args = ap.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).netloc or REST_URL}")
    to = args.to or _now().isoformat()
    frm = (
        args.frm
        or (
            datetime.fromisoformat(to.replace("Z", "+00:00")) - timedelta(weeks=KPI_TREND_WEEKS)
        ).isoformat()
    )

    rc = 0
    states = opportunity_states(args.user)
    tag = " (dry run)" if args.dry_run else ""
    print(f"{len(states)} rows{tag}")
    any_evidence = False
    for st in states:
        uid, nid = st["user_id"], st["node_id"]
        try:
            rows = _evidence(nid)
            any_evidence = any_evidence or bool(rows)
            values = compute(_opportunities(rows)[:BAND_WINDOW])
            print(f"ROW {uid} {nid} {json.dumps(values, sort_keys=True)}{tag}")
            if not args.dry_run:
                write_metrics(uid, nid, **values)
        except Exception as exc:
            print(f"FAIL {uid} {nid} {type(exc).__name__}")
            rc = 1

    rep, report_failed = _report_line(frm, to)
    print("REPORT " + json.dumps(rep, sort_keys=True))
    if report_failed:
        rc = 1

    if states and not any_evidence:
        print("SILENT_EMPTY learner_state has opportunities but no evidence rows were read")
        return 2
    if args.expect_rows and not states:
        print("SILENT_EMPTY --expect-rows and learner_state has no rows")
        return 2
    return rc


if __name__ == "__main__":
    sys.exit(main())
