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
    belief at the write. One exception (#866 audit K22): a never-studied
    concept (map score 0) whose state row has no observation of its own
    (`opps` 0: only one-hop propagation reached it, or a void took back its
    only answers) stays off the map by design — its mirror is 0, not the
    propagated belief.
(e)–(h) `learn_loop_activity_findings` (below): the rows the session documents
    claim exist, no pre-release final-answer leak in the transcript, and —
    under --expect-loop-activity — no vacuous pass.
"""

from __future__ import annotations

import math
import re

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
    unobserved = {r["node_id"] for r in state_rows if r.get("opps") == 0}

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
        if node in unobserved and score is not None and float(score) == 0.0:
            continue  # K22: never studied, only propagated to — off the map
        if score is None or abs(float(score) - float(p)) > ORACLE_P_TOLERANCE:
            findings.append(
                Finding(
                    oracle="learn_loop",
                    summary=f"graph_nodes.mastery_score != learner_state p_known for {node}",
                    evidence={"mastery_score": score, "p_known": p},
                )
            )
    return findings


# ── Activity (PKG-13 fix round): the oracle must not pass vacuously ──────────
# The table-wide checks above pass on an empty stack. These tie the loop's
# rows to the session documents that claim them:
# (e) every check step a session GRADED has an evidence row for its hash
#     written BY THAT SESSION (the loop's only evidence path, A16; one flush
#     per grade; the row's `session_id`) — never another session's row for
#     the same item, which would hide a lost flush (Z47);
# (f) every step whose feedback turn RAN has a zpd.step event (spec §6) of
#     that session (the check-phase payload's `session_id`, A82);
# (g) no assistant message of a loop session states a check item's final
#     answer before THAT item was released (D7: per item, never per session) —
#     a graded step whose verdict is not `correct` (the feedback reply then
#     opens with it, A16/A51) or a logged H6 worked answer. A seeded check
#     item's key is the sentinel (`sentinel`, E2E_LOOP_FINAL_ANSWER,
#     case-insensitive) plus "<slug>-<format>-d<difficulty>", read back off the
#     step's check_item_id (`rich-check-<slug>-<format>-d<difficulty>`); a key
#     no step of the session carries fails closed. A BARE sentinel is the
#     answer every seeded item shares, so it is read as the answer of the item
#     in front of the student when it was said — the step shown most recently
#     by then — and passes only once THAT item was released (an earlier
#     item's release never opens a later one). A release in one session never
#     opens another. An assistant row that cannot be decrypted is a finding of
#     its own (never read as empty text). The text is never echoed;
# (g') likewise for the segment prequestion's OWN sentinel (spec §13 A138,
#     `prequestion_sentinel`, E2E_LOOP_PREQUESTION_ANSWER — the seeded
#     prequestion items' key, never a check's), PER ITEM (second review): each
#     seeded item's key is the sentinel plus "<slug>-pq<n>", and no assistant
#     message states an item's key before the session answered THAT item's
#     prequestion (its record's check_item_id names it); a bare or unknown key
#     fails closed. Each release opens only its own item's key;
# (h) with `expect_activity` (the loop journey runs the oracle right after its
#     walk, before the next test's truncate-and-reseed): no loop user, or no
#     graded check step anywhere, is itself a finding. A loop user is a student
#     with a loop session (`sessions` — never a settings row: the gate reads no
#     column, and the retired build-phase staff/QA toggle is inert seed data, Z50).
_RELEASE_RUNG = 6  # H6: the worked answer (learning.ladder.Rung.H6)


def _steps_of(session: dict) -> dict:
    state = session.get("loop_state")
    steps = state.get("steps") if isinstance(state, dict) else None
    return {k: v for k, v in (steps or {}).items() if isinstance(v, dict)}


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _prequestions_of(session: dict) -> dict:
    state = session.get("loop_state")
    records = state.get("prequestion") if isinstance(state, dict) else None
    return {k: v for k, v in (records or {}).items() if isinstance(v, dict)} if isinstance(records, dict) else {}


#: A seeded prequestion item (scripts/seed_learning_teach_prompts.py) → its sentinel's token.
_SEEDED_PREQUESTION = re.compile(r"^rich-check-(?P<slug>.+)-mc-pq(?P<n>\d+)$")


def _prequestion_cutoffs(prequestions: dict) -> dict[str, float | None]:
    """Spec §13 A138, per ITEM (second review): each posed seeded item's token
    (`<slug>-pq<n>`, read off the record's check_item_id) → when the session
    released its answer — the record's `answered_at` once answered (its
    explaining turn opens with it) — or None (posed, never answered)."""
    out: dict[str, float | None] = {}
    for record in prequestions.values():
        m = _SEEDED_PREQUESTION.match(str(record.get("check_item_id") or ""))
        if m is None:
            continue
        answered = record.get("status") in ("answered", "resolved")
        out[f"{m['slug']}-pq{m['n']}"] = _number(record.get("answered_at")) if answered else None
    return out


def _worked_at(step: dict) -> float | None:
    """When the step's H6 worked answer was logged, or None."""
    times = []
    for r in step.get("rungs") or []:
        at = _number(r.get("at")) if isinstance(r, dict) else None
        rung = _number(r.get("rung")) if isinstance(r, dict) else None
        if at is not None and rung is not None and rung >= _RELEASE_RUNG:
            times.append(at)
    return min(times) if times else None


def _step_release(step: dict) -> float | None:
    """When THIS item's answer was released — graded other than `correct`, or
    an H6 worked answer — or None (never)."""
    graded = _number(step.get("graded_at"))
    times = [graded] if graded is not None and step.get("last_verdict") != "correct" else []
    worked = _worked_at(step)
    if worked is not None:
        times.append(worked)
    return min(times) if times else None


#: A seeded check item (db/seed_local_rich.py::loop_item_id) → its key's token.
_SEEDED_CHECK = re.compile(r"^rich-check-(?P<slug>.+)-(?P<fmt>[a-z_]+)-d(?P<d>\d+)$")


def _check_cutoffs(steps: dict) -> dict[str, float | None]:
    """Each seeded check item's token (`<slug>-<format>-d<difficulty>`, read
    off the step's check_item_id) → when the session released THAT item."""
    out: dict[str, float | None] = {}
    for step in steps.values():
        m = _SEEDED_CHECK.match(str(step.get("check_item_id") or ""))
        if m is not None:
            out[f"{m['slug']}-{m['fmt']}-d{m['d']}"] = _step_release(step)
    return out


def _bare_mention_released(steps: dict, at: float | None) -> bool:
    """A bare sentinel at `at` is read as the answer of the item in front of
    the student then: the step shown most recently at or before `at` (no
    first_shown_at: shown from the start). It passes only when that item was
    released by `at`; with no item shown yet, nothing released it. An unknown
    time fails closed."""
    if at is None:
        return False
    shown = [(_number(s.get("first_shown_at")) or 0.0, s) for s in steps.values()]
    shown = [(t, s) for t, s in shown if t <= at]
    if not shown:
        return False
    latest = max(t for t, _ in shown)
    return all(
        (released := _step_release(s)) is not None and released <= at
        for t, s in shown
        if t == latest
    )


def _states_unreleased_check(text: str, needle: str, token_re, steps: dict, at) -> bool:
    """Whether `text` (casefolded) states a check item's answer that was not
    released at `at`: each keyed mention by its own item, a bare one by
    `_bare_mention_released`; an unknown key, or an unknown time, fails closed."""
    tokens = token_re.findall(text)
    cutoffs = _check_cutoffs(steps)
    for token in tokens:
        cutoff = cutoffs.get(token)
        if cutoff is None or at is None or at < cutoff:
            return True
    bare = text.count(needle) > len(tokens)
    return bare and not _bare_mention_released(steps, at)


def learn_loop_activity_findings(
    sessions: list[dict],
    evidence_keys: set[tuple[str, str]],
    step_event_keys: set[tuple[str, str]],
    messages: list[dict],
    sentinel: str,
    expect_activity: bool,
    prequestion_sentinel: str | None = None,
) -> list[Finding]:
    """`sessions`: {id, user_id, loop_state} of every loop session; the key
    sets are (session_id, question_hash) — the session that wrote the evidence
    row / emitted the check-phase zpd.step (Z47: never the user, or one
    session's rows would vouch for another's lost ones); `messages`:
    {session_id, at (epoch s), content (PLAINTEXT)} — the assistant rows of
    those sessions."""
    findings: list[Finding] = []
    no_evidence, no_step, graded_any = [], [], False
    session_steps: dict[str, dict] = {}
    pq_release: dict[str, dict[str, float | None]] = {}
    for s in sessions:
        steps = _steps_of(s)
        session_steps[s["id"]] = steps
        pq_release[s["id"]] = _prequestion_cutoffs(_prequestions_of(s))
        for qh, step in sorted(steps.items()):
            if step.get("graded_at") is None:
                continue
            graded_any = True
            if (s["id"], qh) not in evidence_keys:
                no_evidence.append([s["id"], qh])
            if step.get("feedback_given") and (s["id"], qh) not in step_event_keys:
                no_step.append([s["id"], qh])
    if no_evidence:
        findings.append(
            Finding(
                oracle="learn_loop",
                summary=(
                    f"{len(no_evidence)} graded check step(s) have no evidence row of "
                    "their session for their question_hash — the grade never reached "
                    "apply_graph_update?"
                ),
                evidence={"sample": no_evidence[:_SAMPLE]},
            )
        )
    if no_step:
        findings.append(
            Finding(
                oracle="learn_loop",
                summary=f"{len(no_step)} served feedback turn(s) have no zpd.step event of their session",
                evidence={"sample": no_step[:_SAMPLE]},
            )
        )
    needle = sentinel.casefold()
    check_token = re.compile(re.escape(needle) + r" ([a-z0-9_-]+-d\d+)")
    pq_token = re.compile(re.escape(prequestion_sentinel.casefold()) + r" ([a-z0-9-]+-pq\d+)") if (
        prequestion_sentinel
    ) else None
    leaked: dict[str, list[str]] = {"the seeded final answer": [], "a seeded prequestion's answer": []}
    unreadable: list[str] = []
    for m in messages:
        sid = m.get("session_id")
        if m.get("undecryptable"):
            # D7: a row the oracle cannot read is never judged as empty text
            unreadable.append(sid)
            continue
        text, at = str(m.get("content") or "").casefold(), _number(m.get("at"))
        if sid in session_steps and needle in text:
            if _states_unreleased_check(text, needle, check_token, session_steps[sid], at):
                leaked["the seeded final answer"].append(sid)
        if pq_token is not None and sid in pq_release and prequestion_sentinel.casefold() in text:
            # each item's key by its OWN record; a bare or unknown one fails closed
            tokens = pq_token.findall(text) or [None]
            for token in tokens:
                cutoff = pq_release[sid].get(token) if token else None
                if cutoff is None or at is None or at < cutoff:
                    leaked["a seeded prequestion's answer"].append(sid)
                    break
    if unreadable:
        findings.append(
            Finding(
                oracle="learn_loop",
                summary=(
                    f"{len(unreadable)} assistant message(s) of loop sessions could not be "
                    "decrypted — the final-answer leak check cannot read them"
                ),
                evidence={"sessions": sorted({str(s) for s in unreadable})[:_SAMPLE]},
            )
        )
    for what, sids in leaked.items():
        if sids:
            findings.append(
                Finding(
                    oracle="learn_loop",
                    summary=f"{len(sids)} assistant message(s) state {what} before the session released it",
                    evidence={"sessions": sorted(set(sids))[:_SAMPLE]},
                )
            )
    if expect_activity:
        # Z50: the students who have a loop session, never a settings column
        if not {s.get("user_id") for s in sessions} - {None, ""}:
            findings.append(
                Finding(
                    oracle="learn_loop", summary="expected loop activity but no loop users exist"
                )
            )
        if not graded_any:
            findings.append(
                Finding(
                    oracle="learn_loop",
                    summary="expected loop activity but no graded check step exists — vacuous pass",
                    evidence={"sessions": len(sessions)},
                )
            )
    return findings
