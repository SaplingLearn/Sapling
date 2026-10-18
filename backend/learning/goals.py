"""Private session goals. Ownership and course scope are checked by the route.

Only confirmed concept IDs drive planning. The learner's prose is encrypted at
rest and is untrusted context when rendered into a tutor prompt.
"""

from __future__ import annotations

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
