"""Spec §13 A134: the strict genuine-attempt gate (flag `help_gate_strict`).

The gap (the wave-2 gap audit, #9, verified on the code first): an attempt
counted after the band's independent time since the item was POSED, so only
the first attempt paid it — in the develop band six distinct one-character
attempts climbed H1→H6 in 45 s + 5 × the 8 s dwell = 85 s. The strict rule
grounds an attempt in signals measured on the attempt: the band's independent
time alone with the LATEST help, and novelty (a token no counted attempt on
the item held; no paste of the stem) — never its length, never the item's key.

Pure tests on learning/gates.py; route tests on the shared hermetic harness of
tests/test_learn_loop_routes.py (no DB, no model). The flag-off pin replays the
scenario captured on the code before A134, byte for byte.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from learning import gates, params
from learning.ladder import Rung, intent
from tests import test_learn_loop_routes as routes
from tests.split_patches import patch_loop

gate_on, no_rate_limit, seams = routes.gate_on, routes.no_rate_limit, routes.seams
client, T0 = routes.client, routes.T0
ATTEMPT, HINT = "/api/learn/loop/step/attempt", "/api/learn/loop/hint"
#: six distinct one-character attempts (none is a token of ITEM's stem)
ONE_CHAR = "qwerty"


def _digest(value: str) -> str:
    return f"d:{value}"


def _novel(text, *, stem=None, seen=()):
    return gates.attempt_novelty(text, stem=stem, seen=seen, digest=_digest)


# ── pure: the strict rule ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "band,variant,required",
    [
        ("develop", "A", params.GATE_INDEPENDENT_MIN_S),
        ("profic", "A", params.GATE_INDEPENDENT_MIN_S),
        ("novice", "A", params.GATE_INDEPENDENT_MIN_S_NOVICE),
        ("develop", "B", params.GATE_INDEPENDENT_MIN_S_VARIANT_B),
        ("novice", "B", params.GATE_INDEPENDENT_MIN_S_NOVICE),
    ],
)
def test_the_strict_rule_asks_the_bands_independent_time_alone_with_the_latest_help(
    band, variant, required
):
    """No new threshold: the §3.3 independent-time gate (PKG-14's variant B
    included), asked of the time since the latest help instead of the pose."""
    assert gates.independent_time_required(band, variant=variant) == required
    ok = dict(genuine=True, novel=True, band=band, variant=variant)
    assert gates.strict_genuine_attempt(alone_seconds=required, **ok) is True
    assert gates.strict_genuine_attempt(alone_seconds=required - 0.001, **ok) is False


def test_the_strict_rule_needs_the_standard_verdict_and_novelty_and_scales_with_a5():
    assert gates.strict_genuine_attempt(False, 600.0, True, "develop") is False  # a plea, the screen
    assert gates.strict_genuine_attempt(True, 600.0, False, "develop") is False  # nothing new
    assert gates.strict_genuine_attempt(True, 600.0, True, "develop") is True
    # A5's lane scale applies to it as to every GATE_* constant
    assert gates.strict_genuine_attempt(True, 0.45, True, "develop", time_scale=0.01) is True
    assert gates.strict_genuine_attempt(True, 0.44, True, "develop", time_scale=0.01) is False
    with pytest.raises(ValueError):
        gates.strict_genuine_attempt(True, float("nan"), True, "develop")
    with pytest.raises(ValueError):
        gates.strict_genuine_attempt(True, 600.0, True, "expert")


def test_novelty_is_a_token_no_counted_attempt_held():
    first, digests = _novel("separate chaining")
    assert first is True and digests == {"d:separate", "d:chaining"}
    seen = digests
    assert _novel("chaining separate", seen=seen)[0] is False  # reordered: nothing new
    assert _novel("chaining", seen=seen)[0] is False  # a subset: nothing new
    assert _novel("Separate   CHAINING!", seen=seen)[0] is False  # spacing, case, punctuation
    assert _novel("separate chaining with lists", seen=seen)[0] is True
    assert _novel("q")[0] is True and _novel("w", seen={"d:q"})[0] is True  # a new letter is new


def test_novelty_ignores_what_a_hedge_sets_aside_and_look_alike_letters():
    """A120's content (attempt_content) is what is compared: a plea added to a
    repeat says nothing new; the A33 fold maps a look-alike to its letter."""
    _, seen = _novel("separate chaining")
    assert _novel("separate chaining, not sure though", seen=seen)[0] is False
    assert _novel("idk", seen=seen)[0] is False  # a plea alone holds no token
    assert _novel("ѕeparate chaining", seen=seen)[0] is False  # Cyrillic ѕ
    assert _novel("?!...", seen=())[0] is False  # punctuation is no answer token


def test_a_paste_of_the_stem_is_no_attempt_but_an_answer_in_it_is():
    stem = routes.ITEM.prompt  # "What stops factorial(0) from recursing?"
    assert gates.pastes_stem(stem, stem) is True
    assert _novel(stem, stem=stem)[0] is False
    assert _novel(f"{stem} the base case", stem=stem)[0] is True  # quoted, with an answer
    choice = "Which is larger in this question, 3 or 5?"
    assert gates.pastes_stem("5", choice) is False and _novel("5", stem=choice)[0] is True
    # a stem shorter than LEAK_PROVENANCE_MIN_TOKENS is never quoted (A125's rule)
    assert gates.pastes_stem("Why?", "Why?") is False


def test_the_digests_are_the_callers_keyed_hashes_never_the_tokens():
    seen_calls: list[str] = []

    def keyed(value: str) -> str:
        seen_calls.append(value)
        return "x" * 12

    _, digests = gates.attempt_novelty("the base case", stem=None, seen=(), digest=keyed)
    assert digests == {"x" * 12} and sorted(seen_calls) == ["base", "case", "the"]


# ── route: the scenario before / after ───────────────────────────────────────


def _scenario(seams, plan, *, strict: bool):
    """POST /step/attempt then /hint at each (seconds after the pose, text) of
    `plan`, the way LoopLearn's Hint button does; the route clock moves."""
    clock = {"t": T0}
    out = []
    with (
        patch_loop("_now_s", side_effect=lambda: clock["t"]),
        patch_loop("_help_gate_strict_on", return_value=strict),
        patch_loop("record_help") as ledger,
    ):
        for at, text in plan:
            clock["t"] = T0 + at
            body = {"session_id": "s1", "user_id": "u1", "question_hash": "qh-1"}
            a = client.post(ATTEMPT, json={**body, "attempt_text": text}).json()
            h = client.post(HINT, json=body).json()
            out.append((at, a, h))
    return out, ledger


