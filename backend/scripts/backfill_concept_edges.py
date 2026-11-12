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
land on each ring; `--report` writes the proposal after every course.
`--from-report` applies a reviewed report: only the courses it contains,
their reviewed `edges` (re-checked against the current graph), and nothing
new is asked of the model. Run from backend/:

    python scripts/backfill_concept_edges.py --report /tmp/edges.json
    python scripts/backfill_concept_edges.py --from-report /tmp/edges.json --apply --manifest /tmp/edges.manifest.json
    python scripts/backfill_concept_edges.py --rollback /tmp/edges.manifest.json

The manifest lists exactly the edge rows this run CREATED, taken as the diff
of the user's edges before and after each write (so a write that fails half
way is still recorded), keyed on the UNIQUE (user_id, source_node_id,
target_node_id, relationship_type). `--rollback` refuses a manifest from
another project and deletes those rows only. It deletes `graph_edges` rows
directly: `graph_service` has no edge-delete path, and these rows are this
script's own.

For staging/prod run under `dotenv -f .env.<env> run -- ...`; `--model-env
.env` takes ONLY the model API keys from another env file.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts._graph_backfill_common import (  # noqa: E402
    course_label, load_env, load_prior, target_project, write_json,
)

_EDGE_COLS = "id,source_node_id,target_node_id,relationship_type"


def _edge_key(user_id: str, e: dict) -> tuple[str, str, str, str]:
    return (user_id, e["source_node_id"], e["target_node_id"], e["relationship_type"])


def _user_edges(page_all, table, user_id: str) -> list[dict]:
    return list(page_all(table("graph_edges"), _EDGE_COLS, filters={"user_id": f"eq.{user_id}"}, order="id"))


