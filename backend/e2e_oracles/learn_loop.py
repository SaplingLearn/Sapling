"""`learn_loop` oracle (PKG-13): the learning loop's write invariants, judged
over already-gathered rows. Pure — stdlib only, no IO (e2e_oracles contract).

(a) single writer: every evidence event's (user, node) has a learner_state row
    (spec §8 inv 1 — only apply_graph_update writes both, so one without the
    other means a second writer exists);
(b) no zpd.leak events (spec §6 — a leak is an error-category event);
(c) every zpd.step payload carries p_known_before/after in [0, 1];
(d) graph_nodes.mastery_score mirrors learner_state on every node that has a
    state row (spec §5; a direct check AND a one-hop propagation target — both
    are written by apply_graph_update beside the mirror), within
    ORACLE_P_TOLERANCE. `state_rows[i]["p_known"]` is the belief AT THE ROW'S
    LAST WRITE — the gatherer decays the stored value over (updated_at −
    last_evidence_at), because a propagation stores against the node's kept
    decay anchor (graph_service._keep_decay_anchor) while the mirror holds the
    belief at the write.
"""

from __future__ import annotations

import math

from e2e_oracles.findings import Finding

ORACLE_P_TOLERANCE = 1e-9  # † mirror equality; both sides are written from one float
_SAMPLE = 20


def _probability(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= float(value) <= 1.0
    )


def learn_loop_findings(
    evidence_pairs: list[tuple[str, str]],
    state_rows: list[dict],
    leak_count: int,
    step_payloads: list[dict],
    node_scores: list[dict],
) -> list[Finding]:
    findings: list[Finding] = []
    state = {(r["user_id"], r["node_id"]): r["p_known"] for r in state_rows}

    missing = sorted({(u, n) for u, n in evidence_pairs if (u, n) not in state})
    if missing:
        findings.append(
            Finding(
                oracle="learn_loop",
                summary=(
                    f"{len(missing)} evidence-touched (user, node) pair(s) have no "
                    "learner_state row — a second evidence writer?"
                ),
                evidence={"sample": missing[:_SAMPLE]},
            )
        )

    if leak_count:
        findings.append(
            Finding(
                oracle="learn_loop",
                summary=f"{leak_count} zpd.leak event(s) recorded",
                evidence={"count": leak_count},
            )
        )

    for i, payload in enumerate(step_payloads):
        body = payload if isinstance(payload, dict) else {}
        for key in ("p_known_before", "p_known_after"):
            value = body.get(key)
            if not _probability(value):
                findings.append(
                    Finding(
                        oracle="learn_loop",
                        summary=f"zpd.step payload #{i} {key} out of [0,1] or missing",
                        evidence={"value": value},
                    )
                )

    p_by_node = {node: p for (_, node), p in state.items()}
    for row in node_scores:
        node = row["id"]
        if node not in p_by_node:
            continue
        score, p = row.get("mastery_score"), p_by_node[node]
        if score is None or abs(float(score) - float(p)) > ORACLE_P_TOLERANCE:
            findings.append(
                Finding(
                    oracle="learn_loop",
                    summary=f"graph_nodes.mastery_score != learner_state p_known for {node}",
                    evidence={"mastery_score": score, "p_known": p},
                )
            )
    return findings
