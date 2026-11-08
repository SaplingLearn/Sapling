#!/usr/bin/env python3
"""Export the within-student trial's de-identified long table
(learning_trial.table; docs/research/learning-loop/2026-11-08-within-student-
trial-preregistration.md).

Who: the students whose `user_settings.loop_arm` is the trial's arm label
(`--arm-label`). Setting that label IS trial enrollment, so the owner sets it
only for students with recorded research consent (the preregistration's
consent section); a student who withdraws has the label cleared and is not
exported.

What it reads (read-only, PostgREST through db.connection):
  - the students' course concepts (graph_nodes: id, course, concept name — the
    name only to form the course-level concept key, never exported);
  - each concept's A112 anchor, its FIRST valid graded evidence in the
    journal's total order (learning/loop_state_store.py::evidence_spans's rule,
    restated here because scripts may not import that ZPD-layer module —
    tests/test_learning_zpd_policy.py; a test pins the two equal). A row the
    student's void record names (learning_evidence_voids, spec §13 A123:
    graded against an item staff retired) is no evidence and never anchors;
  - the anchor journal rows and their sessions' probe histories -> the probe
    pretest (learning.learning_gain.pretest_outcome, A112's own rule);
  - posttest_poses, every window;
  - check_item_reviews and check_item_reports for the posed items (A113).
It writes one row per (student, concept, window) whose window had opened by
`--as-of`: the assigned arm (learning.arms.variant_for under the label; the
treatment is `--treatment-variant`), the pretest, the post-test status and its
rung-0 outcome, an item exclusion (retired; or reported with no staff
approval at or after the last report), and the recorded delay.

De-identified: every id leaves only as a per-export salted HMAC
(learning_trial.deidentify; the salt is drawn fresh and never written or
printed), so an export cannot be joined to another export or to the
database. No text leaves — no concept names, items, answers or timestamps:
booleans, enums, window days, a rounded delay and pseudonyms. Rows are sorted
by pseudonym, so their order says nothing about the underlying ids.

Dry run by default: reads, builds the table in memory and prints the flow
counts (no ids). `--out PATH` writes the CSV (refuses an existing file).
Run from backend/:
    python scripts/export_learning_trial.py --arm-label <label> --treatment-variant A
    python scripts/export_learning_trial.py --arm-label <label> --treatment-variant A --out trial.csv

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the `Project:` line it prints first. Needs the A112/A113/A123 migrations
(20261108041742_learning_posttest_windows.sql, 20261108041639_learning_item_quality.sql,
20261108072715_learning_evidence_void.sql).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import SUPABASE_URL, page_all, pg_quote_value, table  # noqa: E402
from learning import void_store  # noqa: E402
from learning.arms import variant_for  # noqa: E402
from learning.item_alignment import concept_key  # noqa: E402
from learning.learning_gain import posttest_outcome, pretest_outcome  # noqa: E402
from learning.params import POSTTEST_POSE_TTL_HOURS, POSTTEST_WINDOWS_DAYS  # noqa: E402
from learning_trial.deidentify import Pseudonymizer  # noqa: E402
from learning_trial.table import CONTROL, STATUSES, TREATMENT, TrialRow, write_csv  # noqa: E402

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
_SUPABASE_SUFFIX = ".supabase.co"
#: an arm label safe inside a PostgREST `eq.` filter (the owner sets it in SQL)
_LABEL = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
#: ids per `in.(…)` read, so a GET URL stays well under common proxy limits
_IN_BATCH = 100
_POSE_COLS = (
    "node_id,course_id,window_days,question_hash,posed_at,answered_at,correct,max_rung,"
    "anchor_event_id,days_since_evidence"
)
#: the evidence journal's total order (read_planning_history's): the first row of a
#: node in it is the node's A112 anchor (learning/loop_state_store.py::evidence_spans)
_JOURNAL_ORDER = "created_at.asc,evidence_seq.asc.nullslast,id.asc"
#: an anchor row, with what learning_gain.pretest_outcome binds its envelope to
_ANCHOR_COLS = (
    "id,node_id,session_id,question_hash,check_item_id,channel,correct,assisted,max_rung,"
    "reason,planning_observation"
)


def _project_ref() -> str:
    """The project SUPABASE_URL points at (scripts/backfill_check_items.py's rule)."""
    host = (urlparse(SUPABASE_URL).hostname or "").lower()
    if not host or host in _LOCAL_HOSTS:
        return "local"
    if host.endswith(_SUPABASE_SUFFIX):
        return host[: -len(_SUPABASE_SUFFIX)].split(".")[0]
    return host


def _ts(raw) -> datetime | None:
    if isinstance(raw, datetime):
        ts = raw
    else:
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _in(values: Iterable[str]) -> str:
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


def _batches(values: list[str]):
    for start in range(0, len(values), _IN_BATCH):
        yield values[start : start + _IN_BATCH]


# ── reads (DB) ─────────────────────────────────────────────────────────────────


@dataclass
class TrialData:
    """Everything the export reads, raw and in memory only — never written."""

    students: list[str]
    nodes: list[dict]  # graph_nodes rows: id, user_id, course_id, concept_name
    spans: dict[str, tuple[str, datetime]]  # node id -> (anchor event id, anchor time)
    poses: dict[tuple[str, int], dict]  # (node id, window days) -> posttest_poses row
    pretests: dict[str, bool]  # anchor event id -> the probe pretest outcome
    retired: set[tuple[str, str]] = field(default_factory=set)  # (course_id, question_hash)
    reported: set[tuple[str, str]] = field(default_factory=set)  # uncleared reports


def _trial_students(label: str) -> list[str]:
    rows = page_all(table("user_settings"), "user_id", filters={"loop_arm": f"eq.{label}"}, order="user_id")
    return sorted({str(r["user_id"]) for r in rows if r.get("user_id")})


def _nodes(user_id: str) -> list[dict]:
    return [
        r
        for r in page_all(
            table("graph_nodes"),
            "id,user_id,course_id,concept_name",
            filters={"user_id": f"eq.{user_id}", "course_id": "not.is.null"},
            order="id",
        )
        if r.get("id") and r.get("course_id")
    ]


def _anchors(user_id: str) -> dict[str, tuple[str, datetime]]:
    """Node id -> (anchor event id, anchor time) for every node of the student
    with graded evidence: the node's FIRST event_type='evidence' row in the
    journal's total order, owner-scoped through the graph_nodes!inner embed —
    evidence_spans' rule (A112), over all the student's courses at once.
    Propagation is never journaled, so it never anchors. Spec §13 A123: nor
    does a void row (the student's void record names it), so a concept whose
    every row is void has no anchor. An unreadable journal time raises, as
    evidence_spans' does: the database wrote it."""
    voided = void_store.voided_event_ids(user_id=user_id)
    out: dict[str, tuple[str, datetime]] = {}
    for row in page_all(
        table("node_mastery_events"),
        "id,node_id,created_at,evidence_seq,graph_nodes!inner(user_id)",
        filters={"graph_nodes.user_id": f"eq.{user_id}", "event_type": "eq.evidence"},
        order=_JOURNAL_ORDER,
    ):
        node = row.get("node_id")
        if not node or not row.get("id") or str(node) in out or row["id"] in voided:
            continue
        at = _ts(row.get("created_at"))
        if at is None:
            raise ValueError("unreadable evidence journal time")
        out[str(node)] = (str(row["id"]), at)
    return out


def _poses(user_id: str) -> list[dict]:
    return list(
        page_all(
            table("posttest_poses"),
            _POSE_COLS,
            filters={"user_id": f"eq.{user_id}"},
            order="node_id,window_days",
        )
    )


def _pretests(anchor_ids: Iterable[str]) -> dict[str, bool]:
    """Anchor event id -> the concept's probe pretest (A112): the anchor rows by
    id, then the probe histories of their sessions — admin_analytics'
    `_pretests` reads, over every anchor rather than only the answered ones."""
    anchors: list[dict] = []
    for batch in _batches(sorted(set(anchor_ids))):
        anchors += (
            table("node_mastery_events").select(
                _ANCHOR_COLS, filters={"id": _in(batch), "event_type": "eq.evidence"}
            )
            or []
        )
    sessions = sorted({str(r["session_id"]) for r in anchors if r.get("session_id")})
    probed: dict[str, set[str]] = {}
    for batch in _batches(sessions):
        for row in table("sessions").select("id,history:loop_state->probe->history", filters={"id": _in(batch)}) or []:
            history = row.get("history") if isinstance(row.get("history"), list) else []
            probed[str(row.get("id"))] = {
                h["question_hash"] for h in history if isinstance(h, dict) and isinstance(h.get("question_hash"), str)
            }
    out: dict[str, bool] = {}
    for row in anchors:
        outcome = pretest_outcome(row, probed.get(str(row.get("session_id")), set()))
        if outcome is not None and row.get("id"):
            out[str(row["id"])] = outcome
    return out


def _item_decisions(items: set[tuple[str, str]], as_of: datetime) -> tuple[set, set]:
    """(retired, reported) among `items`, as of `as_of` (A113): retired = a
    check_item_reviews row with status 'retired'; reported = a student report
    with no staff approval at or after the item's last report (the admin
    queue's rule). Matched on (course_id, question_hash)."""
    hashes = sorted({qh for _, qh in items})
    reviews: dict[tuple[str, str], tuple[str, datetime | None]] = {}
    last_report: dict[tuple[str, str], datetime] = {}
    for batch in _batches(hashes):
        for row in page_all(
            table("check_item_reviews"),
            "course_id,question_hash,status,reviewed_at",
            filters={"question_hash": _in(batch)},
            order="course_id,question_hash",
        ):
            at = _ts(row.get("reviewed_at"))
            if at is None or at <= as_of:
                reviews[(str(row.get("course_id")), str(row.get("question_hash")))] = (str(row.get("status")), at)
        for row in page_all(
            table("check_item_reports"),
            "course_id,question_hash,created_at",
            filters={"question_hash": _in(batch)},
            order="question_hash,user_id",
        ):
            key = (str(row.get("course_id")), str(row.get("question_hash")))
            at = _ts(row.get("created_at"))
            if at is None or at > as_of:
                continue
            if key not in last_report or at > last_report[key]:
                last_report[key] = at
    retired = {k for k in items if reviews.get(k, ("", None))[0] == "retired"}
    reported = set()
    for key, at in last_report.items():
        if key not in items or key in retired:
            continue
        status, reviewed = reviews.get(key, ("", None))
        if not (status == "approved" and reviewed is not None and reviewed >= at):
            reported.add(key)
    return retired, reported


def read_trial(label: str, as_of: datetime) -> TrialData:
    students = _trial_students(label)
    nodes: list[dict] = []
    spans: dict[str, tuple[str, datetime]] = {}
    poses: dict[tuple[str, int], dict] = {}
    for user_id in students:
        mine = _nodes(user_id)
        nodes += mine
        anchors = _anchors(user_id)
        spans.update({str(n["id"]): anchors[str(n["id"])] for n in mine if str(n["id"]) in anchors})
        for pose in _poses(user_id):
            if pose.get("node_id") and isinstance(pose.get("window_days"), int):
                poses[(str(pose["node_id"]), pose["window_days"])] = pose
    pretests = _pretests(anchor for anchor, _ in spans.values())
    items = {
        (str(p["course_id"]), str(p["question_hash"]))
        for p in poses.values()
        if p.get("course_id") and p.get("question_hash")
    }
    retired, reported = _item_decisions(items, as_of)
    return TrialData(students, nodes, spans, poses, pretests, retired, reported)


# ── the table (pure) ───────────────────────────────────────────────────────────


def pose_status(pose: dict | None, as_of: datetime) -> str:
    """A112/A89 outcome state of one window's pose, as of `as_of`."""
    if pose is None:
        return "not_posed"
    answered = _ts(pose.get("answered_at"))
    if answered is not None and answered <= as_of:
        if posttest_outcome(pose) is not None:
            return "rung0"
        return "assisted" if isinstance(pose.get("correct"), bool) else "unrecorded"
    posed = _ts(pose.get("posed_at"))
    if posed is not None and posed >= as_of - timedelta(hours=POSTTEST_POSE_TTL_HOURS):
        return "open"
    return "expired"


@dataclass
class ExportSummary:
    students_labelled: int = 0
    students_exported: int = 0
    concepts: int = 0
    rows: int = 0
    flow: Counter = field(default_factory=Counter)  # (window, arm, status) -> rows
    excluded: Counter = field(default_factory=Counter)  # (window, arm, exclusion) -> rows
    pretests: Counter = field(default_factory=Counter)  # (window, arm) -> rows with a pretest
    notes: Counter = field(default_factory=Counter)  # data-quality counts

    def render(self) -> str:
        lines = [
            f"students with the arm label: {self.students_labelled}; exported: {self.students_exported}",
            f"student x concept units: {self.concepts}; rows (unit x opened window): {self.rows}",
            "",
            "window arm        due  " + "  ".join(f"{s:>10}" for s in STATUSES) + "  retired  reported  pretest",
        ]
        windows = sorted({w for w, _, _ in self.flow})
        for w in windows:
            for arm in (TREATMENT, CONTROL):
                due = sum(n for (ww, a, _), n in self.flow.items() if ww == w and a == arm)
                lines.append(
                    f"{w:>6} {arm:<9} {due:>5}  "
                    + "  ".join(f"{self.flow[(w, arm, s)]:>10}" for s in STATUSES)
                    + f"  {self.excluded[(w, arm, 'retired_item')]:>7}  {self.excluded[(w, arm, 'reported_item')]:>8}"
                    + f"  {self.pretests[(w, arm)]:>7}"
                )
        if self.notes:
            lines += ["", "data notes: " + ", ".join(f"{k} {v}" for k, v in sorted(self.notes.items()))]
        return "\n".join(lines)


def build_rows(
    data: TrialData,
    *,
    label: str,
    treatment_variant: str,
    as_of: datetime,
    pseudonymize: Callable[..., str],
    windows: Iterable[int] = POSTTEST_WINDOWS_DAYS,
) -> tuple[list[TrialRow], ExportSummary]:
    """The long table from what `read_trial` read. One node per (student,
    course, concept key): when normalization makes two of a student's nodes
    one concept, the earlier-anchored one stands and the other is counted."""
    windows = tuple(windows)
    summary = ExportSummary(students_labelled=len(data.students))
    chosen: dict[tuple[str, str, str], dict] = {}
    for node in data.nodes:
        span = data.spans.get(str(node["id"]))
        if span is None:
            summary.notes["concepts_without_graded_evidence"] += 1
            continue
        key = (str(node["user_id"]), str(node["course_id"]), concept_key(node.get("concept_name") or ""))
        if not key[2]:
            summary.notes["concepts_without_a_name"] += 1
            continue
        prev = chosen.get(key)
        if prev is not None:
            summary.notes["duplicate_concept_nodes_dropped"] += 1
            if data.spans[str(prev["id"])][1] <= span[1]:
                continue
        chosen[key] = node
    used_nodes = {str(n["id"]) for n in chosen.values()}
    summary.notes["poses_of_unexported_concepts"] = sum(1 for node_id, _ in data.poses if node_id not in used_nodes)
    if not summary.notes["poses_of_unexported_concepts"]:
        del summary.notes["poses_of_unexported_concepts"]
    rows: list[TrialRow] = []
    students: set[str] = set()
    units = 0
    for (user_id, course_id, ckey), node in chosen.items():
        node_id = str(node["id"])
        anchor_id, anchor_at = data.spans[node_id]
        arm = TREATMENT if variant_for(user_id, node_id, label) == treatment_variant else CONTROL
        pretest = data.pretests.get(anchor_id)
        due = [w for w in windows if anchor_at + timedelta(days=w) <= as_of]
        if due:
            units += 1
            students.add(user_id)
        for w in due:
            pose = data.poses.get((node_id, w))
            if pose is not None and (_ts(pose.get("posed_at")) or as_of) > as_of:
                pose = None  # posed after the data lock: not posed as of then
            status = pose_status(pose, as_of)
            item = None
            if pose is not None and pose.get("question_hash"):
                item = (str(pose.get("course_id") or course_id), str(pose["question_hash"]))
            exclusion = (
                "retired_item" if item in data.retired else "reported_item" if item in data.reported else ""
            )
            delay = pose.get("days_since_evidence") if pose is not None else None
            row = TrialRow(
                student=pseudonymize("student", user_id),
                course=pseudonymize("course", course_id),
                concept=pseudonymize("concept", course_id, ckey),
                arm=arm,
                window=w,
                pretest=pretest,
                posttest=posttest_outcome(pose) if status == "rung0" else None,
                status=status,
                exclusion=exclusion,
                item=pseudonymize("item", *item) if item else "",
                days_since_evidence=round(float(delay), 1)
                if isinstance(delay, (int, float)) and not isinstance(delay, bool)
                else None,
            )
            rows.append(row)
            summary.flow[(w, arm, status)] += 1
            if exclusion:
                summary.excluded[(w, arm, exclusion)] += 1
            if pretest is not None:
                summary.pretests[(w, arm)] += 1
    rows.sort(key=lambda r: (r.student, r.concept, r.window))
    summary.students_exported = len(students)
    summary.concepts = units
    summary.rows = len(rows)
    return rows, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the within-student trial's de-identified long table.")
    parser.add_argument("--arm-label", required=True, help="the trial's user_settings.loop_arm label")
    parser.add_argument(
        "--treatment-variant",
        required=True,
        choices=("A", "B"),
        help="the learning.arms variant that is the treatment (loop instruction) arm",
    )
    parser.add_argument("--as-of", help="data lock time, ISO 8601 (default: now, UTC)")
    parser.add_argument("--out", help="write the CSV here (default: dry run, nothing written)")
    args = parser.parse_args(argv)
    if not _LABEL.match(args.arm_label):
        parser.error("--arm-label: 1-64 characters from A-Z a-z 0-9 . _ : -")
    as_of = _ts(args.as_of) if args.as_of else datetime.now(timezone.utc)
    if as_of is None:
        parser.error("--as-of: not an ISO 8601 time")
    out = Path(args.out) if args.out else None
    if out is not None and out.exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2
    print(f"Project: {_project_ref()}")
    print(f"arm label {args.arm_label!r}, treatment variant {args.treatment_variant}, as of {as_of.isoformat()}")
    data = read_trial(args.arm_label, as_of)
    rows, summary = build_rows(
        data,
        label=args.arm_label,
        treatment_variant=args.treatment_variant,
        as_of=as_of,
        pseudonymize=Pseudonymizer(),
    )
    print(summary.render())
    if out is None:
        print("\ndry run: nothing written (pass --out PATH to write the table)")
        return 0
    write_csv(rows, out)
    print(f"\nwrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