def _rollback(manifest_path: str) -> int:
    from db.connection import table

    manifest = json.loads(Path(manifest_path).read_text())
    if manifest.get("target") != target_project():
        print(f"ABORT: manifest is for project {manifest.get('target')!r}, "
              f"this run targets {target_project()!r}")
        return 2
    removed = missing = 0
    for r in manifest["created"]:
        filters = {
            "user_id": f"eq.{r['user_id']}",
            "source_node_id": f"eq.{r['source_node_id']}",
            "target_node_id": f"eq.{r['target_node_id']}",
            "relationship_type": f"eq.{r['relationship_type']}",
        }
        if not table("graph_edges").select("id", filters=filters, limit=1):
            missing += 1
            continue
        table("graph_edges").delete(filters=filters)
        removed += 1
    print(f"rolled back {removed} edge(s); {missing} already gone")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the edges (default: dry-run)")
    ap.add_argument("--manifest", help="with --apply: where to record the created edges (required)")
    ap.add_argument("--rollback", metavar="MANIFEST", help="delete the edges a previous --apply created")
    ap.add_argument("--report", help="write the per-course proposal as JSON")
    ap.add_argument("--from-report", help="apply a reviewed dry-run instead of asking the model again")
    ap.add_argument("--user", help="only this user id")
    ap.add_argument("--course", help="only this course id")
    ap.add_argument("--force", action="store_true", help="also re-do courses that already have edges")
    ap.add_argument("--min-concepts", type=int, default=3)
    ap.add_argument("--model-env", help="env file to take ONLY the model API keys from")
    args = ap.parse_args()

    load_env(args.model_env)
    if args.rollback:
        return _rollback(args.rollback)
    if args.apply and not args.manifest:
        ap.error("--apply needs --manifest (it is what makes the run undoable)")

    from db.connection import page_all, table
    from services.concept_edges import build_message, ring_depths, sanitize_edges

    target = target_project()
    print(f"target project: {target}  mode: {'APPLY' if args.apply else 'dry-run'}")
    prior = load_prior(args.from_report)

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

    edges_by_user: dict[str, list[dict]] = {}
    report, created = [], []
    agent_bits = None

    for (user_id, course_id), course_nodes in sorted(groups.items()):
        names = [n["concept_name"] for n in course_nodes]
        by_id = {n["id"]: n["concept_name"] for n in course_nodes}
        if prior is not None and (user_id, course_id) not in prior:
            continue  # --from-report acts on reviewed courses only
        label = course_label(table, course_id)
        tag = f"{user_id[:18]:<18} {label[:40]:<40} n={len(names):<4}"
        if len(names) < args.min_concepts:
            print(f"{tag} skip: fewer than {args.min_concepts} concepts")
            continue
        try:
            if user_id not in edges_by_user:
                edges_by_user[user_id] = _user_edges(page_all, table, user_id)
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
            if prior is not None:
                proposed = prior[(user_id, course_id)]["edges"]
            else:
                if agent_bits is None:
                    from agents import WORKER_LIMITS
                    from agents._run import run_agent_sync
                    from agents.concept_edges import concept_edges_agent
                    from agents.deps import SaplingDeps
                    agent_bits = (WORKER_LIMITS, run_agent_sync, concept_edges_agent, SaplingDeps)
                # Method or property, on either side of pydantic-ai's move.
                from agents.usage import _run_usage
                limits, run_sync, agent, deps_cls = agent_bits
                t0 = time.monotonic()
                result = run_sync(agent.run(
                    build_message(label, names),
                    deps=deps_cls(user_id=user_id, course_id=course_id, supabase=None,
                                  request_id="backfill-concept-edges"),
                    usage_limits=limits,
                ))
                u = _run_usage(result)
                usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                         "seconds": round(time.monotonic() - t0, 1)}
                proposed = [e.model_dump() for e in result.output.edges]

            edges = sanitize_edges(names, proposed, existing)
        except Exception as exc:  # one course failing must not lose the rest
            print(f"{tag} ERROR: {type(exc).__name__}: {exc}")
            report.append({"user_id": user_id, "course_id": course_id, "course": label,
                           "error": f"{type(exc).__name__}: {exc}", "edges": []})
            write_json(args.report, {"target": target, "courses": report})
            continue

        depth = ring_depths(names, existing + edges)
        rings = sorted(Counter(depth.values()).items())
        kinds = Counter(e["relationship_type"] for e in edges)
        print(f"{tag} proposed={len(proposed):<4} kept={len(edges):<4} "
              f"{dict(kinds)}  rings(depth:count)={rings}")
        report.append({
            "user_id": user_id, "course_id": course_id, "course": label,
            "concepts": len(names), "existing": existing, "proposed": len(proposed),
            "edges": edges, "rings": rings, "usage": usage,
            "depth": {n: depth[n] for n in sorted(names, key=lambda x: (depth[x], x))},
        })
        write_json(args.report, {"target": target, "courses": report})

        if args.apply and edges:
            from services.graph_service import apply_graph_update

            before = {_edge_key(user_id, e) for e in edges_by_user[user_id]}
            error = None
            try:
                apply_graph_update(user_id, {"new_edges": edges}, course_id=course_id)
            except Exception as exc:
                error = exc
            finally:
                # Record what actually landed, not what was asked for: exact even
                # when the write stopped half way or resolved a case-variant name
                # to a different node than the sanitizer's canonical one.
                edges_by_user[user_id] = _user_edges(page_all, table, user_id)
                new = [k for k in (_edge_key(user_id, e) for e in edges_by_user[user_id]) if k not in before]
                created.extend({"user_id": k[0], "source_node_id": k[1], "target_node_id": k[2],
                                "relationship_type": k[3]} for k in new)
                write_json(args.manifest, {"target": target, "created": created})
            if error is not None:
                print(f"   ! write failed after {len(new)} edge(s): {type(error).__name__}: {error}")
                report[-1]["error"] = f"{type(error).__name__}: {error}"
                write_json(args.report, {"target": target, "courses": report})

    if args.report:
        print(f"report: {args.report}")
    total = sum(len(c["edges"]) for c in report)
    n_err = sum(1 for c in report if c.get("error"))
    print(f"\n{len(report)} course(s), {total} edge(s) {'written' if args.apply else 'proposed'}, {n_err} error(s)"
          + (f"; manifest: {args.manifest} ({len(created)} created)" if args.apply else ""))
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
