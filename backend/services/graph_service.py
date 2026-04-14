import uuid
from datetime import datetime, date, timedelta

from config import get_mastery_tier
from db.connection import table


def _user_enrolled_courses(user_id: str) -> list[dict]:
    """Get all courses a user is enrolled in via user_courses join."""
    try:
        rows = table("user_courses").select(
            "id,course_id,color,nickname,enrolled_at,courses!inner(course_code,course_name,department,school)",
            filters={"user_id": f"eq.{user_id}"},
        )
    except Exception:
        return []
    return rows or []


def _get_course_nodes(user_id: str, course_id: str) -> list:
    """Get graph nodes for a specific course."""
    return table("graph_nodes").select(
        "*",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    ) or []


def ensure_user_exists(user_id: str) -> None:
    """Create a user row if one doesn't exist yet (prevents FK violations)."""
    existing = table("users").select("id", filters={"id": f"eq.{user_id}"})
    if not existing:
        name = user_id.replace("user_", "").replace("_", " ").title()
        try:
            table("users").insert({"id": user_id, "name": name, "streak_count": 0})
        except Exception:
            pass  # already exists (race condition) — safe to ignore


def update_streak(user_id: str) -> None:
    """Increment streak if first study activity today, reset to 1 if gap > 1 day."""
    today = date.today().isoformat()
    rows = table("users").select("streak_count,last_active_date", filters={"id": f"eq.{user_id}"})
    if not rows:
        return
    row = rows[0]
    last = row.get("last_active_date")
    streak = row.get("streak_count") or 0

    if last == today:
        return  # already counted today

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    new_streak = streak + 1 if last == yesterday else 1

    table("users").update(
        {"streak_count": new_streak, "last_active_date": today},
        filters={"id": f"eq.{user_id}"},
    )


def _compute_velocity(events: list) -> float:
    """Mastery gained per day over the last 14 days. Returns 0.0 if insufficient data."""
    if not events:
        return 0.0
    cutoff = datetime.utcnow() - timedelta(days=14)
    recent = []
    for e in events:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).replace(tzinfo=None)
            if ts > cutoff:
                recent.append(e)
        except Exception:
            pass
    if not recent:
        return 0.0
    positive_gain = sum(e.get("delta", 0) for e in recent if e.get("delta", 0) > 0)
    if positive_gain == 0:
        return 0.0
    try:
        first_ts = datetime.fromisoformat(recent[0]["ts"].replace("Z", "+00:00")).replace(tzinfo=None)
        days = max(1, (datetime.utcnow() - first_ts).days)
    except Exception:
        days = 1
    return round(positive_gain / days, 4)


def get_graph(user_id: str) -> dict:
    ensure_user_exists(user_id)
    
    # Get all enrolled courses for this user
    enrolled_courses = _user_enrolled_courses(user_id)
    course_id_map = {r["course_id"]: r for r in enrolled_courses}
    
    # Get all graph nodes for this user
    nodes_raw = table("graph_nodes").select("*", filters={"user_id": f"eq.{user_id}"})
    nodes = nodes_raw or []
    node_ids = {n["id"] for n in nodes}

    edges_raw = table("graph_edges").select("*", filters={"user_id": f"eq.{user_id}"})
    edges = [
        {
            "id": e["id"],
            "source": e["source_node_id"],
            "target": e["target_node_id"],
            "strength": e["strength"],
            "relationship_type": e.get("relationship_type", "related"),
        }
        for e in edges_raw
        if e["source_node_id"] in node_ids and e["target_node_id"] in node_ids
    ]

    # Enrich each node with learning velocity; trim event history for API response
    for n in nodes:
        events = n.get("mastery_events") or []
        n["learning_velocity"] = _compute_velocity(events)
        n["mastery_events"] = events[-5:]  # keep last 5 for UI; full history lives in DB

    mastered   = sum(1 for n in nodes if n["mastery_tier"] == "mastered")
    learning   = sum(1 for n in nodes if n["mastery_tier"] == "learning")
    struggling = sum(1 for n in nodes if n["mastery_tier"] == "struggling")
    unexplored = sum(1 for n in nodes if n["mastery_tier"] == "unexplored")

    velocities = [n["learning_velocity"] for n in nodes if n["learning_velocity"] > 0]
    avg_velocity = round(sum(velocities) / len(velocities), 4) if velocities else 0.0

    user_rows = table("users").select("streak_count", filters={"id": f"eq.{user_id}"})
    streak = user_rows[0]["streak_count"] if user_rows else 0

    stats = {
        "total_nodes": len(nodes),
        "mastered": mastered,
        "learning": learning,
        "struggling": struggling,
        "unexplored": unexplored,
        "streak": streak,
        "avg_learning_velocity": avg_velocity,
    }

    # Build subject root hubs from enrolled courses
    subject_nodes = []
    subject_edges = []
    
    for enrollment in enrolled_courses:
        course_id = enrollment["course_id"]
        course = enrollment.get("courses", {}) if isinstance(enrollment.get("courses"), dict) else {}
        course_code = course.get("course_code", "")
        course_name = course.get("course_name", "")
        
        # Use "Course Code - Course Name" as the subject label
        subject_label = f"{course_code} - {course_name}" if course_code else course_name
        
        # Find all nodes belonging to this course
        subj_nodes = [n for n in nodes if n.get("course_id") == course_id]
        
        root_id = f"subject_root__{course_id}"
        if subj_nodes:
            avg_mastery = sum(n["mastery_score"] for n in subj_nodes) / len(subj_nodes)
        else:
            avg_mastery = 0.0
            
        subject_nodes.append({
            "id": root_id,
            "user_id": user_id,
            "concept_name": subject_label,
            "mastery_score": round(avg_mastery, 4),
            "mastery_tier": "subject_root",
            "course_id": course_id,
            "times_studied": sum(n.get("times_studied", 0) for n in subj_nodes),
            "last_studied_at": None,
            "is_subject_root": True,
        })
        
        for n in subj_nodes:
            subject_edges.append({
                "id": f"subject_edge__{root_id}__{n['id']}",
                "source": root_id,
                "target": n["id"],
                "strength": 0.7,
                "relationship_type": "related",
            })

    return {"nodes": nodes + subject_nodes, "edges": edges + subject_edges, "stats": stats}


