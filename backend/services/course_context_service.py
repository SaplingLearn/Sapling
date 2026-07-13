"""
services/course_context_service.py

Builds and caches shared class-level context from real DB data.
Aggregates graph_nodes mastery data and quiz_context across all students in an
offering (a course taught in a term). The graph is keyed on the abstract course;
analytics are keyed on the offering.

Stores data in:
- offering_concept_stats: per-concept aggregated metrics (per offering)
- offering_summary: class-wide summary with Gemini-generated text (per offering)
"""

import json
import hashlib
from datetime import datetime, timezone

from db.connection import table
from agents._run import run_agent_sync
from agents.course_summary import course_summary_agent


def _generate_data_hash(stats_rows: list) -> str:
    """Generate a hash of the stats data to detect changes."""
    data_str = json.dumps(stats_rows, sort_keys=True, default=str)
    return hashlib.sha256(data_str.encode()).hexdigest()


def _generate_summary_with_gemini(
    course_code: str,
    course_name: str,
    avg_class_mastery: float,
    top_struggling: list,
    top_mastered: list,
    student_count: int,
) -> str:
    """Generate a natural-language class summary via the course_summary agent.

    The agent owns the analyst persona; the aggregated metrics go in the user
    message. On any agent failure we degrade to a deterministic template string
    (no second LLM call), so a summary is always produced."""
    user_message = (
        f"Course: {course_code} - {course_name}\n"
        f"Students enrolled: {student_count}\n"
        f"Average class mastery: {avg_class_mastery:.1%}\n\n"
        "Top struggling concepts (needs attention):\n"
        f"{chr(10).join(f'- {c}' for c in top_struggling) if top_struggling else 'None identified'}\n\n"
        "Top mastered concepts (students doing well):\n"
        f"{chr(10).join(f'- {c}' for c in top_mastered) if top_mastered else 'None identified'}"
    )

    try:
        result = run_agent_sync(course_summary_agent.run(user_message))
        return result.output.summary
    except Exception:
        # Fallback summary if the agent fails
        return (
            f"Class average mastery: {avg_class_mastery:.1%}. "
            f"Students are struggling with: {', '.join(top_struggling[:3]) if top_struggling else 'No major areas identified'}. "
            f"Students have mastered: {', '.join(top_mastered[:3]) if top_mastered else 'No areas identified yet'}."
        )


def get_course_context(offering_id: str) -> dict:
    """
    Return the cached class context for an offering: summary + concept stats.
    Offering-scoped (one class instance in one term). Returns {} if not found.
    """
    if not offering_id:
        return {}

    try:
        # Get the offering summary
        summary_rows = table("offering_summary").select(
            "*",
            filters={"offering_id": f"eq.{offering_id}"},
        )
        if not summary_rows:
            return {}

        summary = summary_rows[0]

        # Get concept stats for this offering
        stats_rows = table("offering_concept_stats").select(
            "*",
            filters={"offering_id": f"eq.{offering_id}"},
        )

        return {
            "course_summary": {
                "offering_id": summary["offering_id"],
                "student_count": summary["student_count"],
                "avg_class_mastery": summary["avg_class_mastery"],
                "top_struggling_concepts": summary.get("top_struggling_concepts", []),
                "top_mastered_concepts": summary.get("top_mastered_concepts", []),
                "summary_text": summary.get("summary_text", ""),
                "updated_at": summary["updated_at"],
            },
            "concept_stats": stats_rows or [],
        }
    except Exception:
        return {}