def _fresh(seams, **fields):
    """qh-1 posed at T0 with no help yet (`fields` override)."""
    base = {"rung": 0, "attempts": 0, "attempted_at": [], "first_shown_at": T0}
    seams.store["doc"] = routes._state(**{**base, **fields})


#: The develop-band scenario: six distinct one-character attempts, each with a
#: Hint, every GATE_RUNG_DWELL_MIN_S after the first at GATE_INDEPENDENT_MIN_S.
SPAM = [
    (params.GATE_INDEPENDENT_MIN_S + params.GATE_RUNG_DWELL_MIN_S * i, ch)
    for i, ch in enumerate(ONE_CHAR)
]

#: Captured on the code BEFORE A134 (f012ff03, the same harness): the step the
#: scenario leaves. The flag-off run must leave exactly this, plus A134's
#: `attempt_tokens` memory.
BASELINE_ENTRY = {
    "attempt_hashes": [
        "8e35c2cd3bf6641b", "50e721e49c013f00", "3f79bb7b435b0532",
        "454349e422f05297", "e3b98a4da31a127d", "a1fce4363854ff88",
    ],
    "attempted_at": [T0 + 45, T0 + 53, T0 + 61, T0 + 69, T0 + 77, T0 + 85],
    "attempts": 6,
    "check_item_id": "item-1",
    "exam_mode": False,
    "feedback_given": False,
    "first_shown_at": T0,
    "last_rung_at": T0 + 85,
    "node_id": "node-1",
    "rung": 6,
    "rungs": [{"at": T0 + t, "rung": r} for r, t in zip(range(1, 7), (45, 53, 61, 69, 77, 85))],
    "showed_work": False,
    "taught": True,
}