# ── Course management ──────────────────────────────────────────────────────────

def get_courses(user_id: str) -> list:
    """
    Return user's enrolled courses joined with canonical course data.
    Returns list of dicts with: enrollment_id, course_id, course_code, course_name, 
    school, department, color, nickname, node_count, enrolled_at
    """
    try:
        rows = table("user_courses").select(
            "id,course_id,color,nickname,enrolled_at,courses!inner(course_code,course_name,school,department)",
            filters={"user_id": f"eq.{user_id}"},
            order="enrolled_at.asc",
        )
    except Exception:
        return []
    
    result = []
    for r in rows:
        course = r.get("courses", {}) if isinstance(r.get("courses"), dict) else {}
        course_id = r["course_id"]
        
        # Count nodes for this course
        node_rows = table("graph_nodes").select(
            "id",
            filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        )
        
        result.append({
            "enrollment_id": r["id"],
            "course_id": course_id,
            "course_code": course.get("course_code", ""),
            "course_name": course.get("course_name", ""),
            "school": course.get("school", ""),
            "department": course.get("department", ""),
            "color": r.get("color"),
            "nickname": r.get("nickname"),
            "node_count": len(node_rows),
            "enrolled_at": r["enrolled_at"],
        })
    return result


def add_course(user_id: str, course_id: str, color: str | None = None, nickname: str | None = None) -> dict:
    """
    Enroll a user in a course (insert into user_courses).
    course_id refers to the canonical courses table.
    """
    # Check if already enrolled
    existing = table("user_courses").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )
    if existing:
        return {"course_id": course_id, "already_existed": True}
    
    # Verify the course exists in canonical courses
    course_check = table("courses").select("id", filters={"id": f"eq.{course_id}"})
    if not course_check:
        return {"course_id": course_id, "error": "Course not found in catalog"}
    
    table("user_courses").insert({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "color": color,
        "nickname": nickname,
    })
    return {"course_id": course_id, "already_existed": False}


def update_course_color(user_id: str, course_id: str, color: str) -> dict:
    """Update the color for a user's course enrollment."""
    table("user_courses").update(
        {"color": color},
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )
    return {"updated": True}


def update_course_nickname(user_id: str, course_id: str, nickname: str) -> dict:
    """Update the nickname for a user's course enrollment."""
    table("user_courses").update(
        {"nickname": nickname},
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
    )
    return {"updated": True}


def delete_course(user_id: str, course_id: str) -> dict:
    """
    Unenroll a user from a course (delete from user_courses).
    Note: We don't delete the graph nodes - they remain for potential re-enrollment.
    """
    # Just delete the enrollment, not the nodes
    table("user_courses").delete(
        {"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"}
    )
    return {"deleted": True}


