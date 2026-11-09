#!/usr/bin/env python3
"""
One-time backfill: give every student's courses concept-to-concept edges.

Until now nothing wrote edges between concepts (uploads write concepts only),
so under the course-centred radial layout (#803) every course is one flat
ring. For each (student, course) this asks the `concept_edges` agent how the
course's concepts depend on each other, cleans the answer with
`services/concept_edges.py::sanitize_edges` (exact names, no cycles, no
shortcuts, capped fan-in) and writes it through
`graph_service.apply_graph_update` — the only sanctioned graph writer. Edges
only: no node, mastery score or event is touched.

A course is skipped when it already has at least one existing concept edge
per two concepts (re-running does not pile a second opinion on top of the
first); `--force` overrides that.

Dry-run by default: prints, per course, the edge counts and how many concepts
land on each ring, and writes the full proposal to `--report`. Run from
backend/:

    python scripts/backfill_concept_edges.py --report /tmp/edges-local.json
    python scripts/backfill_concept_edges.py --apply --manifest /tmp/edges-local.manifest.json
    python scripts/backfill_concept_edges.py --rollback /tmp/edges-local.manifest.json

The manifest lists exactly the edge rows this run CREATED (keyed on the
UNIQUE (user_id, source_node_id, target_node_id, relationship_type)), so a
rollback deletes those and nothing else.

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...`.
The model call needs a real ANTHROPIC_API_KEY; when the target env file has
none, `--model-env .env` loads ONLY the model keys from another env file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

_MODEL_KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY")


def _load_model_keys(env_file: str | None) -> None:
    if not env_file:
        return
    values = dotenv_values(env_file)
    for k in _MODEL_KEYS:
        if values.get(k) and not os.environ.get(k):
            os.environ[k] = values[k]


def _course_label(table, course_id: str) -> str:
    rows = table("courses").select(
        "course_code,course_name", filters={"id": f"eq.{course_id}"}, limit=1,
    ) or []
    if not rows:
        return "Course"
    code = (rows[0].get("course_code") or "").strip()
    name = (rows[0].get("course_name") or "").strip()
    return f"{code} — {name}" if code and name else (code or name or "Course")


def _rollback(manifest_path: str) -> int:
    from db.connection import table

    rows = json.loads(Path(manifest_path).read_text())["created"]
    for r in rows:
        table("graph_edges").delete(filters={
            "user_id": f"eq.{r['user_id']}",
            "source_node_id": f"eq.{r['source_node_id']}",
            "target_node_id": f"eq.{r['target_node_id']}",
            "relationship_type": f"eq.{r['relationship_type']}",
        })
    print(f"rolled back {len(rows)} edge(s) from {manifest_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the edges (default: dry-run)")
    ap.add_argument("--manifest", help="with --apply: where to record the created edges (required)")
    ap.add_argument("--rollback", metavar="MANIFEST", help="delete the edges a previous --apply created")
    ap.add_argument("--report", help="write the full per-course proposal as JSON")
    ap.add_argument("--from-report", help="apply a previous dry-run's proposal instead of asking the model again")
    ap.add_argument("--user", help="only this user id")
    ap.add_argument("--course", help="only this course id")
    ap.add_argument("--force", action="store_true", help="also re-do courses that already have edges")
    ap.add_argument("--min-concepts", type=int, default=3)
    ap.add_argument("--model-env", help="env file to take ONLY the model API keys from")
    args = ap.parse_args()

    if args.rollback:
        return _rollback(args.rollback)
    if args.apply and not args.manifest:
        ap.error("--apply needs --manifest (it is what makes the run undoable)")

    _load_model_keys(args.model_env)

    from db.connection import page_all, table
    from services.concept_edges import build_message, ring_depths, sanitize_edges

    target = (os.environ.get("SUPABASE_URL") or "").split("//")[-1].split(".")[0]
    print(f"target project: {target}  mode: {'APPLY' if args.apply else 'dry-run'}")

    filters = {}
    if args.user:
        filters["user_id"] = f"eq.{args.user}"
    if args.course:
        filters["course_id"] = f"eq.{args.course}"
    nodes = list(page_all(
        table("graph_nodes"), "id,user_id,course_id,concept_name", filters=filters or None, order="id",
    ))
    deleted = {
        r["id"] for r in table("users").select("id", filters={"deleted_at": "not.is.null"}) or []
    }

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for n in nodes:
        if n.get("course_id") and n.get("concept_name") and n["user_id"] not in deleted:
            groups[(n["user_id"], n["course_id"])].append(n)

    prior = {}
    if args.from_report:
        for c in json.loads(Path(args.from_report).read_text())["courses"]:
            prior[(c["user_id"], c["course_id"])] = c

    edges_by_user: dict[str, list[dict]] = {}
    labels: dict[str, str] = {}
    report, created = [], []
    run_agent_sync = concept_edges_agent = WORKER_LIMITS = SaplingDeps = None

    for (user_id, course_id), course_nodes in sorted(groups.items()):
        names = [n["concept_name"] for n in course_nodes]
        by_id = {n["id"]: n["concept_name"] for n in course_nodes}
        id_by_name = {n["concept_name"]: n["id"] for n in course_nodes}
        if course_id not in labels:
            labels[course_id] = _course_label(table, course_id)
        tag = f"{user_id[:18]:<18} {labels[course_id][:40]:<40} n={len(names):<4}"
        if len(names) < args.min_concepts:
            print(f"{tag} skip: fewer than {args.min_concepts} concepts")
            continue

        if user_id not in edges_by_user:
            edges_by_user[user_id] = table("graph_edges").select(
                "source_node_id,target_node_id,relationship_type",
                filters={"user_id": f"eq.{user_id}"},
            ) or []
        existing = [
            {"source": by_id[e["source_node_id"]], "target": by_id[e["target_node_id"]],
             "relationship_type": e["relationship_type"]}
            for e in edges_by_user[user_id]
            if e["source_node_id"] in by_id and e["target_node_id"] in by_id
        ]
        if not args.force and len(existing) * 2 >= len(names):
            print(f"{tag} skip: already has {len(existing)} edges")
            continue

        usage = None
        if (user_id, course_id) in prior:
            proposed = prior[(user_id, course_id)]["edges"]
        else:
            if run_agent_sync is None:
                from agents import WORKER_LIMITS
                from agents._run import run_agent_sync
                from agents.concept_edges import concept_edges_agent
                from agents.deps import SaplingDeps
            t0 = time.monotonic()
            result = run_agent_sync(concept_edges_agent.run(
                build_message(labels[course_id], names),
                deps=SaplingDeps(user_id=user_id, course_id=course_id, supabase=None,
                                 request_id="backfill-concept-edges"),
                usage_limits=WORKER_LIMITS,
            ))
            u = result.usage()
            usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                     "seconds": round(time.monotonic() - t0, 1)}
            proposed = [e.model_dump() for e in result.output.edges]

        edges = sanitize_edges(names, proposed, existing)
        depth = ring_depths(names, existing + edges)
        rings = sorted(Counter(depth.values()).items())
        kinds = Counter(e["relationship_type"] for e in edges)
        print(f"{tag} proposed={len(proposed):<4} kept={len(edges):<4} "
              f"{dict(kinds)}  rings(depth:count)={rings}")
        report.append({
            "user_id": user_id, "course_id": course_id, "course": labels[course_id],
            "concepts": len(names), "existing": existing, "proposed": len(proposed),
            "edges": edges, "rings": rings, "usage": usage,
            "depth": {n: depth[n] for n in sorted(names, key=lambda x: (depth[x], x))},
        })

        if args.apply and edges:
            from services.graph_service import apply_graph_update

            have = {(e["source_node_id"], e["target_node_id"], e["relationship_type"])
                    for e in edges_by_user[user_id]}
            apply_graph_update(user_id, {"new_edges": edges}, course_id=course_id)
            for e in edges:
                key = (id_by_name[e["source"]], id_by_name[e["target"]], e["relationship_type"])
                if key not in have:
                    created.append({"user_id": user_id, "source_node_id": key[0],
                                    "target_node_id": key[1], "relationship_type": key[2]})
            # Persist after every course so an interrupted run is still undoable.
            Path(args.manifest).write_text(json.dumps({"target": target, "created": created}, indent=1))

    if args.report:
        Path(args.report).write_text(json.dumps({"target": target, "courses": report}, indent=1))
        print(f"report: {args.report}")
    total = sum(len(c["edges"]) for c in report)
    print(f"\n{len(report)} course(s), {total} edge(s) {'written' if args.apply else 'proposed'}"
          + (f"; manifest: {args.manifest} ({len(created)} created)" if args.apply else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
