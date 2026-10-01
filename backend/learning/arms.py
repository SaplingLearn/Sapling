"""Within-student A/B arms (PKG-14; spec §4 `user_settings.loop_arm`, §10 rung 2,
§13 A8). Pure: ids and the arm label in, a variant out.

Concepts — not students — are randomised (research §"Measure learning with
tool-removed, delayed checks": within-student randomisation). The arm is
plumbing: a NULL or empty `loop_arm` is variant A for every concept, so nothing
changes until the series owner sets an arm by SQL. Analysis is
intention-to-treat by the assigned variant, plus the tier actually served
(`zpd.step.tier`) with a cap-hit covariate (`ai.budget_capped` for that
user-day). Kept out of `learning/policy.py`, whose public functions take typed,
text-free parameters only (spec §8 invariant 4).
"""

from __future__ import annotations

import hashlib
from typing import Literal

Variant = Literal["A", "B"]  # spec §13 A8: `zpd.step.variant`


def variant_for(user_id: str, node_id: str, arm: str | None) -> Variant:
    """ "A" whenever `arm` is None or empty; otherwise "A" when the first byte of
    sha256(f"{arm}:{user_id}:{node_id}") is even, else "B". A different arm
    label reshuffles the concepts."""
    if not arm:
        return "A"
    digest = hashlib.sha256(f"{arm}:{user_id}:{node_id}".encode("utf-8")).digest()
    return "A" if digest[0] & 1 == 0 else "B"  # the first byte's parity