def test_before_six_one_character_attempts_reach_the_full_solution_in_85_seconds(gate_on, seams):
    """The gap, as it stands with the flag off (the §3.3 rule, unchanged): H6
    at 45 s + 5 × 8 s. Every response and every step key the §3.3 rule writes
    is the pre-A134 code's, byte for byte."""
    _fresh(seams)
    out, ledger = _scenario(seams, SPAM, strict=False)
    assert [h for _, _, h in out] == [{"rung": r, "intent": intent(Rung(r))} for r in range(1, 7)]
    assert [a for _, a, _ in out] == [
        {"genuine": True, "counted": True, "attempts": k, "independent_s": float(at)}
        for k, (at, _) in enumerate(SPAM, start=1)
    ]
    assert out[-1][0] == 85
    entry = dict(seams.store["doc"]["steps"]["qh-1"])
    tokens = entry.pop("attempt_tokens")
    assert entry == BASELINE_ENTRY
    assert len(tokens) == 6 and all(len(t) == 12 for t in tokens)  # keyed digests only
    assert [c.args[2] for c in ledger.call_args_list] == [1, 2, 3, 4, 5, 6]


def test_after_the_strict_gate_holds_the_same_attempts_at_h1(gate_on, seams):
    """Flag on, the same six attempts: the first comes after 45 s alone and
    counts (H1); each later one comes 8 s after the last hint, so it does not
    count and /hint says to stay with the step longer. No rung past H1 in the
    85 s, and nothing more in the help ledger."""
    _fresh(seams)
    out, ledger = _scenario(seams, SPAM, strict=True)
    assert out[0][1] == {"genuine": True, "counted": True, "attempts": 1, "independent_s": 45.0}
    assert out[0][2] == {"rung": 1, "intent": intent(Rung.H1)}
    for at, a, h in out[1:]:
        assert a == {"genuine": False, "counted": False, "attempts": 1, "independent_s": float(at)}
        assert h == {"denied": "dwell"}
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert entry["rung"] == 1 and entry["attempts"] == 1 and len(entry["attempt_tokens"]) == 1
    assert [c.args[2] for c in ledger.call_args_list] == [1]


def test_the_attempt_events_record_each_attempts_signals_under_either_rule(gate_on, seams):
    """zpd.attempt (A133): one per attempt, its signals — never its text. Flag
    off, attempts 2-6 counted by the §3.3 rule are ones the strict rule would
    not count (8 s alone): that is the counterfactual the report reads."""
    _fresh(seams)
    _scenario(seams, SPAM, strict=False)
    calls = [c.kwargs for c in seams.zpd.emit_zpd_attempt.call_args_list]
    assert len(calls) == 6
    first, *rest = calls
    assert first == {
        "user_id": "u1", "request_id": first["request_id"], "session_id": "s1",
        "question_hash": "qh-1", "concept_id": "node-1", "band": "develop", "gate": "standard",
        "rung": Rung.H0, "since_pose_ms": 45_000, "alone_ms": 45_000, "gate_ms": 45_000,
        "novel": True, "standard": True, "strict": True, "counted": True,
    }
    for k, call in enumerate(rest, start=1):
        assert call["rung"] == Rung(k) and call["alone_ms"] == params.GATE_RUNG_DWELL_MIN_S * 1000
        assert (call["standard"], call["strict"], call["counted"]) == (True, False, True)
    assert not any(v in set(ONE_CHAR) for c in calls for v in c.values() if isinstance(v, str))


