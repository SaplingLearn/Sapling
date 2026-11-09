#!/usr/bin/env python3
"""
One-time cleanup: remove graph "concepts" that are not concepts of their course.

Syllabus uploads put course logistics into students' graphs ("October 4
Homework Deadline", "Makeup Exam Policy", "Office Hours"); a document filed
under the wrong course brought in another subject's concepts. For each
(student, course) the `concept_prune` agent names the entries to remove, and
each is deleted through `graph_service.delete_node` (the owner-scoped
sanctioned path; its edges go with it, mastery events cascade).

Only `logistics` entries are deleted. `off_topic` ones are reported and
left alone: in the dry-runs they were real coursework under a course mapped to
the wrong catalog entry, or a whole misfiled upload, and either is a human's
call, not a delete.

Dry-run by default; `--report` writes the proposal, `--from-report` applies a
reviewed one without asking the model again. `--apply` needs `--manifest`,
which records every deleted node row with its mastery events and edges, for a
hand restore. The real restore path is a `make backup-db` taken beforehand.
Run from backend/:

    python scripts/prune_junk_concepts.py --report /tmp/prune.json
    python scripts/prune_junk_concepts.py --from-report /tmp/prune.json --apply --manifest /tmp/prune.manifest.json

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...`;
`--model-env .env` takes ONLY the model API keys from another env file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
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


def plan_removals(concept_names: list[str], junk: list[dict]) -> tuple[list[dict], list[dict]]:
    """Resolve the model's junk list against the course's exact names.
    Returns (remove, held) as lists of {name, kind, reason}: logistics are
    removed, off-topic entries are held for a human."""
    fold = {" ".join(n.split()).casefold(): n for n in concept_names}
    seen, remove, held = set(), [], []
    for j in junk:
        name = fold.get(" ".join((j.get("name") or "").split()).casefold())
        if not name or name in seen or j.get("kind") not in ("logistics", "off_topic"):
            continue
        seen.add(name)
        item = {"name": name, "kind": j["kind"], "reason": j.get("reason", "")}
        (remove if j["kind"] == "logistics" else held).append(item)
    return remove, held


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
    _load_model_keys(args.model_env)

    from db.connection import page_all, table

    target = (os.environ.get("SUPABASE_URL") or "").split("//")[-1].split(".")[0]
    print(f"target project: {target}  mode: {'APPLY' if args.apply else 'dry-run'}")

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

    prior = {}
    if args.from_report:
        for c in json.loads(Path(args.from_report).read_text())["courses"]:
            prior[(c["user_id"], c["course_id"])] = c

    from scripts.backfill_concept_edges import _course_label

    report, manifest = [], []
    agent_bits = None
    for (user_id, course_id), course_nodes in sorted(groups.items()):
        names = [n["concept_name"] for n in course_nodes]
        label = _course_label(table, course_id)
        tag = f"{user_id[:18]:<18} {label[:40]:<40} n={len(names):<4}"
        if len(names) < args.min_concepts:
            continue
        if (user_id, course_id) in prior:
            junk = prior[(user_id, course_id)]["junk"]
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
        print(f"{tag} remove={len(remove):<3} held={len(held):<3}"
              + (f"  remove: {', '.join(r['name'] for r in remove)}" if remove else "")
              + (f"  HELD (off-topic): {', '.join(h['name'] for h in held)}" if held else ""))
        report.append({"user_id": user_id, "course_id": course_id, "course": label,
                       "concepts": len(names), "junk": junk, "remove": remove, "held": held})

        if args.apply and remove:
            from services.graph_service import delete_node

            by_name = {n["concept_name"]: n for n in course_nodes}
            for r in remove:
                node = by_name[r["name"]]
                events = table("node_mastery_events").select("*", filters={"node_id": f"eq.{node['id']}"}) or []
                edges = (table("graph_edges").select("*", filters={"source_node_id": f"eq.{node['id']}"}) or []) + \
                        (table("graph_edges").select("*", filters={"target_node_id": f"eq.{node['id']}"}) or [])
                out = delete_node(user_id, node["id"])
                if out.get("deleted") is False:
                    print(f"   ! not deleted: {r['name']}: {out}")
                    continue
                manifest.append({"node": node, "removal": r, "mastery_events": events, "edges": edges})
                Path(args.manifest).write_text(json.dumps({"target": target, "deleted": manifest}, indent=1, default=str))

    if args.report:
        Path(args.report).write_text(json.dumps({"target": target, "courses": report}, indent=1))
        print(f"report: {args.report}")
    n_remove = sum(len(c["remove"]) for c in report)
    n_held = sum(len(c["held"]) for c in report)
    print(f"\n{len(report)} course(s): {n_remove} {'deleted' if args.apply else 'to delete'}, {n_held} held for a human")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
