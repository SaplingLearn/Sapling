"""Spec §13 A125: the integrity guard of the AI surfaces OUTSIDE the learning loop.

The loop scans every tutor turn it serves against the student's posed items
(A88/A93), but nothing else knew them: a student could paste an open check into
the notes chat, get its answer, then submit it for full unassisted credit.
services/integrity_guard.py now runs around every student-facing surface that
sends a model text the student typed or pasted (the notes chat, summary and
concepts; the flashcard generators):

- before the model call, text quoting one of the student's OWN posed items'
  stems (learning/stem_match.py — answer_guard's fold, A34 tokens, leak.py's
  stem rule; no model call) gets the deterministic integrity response, no model
  run, and a help row that floors the item's later grade (A93);
- after it, the served-text scan (learning/served_scan.py) withholds text that
  states a posed item's key, with the same help row;
- one bounded read of the posed items per request serves both;
- the event is learn.outside_leak (never zpd.leak / zpd.reveal).

No model runs here: every agent is a stub (owner instruction for A125)."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from learning import params, stem_match
from learning.checks import CheckItem, RubricItem, WrongReason
from learning.stem_match import StemSet
from main import app
from services import integrity_guard
from services.integrity_guard import (
    REFUSED_DETAIL,
    REFUSED_REPLY,
    WITHHELD_DETAIL,
    WITHHELD_REPLY,
    open_guard,
)
from tests import test_learn_loop_routes as _routes
from tests.test_learning_help_ledger import _grade_appends
from tests.test_notes_routes import fake_get_note
from tests.split_patches import patch_loop
import services.loop.reveals

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

client = TestClient(app)
POSED = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
ITEM = _routes.ITEM  # qh-1: "What stops factorial(0) from recursing?" → "The base case returns 1"
OTHER = CheckItem(
    id="item-other",
    course_id="c1",
    concept_key="stacks",
    format="free",
    difficulty=2,
    prompt="Which data structure keeps one frame for every active call?",
    reference_answer="Each active call keeps a frame on the call stack until it returns.",
    final_answer="the call stack",
    canonical_answer=None,
    rubric=[RubricItem(id="r1", text="a"), RubricItem(id="r2", text="b")],
    common_wrong=[WrongReason(key="w", text="wrong")],
    source_chunk_ids=["ch"],
    stepwise=False,
    question_hash="qh-other",
)
PASTE = f"Can you answer this one for me? {ITEM.prompt}"
LEAKING_REPLY = "Sure: the base case returns 1, so the recursion stops there."


def _item(qh: str, prompt: str, final: str = "x") -> SimpleNamespace:
    return SimpleNamespace(question_hash=qh, prompt=prompt, final_answer=final)


@pytest.fixture
def posed():
    """Each student's posed-and-ungraded items at the guard's one read seam
    (`services.loop.posed.posed_items`): u1 has ITEM, u2 has OTHER."""
    world = {"u1": [(ITEM, POSED)], "u2": [(OTHER, POSED)]}

    def read(user_id, *, now):
        return list(world.get(user_id, [])), None

    with patch("services.loop.posed.posed_items", side_effect=read) as reader:
        reader.world = world
        yield reader


@pytest.fixture
def records():
    """The guard's three writes: help rows, 'unscanned' markers, the event."""
    with (
        patch("services.integrity_guard.record_help") as help_row,
        patch("services.integrity_guard.record_unscanned") as marker,
        patch("learning.zpd_events.emit_outside_leak") as event,
    ):
        yield SimpleNamespace(help=help_row, unscanned=marker, event=event)


def _note_chat(
    message: str, *, body: str = "B", user: str = "u1", reply: str = "Here is a quick answer."
):
    run = AsyncMock(return_value=SimpleNamespace(output=reply))
    with (
        patch("routes.notes.note_chat_agent.run", run),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.get_note", side_effect=fake_get_note(body=body)),
    ):
        r = client.post("/api/notes/n1/chat", json={"user_id": user, "message": message})
    return r, run


# ── the stem match (learning/stem_match.py, pure) ────────────────────────────


def test_a_pasted_stem_is_quoted_however_it_is_wrapped_or_punctuated():
    stems = StemSet.build([ITEM, OTHER])
    assert stems.quoted(ITEM.prompt) == ["qh-1"]
    assert stems.quoted(PASTE) == ["qh-1"]
    assert stems.quoted("what stops factorial ( 0 ) from recursing\n\nthanks!!") == ["qh-1"]
    assert stems.quoted(f"{ITEM.prompt} and also {OTHER.prompt}") == ["qh-1", "qh-other"]