def test_after_the_events_say_the_strict_gate_judged_and_refused(gate_on, seams):
    _fresh(seams)
    _scenario(seams, SPAM, strict=True)
    calls = [c.kwargs for c in seams.zpd.emit_zpd_attempt.call_args_list]
    assert {c["gate"] for c in calls} == {"strict"}
    assert [(c["standard"], c["strict"], c["counted"]) for c in calls] == [(True, True, True)] + [
        (True, False, False)
    ] * 5


def test_a_patient_one_character_attempt_per_independent_time_reaches_h6_at_270_seconds(
    gate_on, seams
):
    """What the strict gate does with the same characters spaced out: every
    rung costs the band's independent time alone with the latest hint, so the
    bottom-out moves from 85 s to 6 × 45 s, each hint on screen 45 s. A lone
    character's meaning is not judged — that needs the item's key (an oracle)
    or a length rule (excluded); the A133 report's next-opportunity outcome is
    where the substitution would show (spec §13 A134)."""
    _fresh(seams)
    patient = [(params.GATE_INDEPENDENT_MIN_S * (i + 1), ch) for i, ch in enumerate(ONE_CHAR)]
    out, _ = _scenario(seams, patient, strict=True)
    assert [h for _, _, h in out] == [{"rung": r, "intent": intent(Rung(r))} for r in range(1, 7)]
    assert out[-1][0] == 270


def test_strict_a_repeat_or_a_reordering_never_counts(gate_on, seams):
    _fresh(seams)
    t = params.GATE_INDEPENDENT_MIN_S
    out, _ = _scenario(
        seams,
        [(t, "separate chaining"), (2 * t, "chaining separate"), (3 * t, "separate chaining")],
        strict=True,
    )
    assert out[0][2]["rung"] == 1
    assert [a["counted"] for _, a, _ in out[1:]] == [False, False]
    assert [h for _, _, h in out[1:]] == [{"denied": "no_genuine_attempt"}] * 2  # time is not the issue
    # the §3.3 rule counts the reordering (another digest): the strict rule's novelty is the change
    _fresh(seams)
    out, _ = _scenario(seams, [(t, "separate chaining"), (2 * t, "chaining separate")], strict=False)
    assert out[1][1]["counted"] is True and out[1][2]["rung"] == 2


def test_strict_a_pasted_stem_is_no_attempt_but_a_stem_with_an_answer_is(gate_on, seams):
    _fresh(seams)
    t = params.GATE_INDEPENDENT_MIN_S
    stem = routes.ITEM.prompt
    out, _ = _scenario(seams, [(t, stem), (t + 1, f"{stem} the base case")], strict=True)
    assert out[0][1]["counted"] is False and out[0][2] == {"denied": "no_genuine_attempt"}
    assert out[1][1]["counted"] is True and out[1][2]["rung"] == 1


def test_strict_keeps_a120s_hedge_tolerance_and_a_plea_alone_still_fails(gate_on, seams):
    seams.store["doc"] = routes._state()  # rung 1 at the pose, ten minutes alone
    out, _ = _scenario(seams, [(600, routes._HEDGED_PARTIAL)], strict=True)
    assert out[0][1]["counted"] is True and out[0][2] == {"rung": 2, "intent": intent(Rung.H2)}
    seams.store["doc"] = routes._state()
    out, _ = _scenario(seams, [(600, "I'm not sure, can I have a hint?")], strict=True)
    assert out[0][1]["genuine"] is False and out[0][2] == {"denied": "no_genuine_attempt"}