def _node_filters(user_id: str, concept_name: str, course_id: str | None) -> dict:
    f = {"user_id": f"eq.{user_id}", "concept_name": f"eq.{concept_name}"}
    if course_id:
        f["course_id"] = f"eq.{course_id}"
    return f


def apply_graph_update(user_id: str, graph_update: dict, course_id: str | None = None) -> list:
    """
    Apply a graph_update dict to the DB. Returns mastery_changes list.
    If course_id is provided, all new/updated nodes will be associated with that course.
    """
    mastery_changes = []
    touched_courses: set = set()

    for new_node in graph_update.get("new_nodes", []):
        name = new_node.get("concept_name", "")
        node_course_id = course_id or new_node.get("course_id")
        init_m = float(new_node.get("initial_mastery", 0.0))
        
        existing = table("graph_nodes").select(
            "id",
            filters=_node_filters(user_id, name, node_course_id),
        )
        
        if not existing:
            table("graph_nodes").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "concept_name": name,
                "mastery_score": init_m,
                "mastery_tier": get_mastery_tier(init_m),
                "course_id": node_course_id,
                "mastery_events": [],
            })
            if node_course_id:
                touched_courses.add(node_course_id)

    for upd in graph_update.get("updated_nodes", []):
        name = upd.get("concept_name", "")
        delta = float(upd.get("mastery_delta", 0.0))
        rows = table("graph_nodes").select(
            "id,mastery_score,times_studied,course_id,mastery_events",
            filters=_node_filters(user_id, name, course_id),
        )
        if rows:
            row = rows[0]
            before = row["mastery_score"]
            after = max(0.0, min(1.0, before + delta))

            existing_events = row.get("mastery_events") or []
            new_event = {
                "ts": datetime.utcnow().isoformat(),
                "delta": delta,
                "reason": upd.get("reason", ""),
                "event_type": upd.get("event_type", "interaction"),
            }
            updated_events = (existing_events + [new_event])[-20:]

            table("graph_nodes").update(
                {
                    "mastery_score": after,
                    "mastery_tier": get_mastery_tier(after),
                    "times_studied": row["times_studied"] + 1,
                    "last_studied_at": datetime.utcnow().isoformat(),
                    "mastery_events": updated_events,
                },
                filters={"id": f"eq.{row['id']}"},
            )
            mastery_changes.append({"concept": name, "before": before, "after": after})
            
            cid = row.get("course_id")
            if cid:
                touched_courses.add(cid)
                
    if mastery_changes:
        update_streak(user_id)

    for new_edge in graph_update.get("new_edges", []):
        src_name = new_edge.get("source", "")
        tgt_name = new_edge.get("target", "")
        strength = float(new_edge.get("strength", 0.5))
        relationship_type = new_edge.get("relationship_type", "related")
        src_rows = table("graph_nodes").select(
            "id", filters=_node_filters(user_id, src_name, course_id)
        )
        tgt_rows = table("graph_nodes").select(
            "id", filters=_node_filters(user_id, tgt_name, course_id)
        )
        if src_rows and tgt_rows:
            src_id = src_rows[0]["id"]
            tgt_id = tgt_rows[0]["id"]
            existing_edge = table("graph_edges").select(
                "id",
                filters={
                    "user_id": f"eq.{user_id}",
                    "source_node_id": f"eq.{src_id}",
                    "target_node_id": f"eq.{tgt_id}",
                },
            )
            if not existing_edge:
                table("graph_edges").insert({
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "source_node_id": src_id,
                    "target_node_id": tgt_id,
                    "strength": strength,
                    "relationship_type": relationship_type,
                })

    # Refresh shared course context for every course touched in this update
    if touched_courses:
        from services.course_context_service import update_course_context
        for cid in touched_courses:
            try:
                update_course_context(cid)
            except Exception:
                pass  # never block the main response for a context refresh

    return mastery_changes


def get_recommendations(user_id: str) -> list:
    rows = table("graph_nodes").select(
        "concept_name,mastery_score,mastery_tier",
        filters={
            "user_id": f"eq.{user_id}",
            "mastery_tier": "in.(struggling,learning,unexplored)",
        },
        order="mastery_score.asc",
        limit=5,
    )
    recs = []
    for r in rows:
        tier = r["mastery_tier"]
        if tier == "unexplored":
            reason = "You haven't studied this yet — a great place to start."
        elif tier == "struggling":
            reason = f"You're struggling here ({int(r['mastery_score']*100)}%) — focus here to improve."
        else:
            reason = f"You're making progress ({int(r['mastery_score']*100)}%) — keep going!"
        recs.append({"concept_name": r["concept_name"], "reason": reason})
    return recs