def test_look_alike_letters_zero_width_and_letter_spacing_do_not_hide_a_paste():
    """answer_guard's detection fold: Cyrillic а/о, a zero-width space, a
    letter-spaced word — the stem still reads as pasted."""
    disguised = "Whаt stоps fact​orial(0) from recursing?"
    assert StemSet.build([ITEM]).quoted(disguised) == ["qh-1"]
    assert StemSet.build([ITEM]).quoted("W h a t   stops factorial(0) from recursing") == ["qh-1"]


def test_inflected_words_still_quote_the_stem():
    """leak.py's strict-mode stem rule: "stop"/"stops", "recursion"/"recursing"."""
    assert StemSet.build([ITEM]).quoted("what stop factorial 0 from recursion") == ["qh-1"]


def test_a_shared_opening_or_a_paraphrase_is_not_a_quote():
    mc = _item(
        "qh-mc", "Which of the following best describes the role of the base case in recursion?"
    )
    short = _item("qh-tail", "What is tail recursion?")
    stems = StemSet.build([ITEM, mc, short])
    assert (
        stems.quoted("Which of the following best describes the difference between TCP and UDP?")
        == []
    )
    assert stems.quoted("Why does a recursive function need a base case at all?") == []
    assert stems.quoted("What is tail call optimization?") == []  # a short stem needs all of it
    assert stems.quoted("explain: what is tail recursion") == ["qh-tail"]


def test_the_quote_threshold_is_the_share_and_never_fewer_than_leak_ngram_tokens():
    """A stem of 12 tokens: INTEGRITY_STEM_MIN_SHARE of it (8) must be covered —
    7 consecutive stem tokens are not a quote, 8 are. A stem of 7: LEAK_NGRAM (6)
    of it, never the share's 5."""
    # twelve distinct one-token words, no two of one lemma
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()
    long = _item("qh-12", " ".join(words))
    need = max(math.ceil(params.INTEGRITY_STEM_MIN_SHARE * 12), params.LEAK_NGRAM)
    assert need == 8
    stems = StemSet.build([long])
    assert stems.quoted(" ".join(words[:need])) == ["qh-12"]
    assert stems.quoted(" ".join(words[: need - 1])) == []
    seven = _item("qh-7", " ".join(words[:7]))
    assert StemSet.build([seven]).quoted(" ".join(words[:6])) == ["qh-7"]
    assert StemSet.build([seven]).quoted(" ".join(words[:5])) == []


def test_a_stem_under_three_tokens_is_never_quoted():
    assert StemSet.build([_item("qh-2", "Define recursion.")]).entries == []
    assert StemSet.build([_item("qh-2", "Define recursion.")]).quoted("Define recursion.") == []


# ── the guard (services/integrity_guard.py) ──────────────────────────────────


def test_the_guard_is_inert_with_the_loop_off(posed, records):
    """The kill switch (§11.6): no read, no refusal, nothing withheld or written."""
    guard = open_guard("u1", surface="note_chat", texts=[PASTE], active=False)
    assert not guard.refused
    assert guard.screen(LEAKING_REPLY) is True
    assert guard.screen_each([LEAKING_REPLY, "x"]) == [True, True]
    posed.assert_not_called()
    records.help.assert_not_called()
    records.unscanned.assert_not_called()
    records.event.assert_not_called()


def test_a_quoted_item_is_refused_with_a_help_row_and_one_request_event(posed, records):
    guard = open_guard("u1", surface="note_chat", texts=[PASTE], active=True, request_id="rq")
    assert guard.refused and guard.quoted == ["qh-1"]
    records.help.assert_called_once_with("u1", "qh-1", params.INTEGRITY_HELP_RUNG, source="outside")
    assert params.INTEGRITY_HELP_RUNG >= params.RUNG_NO_CREDIT_MIN  # no unassisted credit later
    records.event.assert_called_once_with(
        user_id="u1",
        request_id="rq",
        surface="note_chat",
        stage="request",
        question_hashes=["qh-1"],
        help_recorded=True,
    )
    records.unscanned.assert_not_called()  # nothing was served


def test_a_failed_help_write_still_refuses(posed, records, caplog):
    records.help.side_effect = RuntimeError("pg down")
    guard = open_guard("u1", surface="note_chat", texts=[PASTE], active=True)
    assert guard.refused  # the accepted DB-down rule: the refusal stands
    assert records.event.call_args.kwargs["help_recorded"] is False
    assert "not recorded" in caplog.text