def update_course_context(offering_id: str) -> None:
    """
    Aggregate mastery + quiz data for all students enrolled in an **offering**
    (a course taught in a term) and upsert into offering_concept_stats and
    offering_summary. Offering-scoped. Called automatically after any graph update.

    The knowledge graph is keyed on the *abstract* course id, so we resolve the
    offering → its abstract course to read graph_nodes.
    """
    if not offering_id:
        return

    # ── 1. Get all students enrolled in this offering via enrollments ─────────
    enrollment_rows = table("enrollments").select(
        "user_id",
        filters={"offering_id": f"eq.{offering_id}"},
    )
    if not enrollment_rows:
        # No students enrolled — purge any stale aggregates
        table("offering_concept_stats").delete({"offering_id": f"eq.{offering_id}"})
        table("offering_summary").delete({"offering_id": f"eq.{offering_id}"})
        return

    user_ids = [r["user_id"] for r in enrollment_rows]
    student_count = len(user_ids)

    # ── 2. Resolve the offering → abstract course (graph key) + term label ────
    from services.academics import offering_course_id
    abstract_course_id = offering_course_id(offering_id)
    if not abstract_course_id:
        return
    course_rows = table("courses").select(
        "course_code,course_name",
        filters={"id": f"eq.{abstract_course_id}"},
    )
    course_info = course_rows[0] if course_rows else {"course_code": "", "course_name": ""}

    # ── 3. All graph nodes for this (abstract) course across enrolled students ─
    # Build user_id filter for PostgREST
    user_filter = ",".join(user_ids)
    node_rows = table("graph_nodes").select(
        "id,concept_name,mastery_score,mastery_tier,user_id",
        filters={"course_id": f"eq.{abstract_course_id}", "user_id": f"in.({user_filter})"},
    )
    if not node_rows:
        return  # No graph data yet for this course

    # ── 4. Group by concept_name, track per-user scores ───────────────────────
    concept_data: dict = {}

    for n in node_rows:
        name = n["concept_name"]
        if name not in concept_data:
            concept_data[name] = {"scores": [], "tiers": [], "node_ids": []}
        concept_data[name]["scores"].append(float(n["mastery_score"] or 0.0))
        concept_data[name]["tiers"].append(n["mastery_tier"] or "unexplored")
        concept_data[name]["node_ids"].append(n["id"])

    # ── 5. Compute per-concept metrics ────────────────────────────────────────
    concept_metrics: dict = {}
    all_scores: list = []
    
    for name, data in concept_data.items():
        scores = data["scores"]
        tiers = data["tiers"]
        n_s = len(scores)
        
        if n_s == 0:
            continue
            
        avg_mastery = sum(scores) / n_s
        all_scores.extend(scores)
        
        struggling_count = sum(1 for t in tiers if t == "struggling")
        mastered_count = sum(1 for t in tiers if t == "mastered")
        unexplored_count = sum(1 for t in tiers if t == "unexplored")
        
        concept_metrics[name] = {
            "avg_mastery_score": round(avg_mastery, 4),
            "pct_struggling": round(struggling_count / n_s, 4),
            "pct_mastered": round(mastered_count / n_s, 4),
            "pct_unexplored": round(unexplored_count / n_s, 4),
            "student_count": n_s,
            "node_ids": data["node_ids"],
        }

    # ── 6. Helpers: quiz_context rows for a set of graph node ids ────────────
    def _fetch_quiz_context_rows(node_ids: list) -> list:
        if not node_ids:
            return []
        chunk_size = 80
        out = []
        for i in range(0, len(node_ids), chunk_size):
            chunk = node_ids[i : i + chunk_size]
            node_filter = ",".join(chunk)
            try:
                rows = table("quiz_context").select(
                    "concept_node_id,context_json",
                    filters={"concept_node_id": f"in.({node_filter})"},
                )
            except Exception:
                rows = []
            out.extend(rows or [])
        return out

    def _parse_quiz_context_to_arrays(ctx_rows: list) -> tuple[list, list, list]:
        common_misconceptions: list = []
        effective_explanations: list = []
        prerequisite_gaps: list = []
        seen_misconceptions: set = set()
        seen_explanations: set = set()
        seen_prereqs: set = set()

        for ctx in ctx_rows:
            cj = ctx.get("context_json") or {}
            if isinstance(cj, str):
                try:
                    cj = json.loads(cj)
                except Exception:
                    cj = {}

            for m in cj.get("common_mistakes", []):
                m = (m or "").strip()
                if m and m.lower() not in seen_misconceptions:
                    seen_misconceptions.add(m.lower())
                    common_misconceptions.append(m)

            for w in cj.get("weak_areas", []):
                w = (w or "").strip()
                if w and w.lower() not in seen_prereqs:
                    seen_prereqs.add(w.lower())
                    prerequisite_gaps.append(w)

            for exp in cj.get("effective_explanations", []):
                exp = (exp or "").strip()
                if exp and exp.lower() not in seen_explanations:
                    seen_explanations.add(exp.lower())
                    effective_explanations.append(exp)

        return common_misconceptions[:20], effective_explanations[:20], prerequisite_gaps[:20]

    # ── 7. Upsert into course_concept_stats (quiz arrays per concept) ─────────
    for name, metrics in concept_metrics.items():
        node_ids_for_concept = concept_data.get(name, {}).get("node_ids", [])
        ctx_rows = _fetch_quiz_context_rows(node_ids_for_concept)
        cm, ee, pg = _parse_quiz_context_to_arrays(ctx_rows)

        table("offering_concept_stats").upsert(
            {
                "offering_id": offering_id,
                "concept_name": name,
                "student_count": metrics["student_count"],
                "avg_mastery_score": metrics["avg_mastery_score"],
                "pct_mastered": metrics["pct_mastered"],
                "pct_struggling": metrics["pct_struggling"],
                "pct_unexplored": metrics["pct_unexplored"],
                "common_misconceptions": cm,
                "effective_explanations": ee,
                "prerequisite_gaps": pg,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="offering_id,concept_name",
        )

    # ── 8. Compute course-wide summary metrics ────────────────────────────────
    avg_class_mastery = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
    
    # Sort for top struggling (highest pct_struggling) and top mastered, excluding zeros
    sorted_by_struggling = sorted(
        [(name, m) for name, m in concept_metrics.items() if m["pct_struggling"] > 0.0],
        key=lambda x: x[1]["pct_struggling"],
        reverse=True,
    )
    top_struggling_concepts = [name for name, _ in sorted_by_struggling[:5]]

    sorted_by_mastered = sorted(
        [(name, m) for name, m in concept_metrics.items() if m["pct_mastered"] > 0.0],
        key=lambda x: x[1]["pct_mastered"],
        reverse=True,
    )
    top_mastered_concepts = [name for name, _ in sorted_by_mastered[:5]]

    # Generate data hash to detect changes
    stats_for_hash = [
        {
            "concept": name,
            "avg_mastery": m["avg_mastery_score"],
            "pct_struggling": m["pct_struggling"],
            "pct_mastered": m["pct_mastered"],
        }
        for name, m in concept_metrics.items()
    ]
    current_hash = _generate_data_hash(stats_for_hash)

    # ── 9. Check if summary needs regeneration ─────────────────────────────────
    existing_summary_rows = table("offering_summary").select(
        "summary_hash,summary_text",
        filters={"offering_id": f"eq.{offering_id}"},
    )
    
    existing_hash = existing_summary_rows[0]["summary_hash"] if existing_summary_rows else None
    
    # Regenerate summary only if data changed or no existing summary
    if current_hash != existing_hash or not existing_summary_rows:
        summary_text = _generate_summary_with_gemini(
            course_info.get("course_code", ""),
            course_info.get("course_name", ""),
            avg_class_mastery,
            top_struggling_concepts,
            top_mastered_concepts,
            student_count,
        )
    else:
        summary_text = existing_summary_rows[0].get("summary_text", "")

    # ── 10. Upsert into offering_summary ──────────────────────────────────────
    table("offering_summary").upsert(
        {
            "offering_id": offering_id,
            "student_count": student_count,
            "avg_class_mastery": avg_class_mastery,
            "top_struggling_concepts": top_struggling_concepts,
            "top_mastered_concepts": top_mastered_concepts,
            "summary_text": summary_text,
            "summary_hash": current_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="offering_id",
    )
