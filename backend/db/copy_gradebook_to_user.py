"""TESTING helper: copy one user's gradebook onto another user's enrollments.

Local dev accounts often end up with *hollow* enrollments: a script mirrored the
enrollment rows onto a new user id but left `gradebook_categories` / `assignments`
keyed on the **source** user's enrollment ids. The courses then render with no
categories and no assignments, because the gradebook keys on `enrollment_id`
(see `routes/gradebook.py::_load_assignments`) and nothing resolves.

This copies the source user's gradebook *forward* onto the target user's
enrollments, matching the two users' enrollments by `offering_id`:

    for each offering both users are enrolled in:
        copy gradebook_categories (new ids, re-pointed at the target enrollment)
        copy assignments          (new ids, category_id remapped to the new ids)
        copy the enrollment-level grade settings (letter_scale, curve_*)

It **duplicates** rather than moves, so the source account keeps its own data and
stays usable as a fixture.

🔒 Encrypted columns (`assignments.points_possible` / `points_earned` / `notes`)
are copied as **ciphertext, verbatim**. Source and target live in the same project
under the same `ENCRYPTION_KEY`, so there is nothing to re-wrap — and this script
never needs the key. `syllabus_doc_id` is deliberately NOT copied: it points at a
document owned by the source user.

Idempotent: a target enrollment that already has any category or assignment is
skipped, so re-running is a no-op. Dry-run by default; pass --apply to write.

Run (from `backend/`):

    python -m db.copy_gradebook_to_user --to <user_id>              # dry run
    python -m db.copy_gradebook_to_user --to <user_id> --apply
    python -m db.copy_gradebook_to_user --from rich-user-active --to <user_id> --apply
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

# Allow `python db/copy_gradebook_to_user.py` as well as `python -m db.…`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import SUPABASE_URL, table  # noqa: E402

CATEGORY_COLS = "id,enrollment_id,name,weight,sort_order,drop_lowest"
ASSIGNMENT_COLS = (
    "id,enrollment_id,category_id,title,due_date,assignment_type,notes,"
    "points_possible,points_earned,source,curve_class_mean,curve_class_sd,"
    "curve_avg_target,curve_sd_delta"
)
ENROLLMENT_COLS = (
    "id,user_id,offering_id,letter_scale,curve_mode,curve_avg_target,curve_sd_delta"
)
# Copied from the source enrollment so the computed grade matches. syllabus_doc_id
# is omitted on purpose — it belongs to the source user's documents.
ENROLLMENT_GRADE_SETTINGS = (
    "letter_scale", "curve_mode", "curve_avg_target", "curve_sd_delta",
)


def _enrollments_for(user_id: str) -> list[dict]:
    return table("enrollments").select(
        ENROLLMENT_COLS, filters={"user_id": f"eq.{user_id}"}, order="id.asc"
    ) or []


def _course_label(offering_id: str) -> str:
    """`CS101 Fall 2025`-ish label for log lines. Best effort, never fatal."""
    off = table("course_offerings").select(
        "course_id,term_id", filters={"id": f"eq.{offering_id}"}, limit=1
    )
    if not off:
        return offering_id
    course = table("courses").select(
        "course_code", filters={"id": f"eq.{off[0]['course_id']}"}, limit=1
    )
    code = course[0]["course_code"] if course else off[0]["course_id"]
    return f"{code} ({off[0].get('term_id')})"


def copy(from_user: str, to_user: str, apply: bool) -> None:
    print(f"project: {SUPABASE_URL or '(SUPABASE_URL unset)'}")
    print(f"copy gradebook: {from_user}  ->  {to_user}")
    print(f"mode: {'APPLY' if apply else 'dry run'}\n")

    src = _enrollments_for(from_user)
    dst = _enrollments_for(to_user)
    if not src:
        raise SystemExit(f"Source user {from_user!r} has no enrollments.")
    if not dst:
        raise SystemExit(f"Target user {to_user!r} has no enrollments — nothing to copy onto.")

    # Match the two users' enrollments by the offering they share.
    src_by_offering = {e["offering_id"]: e for e in src}
    pairs = [(src_by_offering[e["offering_id"]], e)
             for e in dst if e["offering_id"] in src_by_offering]

    print(f"{len(src)} source enrollments, {len(dst)} target enrollments, "
          f"{len(pairs)} shared offering(s).")
    only_dst = [e for e in dst if e["offering_id"] not in src_by_offering]
    if only_dst:
        print(f"  {len(only_dst)} target enrollment(s) have no source counterpart — skipped.")
    if not pairs:
        print("Nothing to do.")
        return

    planned_cats = planned_assigns = 0
    plan: list[tuple[dict, dict, list[dict], list[dict]]] = []
    for s_enr, d_enr in pairs:
        label = _course_label(d_enr["offering_id"])

        existing_cats = table("gradebook_categories").select(
            "id", filters={"enrollment_id": f"eq.{d_enr['id']}"}, limit=1
        )
        existing_assigns = table("assignments").select(
            "id", filters={"enrollment_id": f"eq.{d_enr['id']}"}, limit=1
        )
        if existing_cats or existing_assigns:
            print(f"    {label:24} already has gradebook rows — skipped")
            continue

        cats = table("gradebook_categories").select(
            CATEGORY_COLS, filters={"enrollment_id": f"eq.{s_enr['id']}"}, order="sort_order.asc"
        ) or []
        assigns = table("assignments").select(
            ASSIGNMENT_COLS, filters={"enrollment_id": f"eq.{s_enr['id']}"}, order="due_date.asc"
        ) or []
        if not cats and not assigns:
            print(f"    {label:24} source is empty — skipped")
            continue

        print(f"    {label:24} {len(cats)} categories, {len(assigns)} assignments")
        planned_cats += len(cats)
        planned_assigns += len(assigns)
        plan.append((s_enr, d_enr, cats, assigns))

    print(f"\nto create: {planned_cats} categories, {planned_assigns} assignments "
          f"across {len(plan)} enrollment(s).")
    if not plan:
        return
    if not apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        return

    print()
    for s_enr, d_enr, cats, assigns in plan:
        label = _course_label(d_enr["offering_id"])

        # 1. Categories first — assignments reference them.
        category_id_map: dict[str, str] = {}
        new_cats = []
        for c in cats:
            new_id = str(uuid.uuid4())
            category_id_map[c["id"]] = new_id
            new_cats.append({
                "id": new_id,
                "enrollment_id": d_enr["id"],
                "name": c["name"],
                "weight": c["weight"],
                "sort_order": c["sort_order"],
                "drop_lowest": c["drop_lowest"],
            })
        if new_cats:
            table("gradebook_categories").insert(new_cats)

        # 2. Assignments, with category_id remapped onto the copies. Encrypted
        #    columns ride along as ciphertext — same project, same key.
        new_assigns = []
        for a in assigns:
            row = {k: v for k, v in a.items() if k not in ("id", "enrollment_id", "category_id")}
            row["id"] = str(uuid.uuid4())
            row["enrollment_id"] = d_enr["id"]
            row["category_id"] = category_id_map.get(a.get("category_id"))
            new_assigns.append(row)
        if new_assigns:
            table("assignments").insert(new_assigns)

        # 3. Grade settings, so the computed percent/letter matches the source.
        settings = {k: s_enr.get(k) for k in ENROLLMENT_GRADE_SETTINGS}
        table("enrollments").update(settings, filters={"id": f"eq.{d_enr['id']}"})

        print(f"    {label:24} +{len(new_cats)} categories, +{len(new_assigns)} assignments")

    print(f"\nDone: {planned_cats} categories, {planned_assigns} assignments copied.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--from", dest="from_user", default="rich-user-active",
        help="source user id to copy the gradebook from (default rich-user-active)",
    )
    p.add_argument("--to", dest="to_user", required=True, help="target user id to copy onto")
    p.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    a = p.parse_args()
    copy(a.from_user, a.to_user, a.apply)