def test_the_reply_scan_withholds_a_stated_key_with_a_help_row(posed, records):
    guard = open_guard(
        "u1", surface="note_chat", texts=["How do I study for the midterm?"], active=True
    )
    assert not guard.refused
    assert guard.screen(LEAKING_REPLY) is False
    records.help.assert_called_once_with("u1", "qh-1", params.INTEGRITY_HELP_RUNG, source="outside")
    assert records.event.call_args.kwargs["stage"] == "reply"
    assert guard.screen("Spread your revision over a week.") is True


def test_restating_the_students_own_words_is_not_withheld(posed, records):
    """Served mode's provenance rule: a run copied from what the student wrote
    (and reaching past the key) reveals nothing they do not already have."""
    note = "My note: the base case returns 1 when n equals 0, which ends the recursion."
    guard = open_guard("u1", surface="note_summary", texts=[note], active=True)
    assert guard.screen("The note says the base case returns 1 when n equals 0.") is True
    records.help.assert_not_called()


def test_unreadable_posed_items_serve_under_one_unscanned_marker(records):
    with patch("services.loop.posed.posed_items", return_value=None):
        guard = open_guard("u1", surface="note_chat", texts=[PASTE], active=True)
        assert not guard.refused and guard.unreadable
        assert guard.screen(LEAKING_REPLY) is True
        assert guard.screen("again") is True
    (call,) = records.unscanned.call_args_list  # once per request
    assert call.args == ("u1",) and call.kwargs["session_id"] is None
    assert call.kwargs["source"] == "outside:note_chat"
    assert records.event.call_args.kwargs["stage"] == "unscanned"
    records.help.assert_not_called()


def test_items_beyond_the_window_mark_the_edge_only_when_text_is_served(records):
    edge = datetime(2026, 11, 1, tzinfo=timezone.utc)
    with patch("services.loop.posed.posed_items", return_value=([(ITEM, POSED)], edge)):
        guard = open_guard("u1", surface="flashcards", texts=["topic"], active=True)
        assert guard.screen_each([LEAKING_REPLY]) == [False]
        records.unscanned.assert_not_called()  # nothing was served
        assert guard.screen("A clean card.") is True
    assert records.unscanned.call_args.kwargs["at"] == edge
    assert all(c.kwargs["stage"] != "unscanned" for c in records.event.call_args_list)


def test_the_event_payload_is_hashes_and_enums_only():
    from learning import zpd_events
    from services.events_service import EVENT_TAXONOMY

    with patch("learning.zpd_events.log_event") as log:
        zpd_events.emit_outside_leak(
            user_id="u1",
            request_id="rq",
            surface="note_chat",
            stage="reply",
            question_hashes=["b" * 64, "a" * 64],
            help_recorded=True,
        )
    (event_type,), kw = log.call_args
    assert event_type == "learn.outside_leak" and event_type in EVENT_TAXONOMY
    assert kw["category"] == "audit"
    assert kw["payload"] == {
        "surface": "note_chat",
        "stage": "reply",
        "question_hashes": ["a" * 64, "b" * 64],
        "count": 2,
        "help_recorded": True,
        "request_id": "rq",
    }
    # never zpd.leak (the §11.7 abort criterion) or zpd.reveal (the zero-leak gate)
    assert event_type not in {"zpd.leak", "zpd.reveal"}


@pytest.mark.parametrize("detail", [REFUSED_DETAIL, WITHHELD_DETAIL])
def test_the_409_details_are_toast_prose(detail):
    """frontend/src/lib/errorMessage.ts shows a server detail only when it is at
    most 160 characters with no brackets, angle brackets or line breaks."""
    import re

    assert len(detail) <= 160
    assert not re.search(r"[{}\[\]<>\n\r]", detail)
    assert "learning check" in detail and "counts as helped" in detail


def test_an_inactive_guard_loads_no_pkg06_module():
    """The inertness sanction (tests/test_learning_zpd_policy.py): the guard
    reaches the PKG-06 layer only on an ACTIVE guard. In a clean interpreter,
    importing it and running a whole inactive request (the kill switch) loads
    neither learning.leak nor learning.zpd_events."""
    import os
    import pathlib
    import subprocess
    import sys

    env = {
        k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "LEARNING_LOOP_ENABLED")
    }
    env.update(
        {
            "ENCRYPTION_KEY": "0" * 64,
            "APP_ENV": "test",
            "SUPABASE_URL": "https://dummy.supabase.co",
            "SUPABASE_SERVICE_KEY": "dummy-service-key",
            "SESSION_SECRET": "dummy-session-secret",
        }
    )
    program = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
        "import sys\n"
        "from services import integrity_guard as g\n"
        "guard = g.open_guard('u1', surface='note_chat', texts=['What stops factorial(0)?'], active=False)\n"
        "assert not guard.refused and guard.screen('The base case returns 1') is True\n"
        "assert guard.screen_each(['a', 'b'], own=guard.own_text) == [True, True]\n"
        "print('LOADED=' + ','.join(sorted(m for m in sys.modules if m in (\n"
        "    'learning.leak', 'learning.zpd_events', 'learning.served_scan', 'learning.stem_match',\n"
        "    'routes.learn_loop', 'services.loop.posed'))))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", program],
        cwd=pathlib.Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "LOADED=", proc.stdout


