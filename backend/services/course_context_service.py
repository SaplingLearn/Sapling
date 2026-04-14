"""
services/course_context_service.py

Builds and caches shared course-level context from real DB data.
Aggregates graph_nodes mastery data and quiz_context across all students in a course.

Stores data in:
- course_concept_stats: per-concept aggregated metrics
- course_summary: course-wide summary with Gemini-generated text
"""

import json
import hashlib
from datetime import datetime, timezone

from db.connection import table
from services.gemini_service import call_gemini


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
    """Generate a natural language summary using Gemini."""
    prompt = f"""You are an expert education analyst summarizing a course for instructors.

Course: {course_code} - {course_name}
Students enrolled: {student_count}
Average class mastery: {avg_class_mastery:.1%}

Top struggling concepts (needs attention):
{chr(10).join(f"- {c}" for c in top_struggling) if top_struggling else "None identified"}

Top mastered concepts (students doing well):
{chr(10).join(f"- {c}" for c in top_mastered) if top_mastered else "None identified"}

Write a concise 2-3 paragraph summary that:
1. Describes the overall class performance
2. Highlights specific areas where students are struggling and may need intervention
3. Notes areas where students are excelling
4. Provides actionable recommendations for the instructor

Write in a professional but approachable tone. Be specific and data-driven."""

    try:
        return call_gemini(prompt, retries=1)
    except Exception:
        # Fallback summary if Gemini fails
        return (
            f"Class average mastery: {avg_class_mastery:.1%}. "
            f"Students are struggling with: {', '.join(top_struggling[:3]) if top_struggling else 'No major areas identified'}. "
            f"Students have mastered: {', '.join(top_mastered[:3]) if top_mastered else 'No areas identified yet'}."
        )


def get_course_context(course_id: str) -> dict:
    """
    Return the cached course context including summary and concept stats.
    Returns dict with course_summary + course_concept_stats, or {} if not found.
    """
    if not course_id:
        return {}
    
    try:
        # Get course summary
        summary_rows = table("course_summary").select(
            "*",
            filters={"course_id": f"eq.{course_id}"},
        )
        if not summary_rows:
            return {}
        
        summary = summary_rows[0]
        
        # Get concept stats for this course
        stats_rows = table("course_concept_stats").select(
            "*",
            filters={"course_id": f"eq.{course_id}"},
        )
        
        return {
            "course_summary": {
                "course_id": summary["course_id"],
                "semester": summary["semester"],
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


def update_course_context(course_id: str, semester: str = "Spring 2026") -> None:
    """
    Aggregate mastery + quiz data for all students enrolled in the course and upsert
    into course_concept_stats and course_summary tables.
    Called automatically after any graph update.
    """
    if not course_id:
        return

    # ── 1. Get all students enrolled in this course via user_courses ───────────
    enrollment_rows = table("user_courses").select(
        "user_id",
        filters={"course_id": f"eq.{course_id}"},
    )
    if not enrollment_rows:
        return  # No students enrolled, nothing to aggregate
    
    user_ids = [r["user_id"] for r in enrollment_rows]
    student_count = len(user_ids)

    # ── 2. Get course info for the summary ────────────────────────────────────
    course_rows = table("courses").select(
        "course_code,course_name",
        filters={"id": f"eq.{course_id}"},
    )
    course_info = course_rows[0] if course_rows else {"course_code": "", "course_name": ""}

    # ── 3. All graph nodes for this course across every enrolled student ──────
    # Build user_id filter for PostgREST
    user_filter = ",".join(user_ids)
    node_rows = table("graph_nodes").select(
        "id,concept_name,mastery_score,mastery_tier,user_id",
        filters={"course_id": f"eq.{course_id}", "user_id": f"in.({user_filter})"},
    )
    if not node_rows:
        return  # No graph data yet for this course

    # ── 4. Group by concept_name, track per-user scores ───────────────────────
    concept_data: dict = {}
    node_id_set: set = set()

    for n in node_rows:
        node_id_set.add(n["id"])
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

    # ── 6. Pull quiz_context data for aggregated insights ────────────────────
    node_id_list = list(node_id_set)
    common_misconceptions: list = []
    effective_explanations: list = []
    prerequisite_gaps: list = []
    
    if node_id_list:
        node_filter = ",".join(node_id_list[:100])  # Limit to avoid URL length issues
        try:
            ctx_rows = table("quiz_context").select(
                "concept_node_id,context_json",
                filters={"concept_node_id": f"in.({node_filter})"},
            )
        except Exception:
            ctx_rows = []

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

            # Extract common mistakes as misconceptions
            for m in cj.get("common_mistakes", []):
                m = (m or "").strip()
                if m and m.lower() not in seen_misconceptions:
                    seen_misconceptions.add(m.lower())
                    common_misconceptions.append(m)

            # Extract weak areas as prerequisite gaps
            for w in cj.get("weak_areas", []):
                w = (w or "").strip()
                if w and w.lower() not in seen_prereqs:
                    seen_prereqs.add(w.lower())
                    prerequisite_gaps.append(w)
                    
            # Look for effective explanations in any field
            for exp in cj.get("effective_explanations", []):
                exp = (exp or "").strip()
                if exp and exp.lower() not in seen_explanations:
                    seen_explanations.add(exp.lower())
                    effective_explanations.append(exp)

    # ── 7. Upsert into course_concept_stats ───────────────────────────────────
    for name, metrics in concept_metrics.items():
        table("course_concept_stats").upsert(
            {
                "course_id": course_id,
                "concept_name": name,
                "semester": semester,
                "student_count": metrics["student_count"],
                "avg_mastery_score": metrics["avg_mastery_score"],
                "pct_mastered": metrics["pct_mastered"],
                "pct_struggling": metrics["pct_struggling"],
                "pct_unexplored": metrics["pct_unexplored"],
                "common_misconceptions": common_misconceptions[:20],  # Limit array size
                "effective_explanations": effective_explanations[:20],
                "prerequisite_gaps": prerequisite_gaps[:20],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="course_id,concept_name,semester",
        )

    # ── 8. Compute course-wide summary metrics ────────────────────────────────
    avg_class_mastery = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0
    
    # Sort for top struggling (highest pct_struggling) and top mastered
    sorted_by_struggling = sorted(
        [(name, m) for name, m in concept_metrics.items()],
        key=lambda x: x[1]["pct_struggling"],
        reverse=True,
    )
    top_struggling_concepts = [name for name, _ in sorted_by_struggling[:5]]
    
    sorted_by_mastered = sorted(
        [(name, m) for name, m in concept_metrics.items()],
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
    existing_summary_rows = table("course_summary").select(
        "summary_hash,summary_text",
        filters={"course_id": f"eq.{course_id}", "semester": f"eq.{semester}"},
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

    # ── 10. Upsert into course_summary ────────────────────────────────────────
    table("course_summary").upsert(
        {
            "course_id": course_id,
            "semester": semester,
            "student_count": student_count,
            "avg_class_mastery": avg_class_mastery,
            "top_struggling_concepts": top_struggling_concepts,
            "top_mastered_concepts": top_mastered_concepts,
            "summary_text": summary_text,
            "summary_hash": current_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="course_id,semester",
    )
