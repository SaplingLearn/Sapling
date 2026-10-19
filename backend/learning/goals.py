"""Private session goals. Ownership and course scope are checked by the route.

Only confirmed concept IDs drive planning. The learner's prose is encrypted at
rest and is untrusted context when rendered into a tutor prompt.
"""

from __future__ import annotations

import hashlib
import json
import math

from learning.params import BKT_PROFICIENT
from services.encryption import decrypt_if_present, encrypt_if_present


def encode_goal(goal) -> dict | None:
    if goal is None:
        return None
    return {
        "target_node_ids": list(goal.target_node_ids),
        "text_encrypted": encrypt_if_present(goal.text),
    }


def public_goal(state: dict) -> dict | None:
    goal = state.get("goal")
    if not isinstance(goal, dict) or not goal.get("target_node_ids"):
        return None
    return {
        "text": decrypt_if_present(goal.get("text_encrypted")) or "",
        "target_node_ids": list(goal["target_node_ids"]),
    }


def goal_version(state: dict) -> int:
    return int(state.get("goal_version") or 0)


def attempted_nodes(state: dict) -> list[str]:
    """Exhausted session frontiers, never a claim that these skills are known."""
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    attempted = plan.get("attempted")
    if not isinstance(attempted, list):
        return []
    return list(dict.fromkeys(n for n in attempted if isinstance(n, str) and n.strip()))


def planning_observations(state: dict) -> list[dict]:
    """Chronological metadata from diagnosis and actually graded teaching items.

    Legacy steps without explicit independence provenance cannot resolve an
    observed failure. No response, reference or other learner prose is read.
    """
    probe = state.get("probe") if isinstance(state.get("probe"), dict) else {}
    history = probe.get("history") if isinstance(probe.get("history"), list) else []
    steps = state.get("steps") if isinstance(state.get("steps"), dict) else {}
    graded = [
        entry
        for entry in steps.values()
        if isinstance(entry, dict)
        and isinstance(entry.get("goal_observation"), dict)
        and type(entry.get("graded_at")) in (int, float)
        and math.isfinite(entry["graded_at"])
    ]
    graded.sort(
        key=lambda entry: (
            entry["graded_at"],
            str(entry["goal_observation"].get("question_hash") or ""),
        )
    )
    return history + [entry["goal_observation"] for entry in graded]


def scope_signature(targets, scope, edges) -> str:
    """IDs-only proposal fingerprint; graph edits require a fresh approval."""
    scope = set(scope)
    value = {
        "targets": sorted(set(targets)),
        "scope": sorted(scope),
        "edges": sorted({(a, b) for a, b in edges if a in scope and b in scope}),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def progress(state: dict, states: dict[str, float], scope, *, continue_available: bool) -> dict:
    """Bounded goal progress, distinct from mastery or successful learning."""
    goal = state.get("goal") if isinstance(state.get("goal"), dict) else {}
    targets = list(goal.get("target_node_ids") or [])
    attempted = attempted_nodes(state)
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    checked = set(plan["checked_nodes"]) if isinstance(plan.get("checked_nodes"), list) else set()
    remaining = [n for n in targets if n not in checked or states[n] < BKT_PROFICIENT]
    unresolved = sorted(n for n in scope if n not in targets and states[n] < BKT_PROFICIENT)
    status = (
        "continue_available"
        if continue_available
        else "needs_more_practice"
        if remaining or unresolved
        else "session_plan_finished"
    )
    return {
        "status": status,
        "target_node_ids": targets,
        "remaining_target_node_ids": remaining,
        "unresolved_prerequisite_ids": unresolved,
        "attempted_node_ids": attempted,
    }