def test_the_notes_chat_agents_graph_writes_are_screened(posed, records):
    """The notes-chat agent can file concept nodes the student later reads in
    their graph (apply_graph_update_tool): with the request's guard on its deps,
    a name stating a posed check's key is dropped, the student's own words pass;
    with no guard (every other agent) nothing changes."""
    import asyncio

    from agents.deps import SaplingDeps
    from agents.tools.graph import GraphUpdateInput, apply_graph_update_tool

    guard = open_guard(
        "u2", surface="note_chat", texts=["My note: recursion uses frames."], active=True
    )
    applied: list = []

    def run(integrity):
        deps = SaplingDeps(
            user_id="u2", course_id="c1", supabase=None, request_id="", integrity=integrity
        )
        ctx = SimpleNamespace(deps=deps)
        update = GraphUpdateInput(concepts=["Recursion", "The Call Stack"])
        with patch(
            "agents.tools.graph.apply_graph_update", side_effect=lambda u, p, c: applied.append(p)
        ):
            return asyncio.run(apply_graph_update_tool(ctx, update))

    run(guard)
    filed = applied.pop()
    assert filed == {"new_nodes": [{"concept_name": "Recursion", "initial_mastery": 0.0}]}
    records.help.assert_called_once_with(
        "u2", "qh-other", params.INTEGRITY_HELP_RUNG, source="outside"
    )
    run(None)
    filed = applied.pop()
    assert [n["concept_name"] for n in filed["new_nodes"]] == [
        "Recursion",
        "The Call Stack",
    ]
    # the student's own words: their note names the call stack, so filing it adds nothing
    records.help.reset_mock()
    own = open_guard(
        "u2",
        surface="note_chat",
        texts=["Each call pushes a frame on the call stack."],
        active=True,
    )
    run(own)
    filed = applied.pop()
    assert [n["concept_name"] for n in filed["new_nodes"]] == [
        "Recursion",
        "The Call Stack",
    ]
    records.help.assert_not_called()


def test_the_ledger_source_and_surfaces_are_declared():
    from learning import help_ledger

    assert integrity_guard.SOURCE in help_ledger.SOURCES
    with pytest.raises(ValueError):
        open_guard("u1", surface="study_guide", texts=[], active=True)


# ── the notes chat (/api/notes/{id}/chat) ────────────────────────────────────


def test_pasting_an_open_check_into_notes_chat_is_refused_with_no_model_call(posed, records):
    r, run = _note_chat(PASTE)
    assert r.status_code == 200
    assert r.json() == {"reply": REFUSED_REPLY, "degraded": False, "integrity": "refused"}
    run.assert_not_called()
    records.help.assert_called_once_with("u1", "qh-1", params.INTEGRITY_HELP_RUNG, source="outside")
    assert records.event.call_args.kwargs["stage"] == "request"


def test_an_open_check_written_into_the_note_is_refused_too(posed, records):
    """The agent grounds every answer in the note (read_active_note): a check
    pasted into the note body reaches the model as surely as one in the message."""
    r, run = _note_chat("Explain my note please.", body=f"Homework:\n{ITEM.prompt}")
    assert r.json()["integrity"] == "refused"
    run.assert_not_called()


def test_the_post_call_scan_withholds_a_reply_stating_an_open_key(posed, records):
    r, run = _note_chat("How does factorial end?", reply=LEAKING_REPLY)
    assert r.status_code == 200
    assert r.json() == {"reply": WITHHELD_REPLY, "degraded": False, "integrity": "withheld"}
    run.assert_awaited_once()
    records.help.assert_called_once_with("u1", "qh-1", params.INTEGRITY_HELP_RUNG, source="outside")
    assert records.event.call_args.kwargs["stage"] == "reply"


def test_unrelated_questions_still_work_with_one_bounded_read_per_message(posed, records):
    r, run = _note_chat("What's the gist of my note?", reply="It covers merge sort.")
    assert r.json() == {"reply": "It covers merge sort.", "degraded": False}
    run.assert_awaited_once()
    # ONE read of the posed items serves both the pre-call check and the reply
    # scan — the bounded, batched posed_items (A93/A101), keyed by the student
    posed.assert_called_once()
    assert posed.call_args.args == ("u1",)
    records.help.assert_not_called()
    records.event.assert_not_called()