def test_strict_keeps_the_novice_worked_example_first_then_h5_after_time_alone(gate_on, seams):
    """A122 intact: the worked example (H4) comes first with no attempt; H5
    needs an attempt after the novice gate (90 s) alone with the example."""
    seams.p_known["node-1"] = 0.1  # novice
    seams.prereq.return_value = False  # prerequisite not known → worked example first
    _fresh(seams, worked_first=True)
    clock = {"t": T0 + 1}
    body = {"session_id": "s1", "user_id": "u1", "question_hash": "qh-1"}
    with (
        patch_loop("_now_s", side_effect=lambda: clock["t"]),
        patch_loop("_help_gate_strict_on", return_value=True),
    ):
        assert client.post(HINT, json=body).json() == {"rung": 4, "intent": intent(Rung.H4)}
        clock["t"] = T0 + 1 + 50
        assert client.post(ATTEMPT, json={**body, "attempt_text": "n == 0"}).json()["counted"] is False
        assert client.post(HINT, json=body).json() == {"denied": "dwell"}
        clock["t"] = T0 + 1 + params.GATE_INDEPENDENT_MIN_S_NOVICE
        assert client.post(ATTEMPT, json={**body, "attempt_text": "n == 0"}).json()["counted"] is True
        assert client.post(HINT, json=body).json() == {"rung": 5, "intent": intent(Rung.H5)}


def test_strict_a_rung_granted_meanwhile_is_seen_on_the_fresh_document(gate_on, seams):
    """The compare-and-set re-runs the count on the fresh document: a hint
    granted between the read and the write moved the latest help to now, so
    the attempt has had no time alone with it and does not count."""
    _fresh(seams)

    def granted_meanwhile(doc):
        doc["steps"]["qh-1"].update(rung=1, last_rung_at=routes.NOW, rungs=[{"rung": 1, "at": routes.NOW}])

    seams.store["conflicts"], seams.store["racer"] = 1, granted_meanwhile
    with patch_loop("_help_gate_strict_on", return_value=True):
        r = client.post(ATTEMPT, json=routes._attempt(attempt_text="the base case"))
    assert r.json()["counted"] is False
    assert seams.store["doc"]["steps"]["qh-1"]["attempts"] == 0


def test_strict_the_help_floor_and_the_evidence_rung_read_as_before(gate_on, seams):
    """A93 unchanged: the grade carries the max of the step's rung and the
    ledger's floor (re-read inside the claim); the strict gate moves only how
    far the step's own rung climbed (here H1: the scenario's step after it)."""
    written: list = []
    seams.flush.side_effect = lambda deps, course: written.append([dict(e) for e in deps.pending_evidence]) or []
    for floor, expected in ((0, 1), (params.RUNG_NO_CREDIT_MIN, params.RUNG_NO_CREDIT_MIN)):
        written.clear()
        _fresh(seams, rung=1, attempts=1, attempted_at=[T0 + 45], last_rung_at=T0 + 45)
        agent_p, usage_p, _ = routes._feedback_agent()
        with (
            agent_p,
            usage_p,
            patch_loop("_help_gate_strict_on", return_value=True),
            patch_loop("_reveal_floor", return_value=floor),
            patch_loop("mark_graded"),
        ):
            r = client.post("/api/learn/loop/check/answer", json=routes._answer(answer="n == 0 returns 1"))
        assert r.status_code == 200, r.text
        ((ev,),) = written
        assert ev["max_rung"] == expected and ev["assisted"] is True


def test_the_attempt_text_is_never_stored_and_the_digests_are_keyed(gate_on, seams):
    _fresh(seams)
    _scenario(seams, [(params.GATE_INDEPENDENT_MIN_S, "factorial base case returns one")], strict=True)
    doc = json.dumps(seams.store["doc"])
    for word in ("base", "case", "returns", "one"):
        assert f'"{word}"' not in doc and word not in seams.store["doc"]["steps"]["qh-1"]["attempt_tokens"]
    from services.loop.attempts import _token_digest

    tokens = seams.store["doc"]["steps"]["qh-1"]["attempt_tokens"]
    assert _token_digest("qh-1", "base") in tokens
    assert _token_digest("qh-2", "base") != _token_digest("qh-1", "base")  # per item


