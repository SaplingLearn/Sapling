"""One-shot cleanup for the Prompt-09 classifier integration test.

Deletes exactly the artifacts the test created against production Supabase:
- the documents row inserted by the upload
- graph_nodes added for the test user+course in the test window
- graph_edges touching any of those nodes (defensive; upload doesn't insert
  edges today but apply_graph_update is the seam)
- assignments added for the test user+course in the test window

Run from backend/:
    venv/bin/python3 scripts/cleanup_classifier_test.py
"""
from __future__ import annotations

import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv(".env")

from db.connection import table

USER_ID = "user_110308730010648729974"
COURSE_ID = "cas-aa-103"
# Doc rows from each test in this session: Prompt 09 + 11 (legacy x2) + 11 (orchestrator).
DOC_IDS = [
    "4e1ec901-0c0b-45a6-a24a-0a4c3e4a84ce",  # Prompt 11 attempt #1, legacy fallback
    "99ab0e41-eea3-4ad2-b05d-44c0420ec5de",  # Prompt 11 attempt #2, legacy fallback
    "08747e6e-142b-4ae0-ad26-55867e4b7258",  # Prompt 11 attempt #3, orchestrator OK
]
SINCE = "2026-05-03T16:00:00"


def preview() -> tuple[list, list, list]:
    ids_filter = "(" + ",".join(DOC_IDS) + ")"
    doc = table("documents").select(
        "id,file_name", filters={"id": f"in.{ids_filter}"}
    )
    nodes = table("graph_nodes").select(
        "id,concept_name",
        filters={
            "user_id": f"eq.{USER_ID}",
            "course_id": f"eq.{COURSE_ID}",
            "created_at": f"gte.{SINCE}",
        },
    )
    asgs = table("assignments").select(
        "id,title",
        filters={
            "user_id": f"eq.{USER_ID}",
            "course_id": f"eq.{COURSE_ID}",
            "created_at": f"gte.{SINCE}",
        },
    )
    return doc, nodes, asgs


def main() -> None:
    doc, nodes, asgs = preview()
    print(f"documents to delete:   {len(doc)}")
    print(f"graph_nodes to delete: {len(nodes)}")
    print(f"assignments to delete: {len(asgs)}")
    print()
    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # graph_edges first — must drop FK references before nodes go.
    deleted_edges = 0
    for n in nodes:
        nid = n["id"]
        for col in ("source_node_id", "target_node_id"):
            res = table("graph_edges").delete(
                filters={"user_id": f"eq.{USER_ID}", col: f"eq.{nid}"}
            )
            deleted_edges += len(res or [])

    deleted_nodes = 0
    for n in nodes:
        res = table("graph_nodes").delete(
            filters={"id": f"eq.{n['id']}", "user_id": f"eq.{USER_ID}"}
        )
        deleted_nodes += len(res or [])

    deleted_asgs = 0
    for a in asgs:
        res = table("assignments").delete(
            filters={"id": f"eq.{a['id']}", "user_id": f"eq.{USER_ID}"}
        )
        deleted_asgs += len(res or [])

    deleted_docs = 0
    for d in doc:
        res = table("documents").delete(filters={"id": f"eq.{d['id']}"})
        deleted_docs += len(res or [])

    print()
    print(f"deleted: documents={deleted_docs} graph_edges={deleted_edges} "
          f"graph_nodes={deleted_nodes} assignments={deleted_asgs}")


if __name__ == "__main__":
    main()