def test_another_students_items_never_match(posed, records):
    """u2 pastes u1's open check (and gets a reply stating its key): u1's items
    are never read for u2, so nothing is refused, withheld or recorded."""
    r, run = _note_chat(PASTE, user="u2", reply=LEAKING_REPLY)
    assert r.json() == {"reply": LEAKING_REPLY, "degraded": False}
    run.assert_awaited_once()
    assert [c.args for c in posed.call_args_list] == [("u2",)]
    records.help.assert_not_called()


def test_the_kill_switch_turns_the_guard_off(posed, records):
    with patch("routes.notes.learning_loop_for_request", return_value=False) as gate:
        r, run = _note_chat(PASTE, reply=LEAKING_REPLY)
    assert r.json() == {"reply": LEAKING_REPLY, "degraded": False}
    gate.assert_called_once_with("u1")
    posed.assert_not_called()
    records.help.assert_not_called()


@pytest.mark.parametrize("loop_off", ["kill_switch", "flag_off"])
def test_the_real_gate_turns_the_guard_off_both_ways(posed, records, monkeypatch, loop_off):
    """The real gate, not a patched one: the env kill switch, or the student's
    `learning_loop` flag off under an open switch — either way no posed-item
    scan, nothing refused or withheld, no help row."""
    import config

    if loop_off == "kill_switch":
        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
    else:
        monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "off")
    r, run = _note_chat(PASTE, reply=LEAKING_REPLY)
    assert r.json() == {"reply": LEAKING_REPLY, "degraded": False}
    posed.assert_not_called()
    records.help.assert_not_called()


def test_the_agent_reads_the_screened_note_snapshot(posed, records):
    """The route hands the agent the note it screened (deps.note), and
    read_active_note serves it without reading the note again — an edit landing
    mid-run cannot hand the model text the guard never saw."""
    seen = {}

    async def run(message, *, deps, usage_limits):
        seen["note"], seen["guard"] = deps.note, deps.integrity
        return SimpleNamespace(output="ok")

    with (
        patch("routes.notes.note_chat_agent.run", side_effect=run),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.get_note", side_effect=fake_get_note(body="screened body")),
    ):
        client.post("/api/notes/n1/chat", json={"user_id": "u1", "message": "hi"})
    assert seen["note"]["body"] == "screened body"
    # the agent's own writes (apply_graph_update_tool) are screened by the same guard
    assert isinstance(seen["guard"], integrity_guard.Guard) and seen["guard"].surface == "note_chat"
    assert seen["guard"].items == [ITEM]  # the request's one read, not a second

    import asyncio

    from agents.tools.note_context import read_active_note

    async def no_concepts(note_id, user_id):
        return []

    with (
        patch("agents.tools.note_context.get_note", side_effect=AssertionError("read again")),
        patch("agents.tools.note_context.list_linked_concepts", side_effect=no_concepts),
    ):
        ctx = asyncio.run(read_active_note("n1", "u1", note=seen["note"]))
    assert ctx.body == "screened body"


def test_note_chat_instructions_carry_the_integrity_rule():
    from agents.note_chat import _PROMPT

    assert "ACADEMIC INTEGRITY" in _PROMPT
    assert "learning session" in _PROMPT and "one step at a time" in _PROMPT


# ── summarize and extract-concepts ───────────────────────────────────────────


def _summarize(body: str, summary: str):
    run = AsyncMock(return_value=SimpleNamespace(output=SimpleNamespace(summary=summary)))
    save = AsyncMock()
    with (
        patch("routes.notes.note_summary_agent.run", run),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.get_note", side_effect=fake_get_note(body=body)),
        patch("routes.notes.save_summary", save),
    ):
        r = client.post("/api/notes/n1/summarize", json={"user_id": "u1"})
    return r, run, save


def test_summarize_refuses_a_note_holding_an_open_check_and_saves_nothing(posed, records):
    r, run, save = _summarize(f"Q to ask the AI: {ITEM.prompt}", "unused")
    assert r.status_code == 409 and r.json()["detail"] == REFUSED_DETAIL
    run.assert_not_called()
    save.assert_not_called()
    records.help.assert_called_once()


def test_summarize_withholds_a_summary_stating_an_open_key_and_saves_nothing(posed, records):
    r, run, save = _summarize(
        "Recursion notes, week 3.", "The note concludes the base case returns 1."
    )
    assert r.status_code == 409 and r.json()["detail"] == WITHHELD_DETAIL
    run.assert_awaited_once()
    save.assert_not_called()
    records.help.assert_called_once_with("u1", "qh-1", params.INTEGRITY_HELP_RUNG, source="outside")