def test_the_novelty_memory_is_bounded_and_errs_toward_counting(gate_on, seams):
    entry: dict = {"attempt_tokens": [f"{i:012x}" for i in range(params.HELP_NOVELTY_DIGESTS_MAX)]}
    from services.loop.attempts import _remember_attempt_tokens

    _remember_attempt_tokens(entry, frozenset({"ffffffffffff"}))
    assert len(entry["attempt_tokens"]) == params.HELP_NOVELTY_DIGESTS_MAX
    assert "ffffffffffff" not in entry["attempt_tokens"]
    # what was not kept reads as new: the check errs toward counting (time still binds)
    novel, _ = gates.attempt_novelty("x", stem=None, seen=entry["attempt_tokens"], digest=lambda v: "ffffffffffff")
    assert novel is True


def test_flag_off_hint_reads_nothing_more_than_before(gate_on, seams):
    """Off, /hint's denial is _rung_gate_denial's: the strict wording reads
    the item and the band only when the flag is on."""
    seams.store["doc"] = routes._state(attempted_at=[])
    with patch_loop("_help_gate_strict_on", return_value=False) as flag:
        assert client.post(HINT, json=routes._hint()).json() == {"denied": "no_genuine_attempt"}
    flag.assert_called_once_with("u1")
    seams.item.assert_not_called()


# ── the flag ─────────────────────────────────────────────────────────────────


def test_the_flag_is_server_only_off_first_and_off_when_unconfigured(monkeypatch):
    from services import feature_flags as ff

    monkeypatch.delenv("SAPLING_FLAG_HELP_GATE_STRICT", raising=False)
    fd = ff.REGISTRY["help_gate_strict"]
    assert fd.variants == ("off", "on") and not fd.client_visible
    from services.loop.flags import HELP_GATE_STRICT_FLAG, _help_gate_strict_on

    assert HELP_GATE_STRICT_FLAG == "help_gate_strict"
    with patch("services.feature_flags.read_config", return_value=ff.Snapshot(flags={}, targets={})):
        ff.clear_feature_flags_cache()
        assert _help_gate_strict_on("u1") is False
    assert _help_gate_strict_on(None) is False and _help_gate_strict_on("") is False


def test_the_flag_resolves_per_student(monkeypatch):
    from services import feature_flags as ff
    from services.loop.flags import _help_gate_strict_on

    snap = ff.Snapshot(
        flags={"help_gate_strict": {"key": "help_gate_strict", "default_variant": "off",
                                    "rollout_percent": 0, "rollout_variant": None}},
        targets={"help_gate_strict": [{"flag_key": "help_gate_strict", "target_type": "user",
                                       "target_id": "u-on", "variant": "on"}]},
    )
    with patch("services.feature_flags.read_config", return_value=snap):
        ff.clear_feature_flags_cache()
        assert _help_gate_strict_on("u-on") is True
        assert _help_gate_strict_on("u-off") is False


# ── the event ────────────────────────────────────────────────────────────────


def test_emit_zpd_attempt_sends_ids_counts_enums_and_bools_only(monkeypatch):
    from learning import zpd_events
    from services.events_service import EVENT_TAXONOMY

    calls: list = []
    monkeypatch.setattr(zpd_events, "log_event", lambda et, **kw: calls.append((et, kw)))
    zpd_events.emit_zpd_attempt(
        user_id="u1", request_id="r1", session_id="s1", question_hash="q" * 64, concept_id=None,
        band="develop", gate="strict", rung=Rung.H2, since_pose_ms=90_000, alone_ms=45_000,
        gate_ms=45_000, novel=True, standard=True, strict=True, counted=True,
    )
    ((et, kw),) = calls
    assert et == "zpd.attempt" and et in EVENT_TAXONOMY and kw["category"] == "usage"
    assert kw["payload"] == {
        "session_id": "s1", "question_hash": "q" * 64, "band": "develop", "gate": "strict",
        "rung": 2, "since_pose_ms": 90_000, "alone_ms": 45_000, "gate_ms": 45_000,
        "novel": True, "standard": True, "strict": True, "counted": True,
    }  # concept_id omitted when unknown, never blanked
