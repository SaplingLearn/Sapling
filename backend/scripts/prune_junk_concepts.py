#!/usr/bin/env python3
"""
One-time cleanup: remove graph "concepts" that are course logistics.

Syllabus uploads put course logistics into students' graphs ("October 4
Homework Deadline", "Makeup Exam Policy", "Office Hours"), where they sit
unlinked on the course's inner ring. For each (student, course) the
`concept_prune` agent names the entries that are not concepts; each logistics
entry is deleted through `graph_service.delete_node` (the owner-scoped
sanctioned path; edges and mastery events cascade, as do `quiz_context` rows).

Never deleted, only reported:
* `off_topic` entries. In the dry-runs they were real coursework under a
  course mapped to the wrong catalog entry, or a whole misfiled upload;
  either is a human's call.
* a logistics entry with study history a delete would damage: quiz attempts
  on it (their `concept_node_id` would be nulled) or notes linked to it.

Dry-run by default; `--report` writes the proposal after every course.
`--from-report` applies a reviewed report EXACTLY: its `remove` lists (edit
them to veto a deletion), and only the courses it contains; nothing new is
asked of the model. `--apply` needs `--manifest`, which keeps every deleted
node row with its mastery events, edges and quiz_context rows. The real
restore path is a `make backup-db` taken beforehand. Run from backend/:

    python scripts/prune_junk_concepts.py --report /tmp/prune.json
    python scripts/prune_junk_concepts.py --from-report /tmp/prune.json --apply --manifest /tmp/prune.manifest.json

For staging/prod run under `dotenv -f .env.<env> run -- ...`; `--model-env
.env` takes ONLY the model API keys from another env file.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts._graph_backfill_common import (  # noqa: E402
    course_label, load_env, load_prior, target_project, write_json,
)


def _fold(name: str) -> str:
    return " ".join((name or "").split()).casefold()


def plan_removals(concept_names: list[str], junk: list[dict]) -> tuple[list[dict], list[dict]]:
    """Resolve the model's junk list against the course's exact names.
    Returns (remove, held) as lists of {name, kind, reason}: logistics are
    removed, off-topic entries are held for a human."""
    fold = {_fold(n): n for n in concept_names}
    seen, remove, held = set(), [], []
    for j in junk:
        name = fold.get(_fold(j.get("name")))
        if not name or name in seen or j.get("kind") not in ("logistics", "off_topic"):
            continue
        seen.add(name)
        item = {"name": name, "kind": j["kind"], "reason": j.get("reason", "")}
        (remove if j["kind"] == "logistics" else held).append(item)
    return remove, held


def reviewed_removals(concept_names: list[str], reviewed: dict) -> tuple[list[dict], list[dict]]:
    """A reviewed report's own `remove`/`held` lists, re-resolved against the
    course's CURRENT names (a concept gone since the review is dropped)."""
    fold = {_fold(n): n for n in concept_names}
    remove = [{**r, "name": fold[_fold(r["name"])]} for r in reviewed.get("remove", [])
              if r.get("kind") == "logistics" and _fold(r["name"]) in fold]
    return remove, list(reviewed.get("held", []))