def test_a_clean_summary_is_saved(posed, records):
    r, _run, save = _summarize("Merge sort splits the list.", "Merge sort, divide and conquer.")
    assert r.status_code == 200 and r.json() == {"summary": "Merge sort, divide and conquer."}
    save.assert_awaited_once()


def test_extract_concepts_drops_a_name_stating_an_unseen_key_and_keeps_the_notes_own(
    posed, records
):
    """A concept name the note itself holds is the student's own word (kept,
    unscanned); a name the model brought that states a posed check's key is
    dropped before it is filed or returned. u2's check: "the call stack"."""
    applied = {}

    async def apply(*, user_id, course_id, concept_names):
        applied["names"] = list(concept_names)

    async def lookup(*, user_id, course_id, names):
        return []

    def run_with(names):
        return AsyncMock(return_value=SimpleNamespace(output=SimpleNamespace(concepts=names)))

    for body, expect_kept, expect_withheld in (
        ("Recursion notes: which structure keeps frames?", ["Recursion"], 1),
        ("Each call pushes a frame on the call stack.", ["Recursion", "The Call Stack"], 0),
    ):
        records.help.reset_mock()
        with (
            patch(
                "routes.notes.note_concepts_agent.run", run_with(["Recursion", "The Call Stack"])
            ),
            patch("routes.notes.offering_course_id", return_value="c1"),
            patch("routes.notes.get_note", side_effect=fake_get_note(body=body)),
            patch("routes.notes.apply_concepts_to_graph", side_effect=apply),
            patch("routes.notes._lookup_concept_nodes_by_name", side_effect=lookup),
        ):
            r = client.post("/api/notes/n1/extract-concepts", json={"user_id": "u2"})
        assert r.status_code == 200, r.text
        assert r.json()["concepts"] == expect_kept == applied["names"]
        assert r.json().get("withheld", 0) == expect_withheld
        assert records.help.call_count == expect_withheld


def test_extract_concepts_refuses_a_note_holding_an_open_check(posed, records):
    run = AsyncMock()
    with (
        patch("routes.notes.note_concepts_agent.run", run),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.get_note", side_effect=fake_get_note(body=ITEM.prompt)),
    ):
        r = client.post("/api/notes/n1/extract-concepts", json={"user_id": "u1"})
    assert r.status_code == 409 and r.json()["detail"] == REFUSED_DETAIL
    run.assert_not_called()


# ── the flashcard generators (/api/flashcards/*) ─────────────────────────────


def _paste(text: str, cards: list):
    gen = MagicMock(return_value=cards)
    with (
        patch("routes.flashcards.gemini_generate_cards", gen),
        patch("routes.flashcards.check_rate_limit", return_value=None),
    ):
        r = client.post(
            "/api/flashcards/import/generate",
            json={"user_id": "u1", "source": "paste", "text": text},
        )
    return r, gen


def test_flashcard_paste_quoting_an_open_check_is_refused_before_the_model(posed, records):
    r, gen = _paste(PASTE, [])
    assert r.status_code == 409 and r.json()["detail"] == REFUSED_DETAIL
    gen.assert_not_called()
    records.help.assert_called_once()


def test_a_card_stating_an_open_key_is_withheld_and_the_rest_served(posed, records):
    cards = [
        {"front": "How does factorial(0) end?", "back": "The base case returns 1"},
        {"front": "What is merge sort?", "back": "A divide and conquer sort"},
    ]
    r, _gen = _paste("Lecture 3 notes on sorting.", cards)
    assert r.status_code == 200
    assert r.json() == {"cards": [cards[1]], "withheld": 1}
    records.help.assert_called_once_with("u1", "qh-1", params.INTEGRITY_HELP_RUNG, source="outside")


def test_every_card_withheld_is_a_409(posed, records):
    r, _gen = _paste("Lecture 3.", [{"front": "factorial(0)?", "back": "The base case returns 1"}])
    assert r.status_code == 409 and r.json()["detail"] == WITHHELD_DETAIL


def test_a_cloze_of_the_students_own_sentence_is_kept(posed, records):
    """A cloze card is read with its blank filled, so a cloze of the student's
    own sentence is the copy it is — never a withheld key."""
    paragraph = "In factorial, the base case returns 1 when n equals 0, which stops it."
    card = {
        "front": "In factorial, {{...}} when n equals 0, which stops it.",
        "back": "the base case returns 1",
    }
    with (
        patch("routes.flashcards.gemini_cloze", return_value=[card]),
        patch("routes.flashcards.check_rate_limit", return_value=None),
    ):
        r = client.post(
            "/api/flashcards/import/cloze", json={"user_id": "u1", "paragraph": paragraph}
        )
    assert r.status_code == 200 and r.json() == {"cards": [card]}
    records.help.assert_not_called()


def test_library_doc_generation_is_not_guarded(posed, records):
    """A library document is stored course material, not request text."""
    with (
        patch("services.flashcards.cards.table") as t,  # #118: the library read moved here
        patch(
            "routes.flashcards.gemini_generate_cards",
            return_value=[{"front": "q", "back": "The base case returns 1"}],
        ),
        patch("routes.flashcards.check_rate_limit", return_value=None),
    ):
        t.return_value.select.return_value = [{"id": "d1", "summary": None, "concept_notes": None}]
        r = client.post(
            "/api/flashcards/import/generate",
            json={"user_id": "u1", "source": "library_doc", "document_id": "d1"},
        )
    assert r.status_code == 200
    posed.assert_not_called()


@pytest.mark.parametrize("surface", ["topic", "cleanup", "ocr"])
def test_every_other_flashcard_generator_is_guarded_both_ways(posed, records, surface):
    """/generate (its topic), /import/cleanup (the cards' text) and the OCR
    import (the photographed page, once it is text): quoting text is refused
    before the model; a card stating a key is withheld."""
    leaking = [
        {"front": "factorial(0)?", "back": "The base case returns 1"},
        {"front": "a", "back": "b"},
    ]
    agent = MagicMock(return_value=leaking)

    def call(text: str):
        if surface == "topic":
            with (
                patch("routes.flashcards._generate", agent),
                patch("routes.flashcards.table") as t,
                patch("services.achievement_service.check_achievements"),
            ):
                t.return_value.select.return_value = []
                return client.post(
                    "/api/flashcards/generate", json={"user_id": "u1", "topic": text}
                )
        if surface == "cleanup":
            with (
                patch("routes.flashcards.gemini_cleanup_cards", agent),
                patch("routes.flashcards.check_rate_limit", return_value=None),
            ):
                return client.post(
                    "/api/flashcards/import/cleanup",
                    json={"user_id": "u1", "cards": [{"front": text, "back": "?"}]},
                )
        import base64

        with (
            patch(
                "services.flashcard_import_service.extraction_service.extract_text_from_file",
                return_value=text,
            ),
            patch("services.flashcard_import_service._run_flashcard_agent", agent),
        ):
            return client.post(
                "/api/flashcards/import/parse",
                json={
                    "user_id": "u1",
                    "source": "ocr",
                    "payload": base64.b64encode(b"img").decode(),
                    "options": {"filename": "page.png"},
                },
            )

    r = call(PASTE)
    assert r.status_code == 409 and r.json()["detail"] == REFUSED_DETAIL
    agent.assert_not_called()
    r = call("Intro CS")
    assert r.status_code == 200, r.text
    served = r.json().get("flashcards") or r.json().get("cards")
    assert r.json()["withheld"] == 1
    if surface == "cleanup":
        # withheld whole: the student's own cards come back as they sent them
        assert served == [{"front": "Intro CS", "back": "?"}]
    else:
        assert [c["back"] for c in served] == ["b"]
    # one help row per request: the refused paste, then the withheld card
    assert [c.args for c in records.help.call_args_list] == [
        ("u1", "qh-1", params.INTEGRITY_HELP_RUNG)
    ] * 2
    assert [c.kwargs["stage"] for c in records.event.call_args_list] == ["request", "reply"]


# ── the floor: a help record floors the later grade (A93) ────────────────────


class _Ledger:
    """learning_reveals in memory, with the PostgREST filters help_ledger uses."""

    def __init__(self):
        self.rows: list[dict] = []

    @staticmethod
    def _hit(row: dict, filters) -> bool:
        for key, expr in (filters or {}).items():
            op, _, arg = expr.partition(".")
            value = row.get(key)
            if op == "eq" and str(value) != arg:
                return False
            if op == "in" and str(value) not in arg.strip("()").split(","):
                return False
            if op == "is" and arg == "null" and value is not None:
                return False
        return True

    def insert(self, rows):
        self.rows.extend(dict(r) for r in (rows if isinstance(rows, list) else [rows]))
        return []

    def select(self, cols, *, filters=None, order=None, limit=None):
        out = [dict(r) for r in self.rows if self._hit(r, filters)]
        return out[:limit] if limit else out

    def update(self, data, *, filters=None, prefer_return_minimal=False):
        for row in self.rows:
            if self._hit(row, filters):
                row.update(data)
        return []