def _study_history(table, node_id: str) -> list[str]:
    reasons = []
    if table("quiz_attempts").select("id", filters={"concept_node_id": f"eq.{node_id}"}, limit=1):
        reasons.append("quiz attempts")
    if table("note_concepts").select("concept_node_id", filters={"concept_node_id": f"eq.{node_id}"}, limit=1):
        reasons.append("linked notes")
    return reasons


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--manifest")
    ap.add_argument("--report")
    ap.add_argument("--from-report")
    ap.add_argument("--user")
    ap.add_argument("--course")
    ap.add_argument("--min-concepts", type=int, default=3)
    ap.add_argument("--model-env")
    args = ap.parse_args()
    if args.apply and not args.manifest:
        ap.error("--apply needs --manifest")
    load_env(args.model_env)

    from db.connection import page_all, table

    target = target_project()
    print(f"target project: {target}  mode: {'APPLY' if args.apply else 'dry-run'}")
    prior = load_prior(args.from_report)

    filters = {}
    if args.user:
        filters["user_id"] = f"eq.{args.user}"
    if args.course:
        filters["course_id"] = f"eq.{args.course}"
    nodes = list(page_all(table("graph_nodes"), "*", filters=filters or None, order="id"))
    deleted_users = {r["id"] for r in table("users").select("id", filters={"deleted_at": "not.is.null"}) or []}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for n in nodes:
        if n.get("course_id") and n.get("concept_name") and n["user_id"] not in deleted_users:
            groups[(n["user_id"], n["course_id"])].append(n)

    report, manifest = [], []
    agent_bits = None
    for (user_id, course_id), course_nodes in sorted(groups.items()):
        names = [n["concept_name"] for n in course_nodes]
        if len(names) < args.min_concepts:
            continue
        if prior is not None and (user_id, course_id) not in prior:
            continue  # --from-report acts on reviewed courses only
        label = course_label(table, course_id)
        tag = f"{user_id[:18]:<18} {label[:40]:<40} n={len(names):<4}"
        try:
            if prior is not None:
                junk = prior[(user_id, course_id)].get("junk", [])
                remove, held = reviewed_removals(names, prior[(user_id, course_id)])
            else:
                if agent_bits is None:
                    from agents import WORKER_LIMITS
                    from agents._run import run_agent_sync
                    from agents.concept_prune import concept_prune_agent
                    from agents.deps import SaplingDeps
                    from services.concept_edges import build_message
                    agent_bits = (WORKER_LIMITS, run_agent_sync, concept_prune_agent, SaplingDeps, build_message)
                limits, run_sync, agent, deps_cls, build_message = agent_bits
                result = run_sync(agent.run(
                    build_message(label, names),
                    deps=deps_cls(user_id=user_id, course_id=course_id, supabase=None,
                                  request_id="prune-junk-concepts"),
                    usage_limits=limits,
                ))
                junk = [j.model_dump() for j in result.output.junk]
                remove, held = plan_removals(names, junk)

            by_name = {n["concept_name"]: n for n in course_nodes}
            safe = []
            for r in remove:
                history = _study_history(table, by_name[r["name"]]["id"])
                if history:
                    held.append({**r, "kind": "has_history", "reason": ", ".join(history)})
                else:
                    safe.append(r)
            remove = safe
        except Exception as exc:  # one course failing must not lose the rest
            print(f"{tag} ERROR: {type(exc).__name__}: {exc}")
            report.append({"user_id": user_id, "course_id": course_id, "course": label,
                           "error": f"{type(exc).__name__}: {exc}", "junk": [], "remove": [], "held": []})
            write_json(args.report, {"target": target, "courses": report})
            continue

        print(f"{tag} remove={len(remove):<3} held={len(held):<3}"
              + (f"  remove: {', '.join(r['name'] for r in remove)}" if remove else "")
              + (f"  HELD: {', '.join(h['name'] + ' (' + h['kind'] + ')' for h in held)}" if held else ""))
        report.append({"user_id": user_id, "course_id": course_id, "course": label,
                       "concepts": len(names), "junk": junk, "remove": remove, "held": held})
        write_json(args.report, {"target": target, "courses": report})

        if args.apply and remove:
            from services.graph_service import delete_node

            for r in remove:
                node = by_name[r["name"]]
                nid = node["id"]
                snapshot = {
                    "node": node, "removal": r,
                    "mastery_events": table("node_mastery_events").select("*", filters={"node_id": f"eq.{nid}"}) or [],
                    "edges": (table("graph_edges").select("*", filters={"source_node_id": f"eq.{nid}"}) or [])
                    + (table("graph_edges").select("*", filters={"target_node_id": f"eq.{nid}"}) or []),
                    "quiz_context": table("quiz_context").select("*", filters={"concept_node_id": f"eq.{nid}"}) or [],
                }
                out = delete_node(user_id, nid)
                if out.get("deleted") is False:
                    print(f"   ! not deleted: {r['name']}: {out}")
                    continue
                manifest.append(snapshot)
                write_json(args.manifest, {"target": target, "deleted": manifest})

    n_remove = sum(len(c["remove"]) for c in report)
    n_held = sum(len(c["held"]) for c in report)
    n_err = sum(1 for c in report if c.get("error"))
    if args.report:
        print(f"report: {args.report}")
    print(f"\n{len(report)} course(s): {n_remove} {'deleted' if args.apply else 'to delete'}, "
          f"{n_held} held for a human, {n_err} error(s)"
          + (f"; manifest: {args.manifest} ({len(manifest)} rows)" if args.apply else ""))
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