def test_a_help_record_floors_the_later_grade(gate_on, seams):
    """End to end, the real ledger code on an in-memory table: the student pastes
    an open check into the notes chat (refused, help row written), then answers
    that check in the loop — the grade carries no unassisted credit."""
    ledger = _Ledger()
    seams.open_posed.return_value = ([(ITEM, POSED)], None)  # the guard's one read
    # spec §13 A149: the guard reads the scan set from services/loop/posed.py
    with patch("learning.help_ledger.table", return_value=ledger), \
            patch("services.loop.posed.posed_items", seams.open_posed):
        r, run = _note_chat(PASTE)
        assert r.json()["integrity"] == "refused"
        run.assert_not_called()
        (row,) = ledger.rows
        assert {k: row[k] for k in ("user_id", "kind", "question_hash", "rung", "source")} == {
            "user_id": "u1",
            "kind": "help",
            "question_hash": "qh-1",
            "rung": params.INTEGRITY_HELP_RUNG,
            "source": "outside",
        }

        assert services.loop.reveals._reveal_floor("u1", ITEM, None) >= params.RUNG_NO_CREDIT_MIN

        seams.store["doc"] = _routes._state(attempted_at=[_routes.T0 + 10])
        rung_seen: list = []
        _grade_appends(seams, rung_seen)
        written: list = []
        seams.flush.side_effect = lambda deps, course: (
            written.append([dict(e) for e in deps.pending_evidence]) or []
        )
        agent_p, usage_p, _ = _routes._feedback_agent()
        with agent_p, usage_p, patch_loop("mark_graded"):
            r = client.post(
                "/api/learn/loop/check/answer",
                json=_routes._answer(answer="The base case returns 1"),
            )
    assert r.status_code == 200, r.text
    assert rung_seen == [params.INTEGRITY_HELP_RUNG]  # graded at the floor …
    ((ev,),) = written  # … and written with it
    assert ev["max_rung"] >= params.RUNG_NO_CREDIT_MIN and ev["assisted"] is True
    from learning.evidence import Evidence

    assert Evidence.model_validate(ev).weight == 0.0  # no unassisted credit


# ── function mode and the bound ──────────────────────────────────────────────


def test_the_function_mode_note_outputs_state_no_seeded_items_key():
    """The E2E lanes run the notes actions on fixed constants against the seeded
    loop items: the guard must leave them served (handlers ↔ guard in sync)."""
    from agents import function_handlers_e2e as fh
    from learning.served_scan import ScanSet

    seeded = [
        CheckItem(
            id=f"id-{n}",
            course_id="c1",
            concept_key="k",
            format="free",
            difficulty=1,
            prompt=prompt,
            reference_answer=reference,
            final_answer=final,
            canonical_answer=None,
            rubric=[RubricItem(id="r1", text="a"), RubricItem(id="r2", text="b")],
            common_wrong=[WrongReason(key="w", text="wrong")],
            source_chunk_ids=[],
            stepwise=False,
            question_hash=f"qh-{n}",
        )
        for n, (prompt, reference, final) in enumerate(
            [
                (fh.E2E_LOOP_PROBE_PROMPT, fh.E2E_LOOP_REFERENCE, fh.E2E_LOOP_FINAL_ANSWER),
                (
                    fh.E2E_CHECK_ITEM_PROMPT_TEMPLATE.format(concept="recursion", format="free"),
                    fh.E2E_CHECK_ITEM_REFERENCE,
                    fh.E2E_CHECK_ITEM_FINAL_ANSWER,
                ),
            ]
        )
    ]
    scan = ScanSet.build(seeded, given="")
    for text in (fh.E2E_NOTE_CHAT_REPLY, fh.E2E_NOTE_SUMMARY, *fh.E2E_NOTE_CONCEPTS):
        assert scan.stated(text) == []
    assert StemSet.build(seeded).quoted(fh.E2E_NOTE_CHAT_REPLY) == []


def test_the_pre_check_is_bounded_for_the_scan_window():
    """The read is bounded by LOOP_SCAN_POSED_MAX (posed_items' contract, pinned
    in test_learning_teach_reveal.py); matching that many stems against a long
    note stays well inside a generous CPU bound (≈0.3 s measured)."""
    import random

    rng = random.Random(7)
    words = "the of recursion base case stack frame returns value call tree node sort merge".split()

    def sent(n):
        return " ".join(rng.choice(words) for _ in range(n))

    items = [
        _item(f"qh-{i}", f"In one sentence, {sent(14)}?") for i in range(params.LOOP_SCAN_POSED_MAX)
    ]
    note = "\n".join(sent(18) + "." for _ in range(400))
    start = time.process_time()
    StemSet.build(items).quoted(note)
    assert time.process_time() - start < 10.0
    assert stem_match.tokens("") == []
