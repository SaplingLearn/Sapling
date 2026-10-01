"""PKG-14 final fix round (spec §13 A101): the served-text scan, compiled once per
turn — focused review M2 (the scan blocked the event loop, its cost growing with
the posed set and the reply length) and minors 1–3.

- (a) every item's rules are built once per turn; the posed items are read in
  batches (tests/test_learning_teach_reveal.py pins posed_items' batching);
- (b) a scan reads the new suffix plus an overlap (`ScanSet.window_start`),
  never the whole text again — and finds what a whole-text scan finds;
- (c) the stream runs the scan in a worker thread and awaits it before the
  chunk that triggered it goes out; a cancelled stream's final scan waits for
  an in-flight one (the turn's lock);
- (d) the fan-out is cut before any item is loaded (teach_reveal tests);
- minor 1: EVERY relayed delta is scanned (no 80-char blind window);
- minor 2: one 'unscanned' marker and one unscanned zpd.reveal per turn;
- minor 3: the ledger read that hits its row limit reports an edge.

The performance test bounds CPU time (process time), generously — never wall
clock — for 200 items and a 4k reply streamed in 20-char deltas through the
REAL `_LoopTurn.record_relayed`."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import leak, params
from learning.checks import CheckItem, Option, RubricItem, WrongReason
from learning.ladder import Rung
from learning.served_scan import ScanSet, form_chars
from services.chat_stream import SaplingEvent

POSED = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
WORDS = (
    "the of recursion base case stack frame returns value function call tree node pointer "
    "memory graph edge weight path sort merge quick heap binary search loop index array"
).split()


def _item(qh, final, *, reference=None, fmt="free", options=None, correct=None, canonical=None):
    return CheckItem(
        id=f"id-{qh}",
        course_id="c1",
        concept_key="k",
        format=fmt,
        difficulty=2,
        prompt="What is it?",
        reference_answer=reference or f"The answer is {final}.",
        final_answer=final,
        canonical_answer=canonical,
        answer_kind="numeric" if canonical else "free",
        options=options,
        correct_option=correct,
        rubric=[RubricItem(id="r1", text="a"), RubricItem(id="r2", text="b")],
        common_wrong=[WrongReason(key="w", text="wrong")],
        source_chunk_ids=["ch"],
        question_hash=qh,
    )


def _random_items(n: int, rnd: random.Random) -> list[CheckItem]:
    return [
        _item(
            f"h{i}",
            " ".join(rnd.choice(WORDS) for _ in range(3)) + f" {i}",
            reference=" ".join(rnd.choice(WORDS) for _ in range(30)),
        )
        for i in range(n)
    ]


ITEMS = [
    _item("qh-base", "returns 1", reference="The base case returns 1 when n is 0."),
    _item("qh-stack", "the call stack", reference="Frames sit on the call stack."),
    _item("qh-num", "12.5", canonical="12.5"),
    _item(
        "qh-mc",
        "a sorted array",
        fmt="mc_reason",
        options=[
            Option(letter="A", text="a linked list"),
            Option(letter="B", text="a sorted array"),
            Option(letter="C", text="a hash map"),
        ],
        correct="B",
    ),
]
TEXTS = [
    "Key idea: At n == 0 it returns 1.\n\nEach frame waits on the call stack.\n\nWhy?",
    "A base case stops it. Try writing one.",
    "The result is twelve and a half. Or 12.5, written out.",
    "So the answer is B, because binary search needs a sorted array.",
    "Option B is right. Think about the third option too.",
    "Nothing here states anything at all.",
    "Returns one. The stack holds frames. 25/2 is the value.",
]


# ── equivalence with detect_leak ─────────────────────────────────────────────


def _detect_all(text, items, given=""):
    out = []
    for item in items:
        opt = next((o.text for o in item.options or [] if o.letter == item.correct_option), None)
        if leak.detect_leak(
            reference=item.reference_answer,
            emitted=text,
            rung=Rung.H0,
            final_answer=item.final_answer,
            canonical_answer=item.canonical_answer,
            correct_option=item.correct_option,
            option_text=opt,
            strict=True,
            given=given,
        ).leaked:
            out.append(item.question_hash)
    return sorted(out)


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("given", ["", "What does factorial(0) return? It returns a value."])
def test_the_compiled_scan_states_exactly_what_detect_leak_says(text, given):
    assert ScanSet.build(ITEMS, given=given).stated(text) == _detect_all(text, ITEMS, given)


def test_the_compiled_scan_matches_detect_leak_on_random_texts():
    rnd = random.Random(7)
    items = _random_items(40, rnd)
    scan = ScanSet.build(items, given="What is the base case?")
    for _ in range(60):
        pieces = [rnd.choice(WORDS) for _ in range(rnd.randint(5, 60))]
        if rnd.random() < 0.5:  # plant an item's answer (or an inflection of it)
            target = rnd.choice(items)
            planted = target.final_answer.split()
            if rnd.random() < 0.3:
                planted[0] = planted[0] + "s"
            pieces[rnd.randrange(len(pieces)) :] = planted
        text = " ".join(pieces) + rnd.choice([".", "", "?"])
        assert scan.stated(text) == _detect_all(text, items, "What is the base case?"), text


def test_the_lemma_index_finds_the_same_spans_as_the_full_walk():
    rnd = random.Random(3)
    for _ in range(80):
        toks = leak.answer_tokens(" ".join(rnd.choice(WORDS + ["returned", "returning", "stacks"]) for _ in range(40)))
        run = tuple(leak.answer_run(" ".join(rnd.choice(WORDS + ["return"]) for _ in range(rnd.randint(1, 3)))))
        assert leak._lemma_run_hits(toks, run, leak._lemma_index(toks)) == leak._lemma_run_hits(toks, run)


def test_rules_that_cannot_be_built_count_as_stated_and_non_servable_items_are_skipped():
    legacy = _item("qh-legacy", "x")
    legacy.final_answer = None  # a legacy row: not servable
    with patch("learning.served_scan.leak.served_rules", side_effect=ValueError("bad")):
        scan = ScanSet.build([ITEMS[0], legacy], given="")
    assert scan.hashes == ["qh-base"]
    assert scan.stated("nothing") == ["qh-base"]


def test_nothing_is_stated_at_h6_through_stated_items():
    from routes.learn_loop import stated_items

    assert stated_items(TEXTS[0], ITEMS, rung=Rung.H6, given="") == []
    assert stated_items(TEXTS[0], ITEMS, rung=Rung.H0, given="") == _detect_all(TEXTS[0], ITEMS)


# ── (b) the window ───────────────────────────────────────────────────────────


def test_the_overlap_covers_twice_the_longest_form_plus_the_context():
    scan = ScanSet.build(ITEMS, given="")
    longest = max(form_chars(i) for i in ITEMS)
    assert scan.overlap == 2 * longest + params.LEAK_POSITION_WINDOW_CHARS + params.LOOP_SCAN_CONTEXT_CHARS


def test_window_start_counts_non_space_characters_and_snaps_to_a_sentence():
    scan = ScanSet.build(ITEMS, given="")
    filler = "word " * 400
    text = filler + "First sentence ends here. " + "x" * 10 + " tail"
    start = scan.window_start(text, len(text))
    assert 0 < start < len(text)
    assert sum(1 for c in text[start:] if not c.isspace()) >= scan.overlap
    # stretched whitespace cannot outrun the overlap: it is counted in non-space chars
    spaced = "a" + " " * 5000 + "b"
    assert scan.window_start(spaced, len(spaced)) == 0
    assert scan.window_start("short", 5) == 0


def test_an_answer_spanning_the_scan_boundary_is_caught():
    """The answer's first half went out in one delta, its second in the next:
    the second scan's window reaches back over it."""
    scan = ScanSet.build(ITEMS, given="")
    head = ("Think about frames. " * 30) + "Each frame waits on the call"
    text = head + " stack, so it unwinds."
    assert scan.stated(head) == []
    start = scan.window_start(text, len(head))
    assert start < head.index("the call")
    assert "qh-stack" in scan.stated(text, start=start)


def test_incremental_scanning_finds_what_a_whole_text_scan_finds():
    rnd = random.Random(11)
    items = _random_items(60, rnd)
    scan = ScanSet.build(items, given="")
    for _ in range(25):
        pieces = [rnd.choice(WORDS) for _ in range(rnd.randint(50, 300))]
        for target in rnd.sample(items, 3):
            at = rnd.randrange(len(pieces))
            pieces[at:at] = target.final_answer.split()
        text = ". ".join(" ".join(pieces[i : i + 9]) for i in range(0, len(pieces), 9))
        found: set[str] = set()
        shown, upto = "", 0
        step = rnd.choice([1, 7, 20, 64])
        for k in range(0, len(text), step):
            shown += text[k : k + step]
            found |= set(scan.stated(shown, start=scan.window_start(shown, upto), skip=found))
            upto = len(shown)
        assert sorted(found) == scan.stated(text)


# ── the turn: every delta, in a thread, ordered, once-per-turn markers ───────


def _scan_turn(items, *, overflow=None, unreadable=False):
    """A real _LoopTurn's scan methods on a bare object (no request)."""
    from routes import learn_loop

    turn = learn_loop._LoopTurn.__new__(learn_loop._LoopTurn)
    turn.user_id, turn.session_id, turn.phase, turn.tier = "u1", "s1", "teach", "standard"
    turn.item, turn.given, turn.request_id = None, "", "rq"
    turn.reveal_hashes, turn.reveal_unscanned = [], False
    turn.reveal_overflow, turn.reveal_fallback = None, None
    got = None if unreadable else ([(i, POSED) for i in items], overflow)
    return turn, patch("routes.learn_loop.posed_items", return_value=got)


def test_record_relayed_scans_every_delta_and_records_each_item_once():
    from routes import learn_loop

    turn, posed = _scan_turn(ITEMS[:2])
    with (
        posed,
        patch("routes.learn_loop.record_reveals") as rec,
        patch("routes.learn_loop.record_unscanned") as marker,
        patch("routes.learn_loop.zpd_events") as zpd,
    ):
        shown = ""
        for delta in ["At n == 0 it ret", "urns 1. Each frame", " waits on the call stack."]:
            shown += delta
            learn_loop._LoopTurn.record_relayed(turn, shown)
    assert [c.args[1] for c in rec.call_args_list] == [["qh-base"], ["qh-stack"]]
    marker.assert_not_called()
    assert [c.kwargs["question_hashes"] for c in zpd.emit_zpd_reveal.call_args_list] == [
        ["qh-base"],
        ["qh-stack"],
    ]
    assert turn.reveal_hashes == ["qh-base", "qh-stack"]


def test_an_unreadable_scan_set_writes_one_marker_and_one_event_per_turn():
    """Minor 2: a stream meets the unreadable scan set on every delta; the turn
    writes ONE 'unscanned' marker and emits ONE unscanned zpd.reveal."""
    from routes import learn_loop

    turn, posed = _scan_turn([], unreadable=True)
    with (
        posed as read,
        patch("routes.learn_loop.record_reveals") as rec,
        patch("routes.learn_loop.record_unscanned") as marker,
        patch("routes.learn_loop.zpd_events") as zpd,
    ):
        for n in range(1, 30):
            learn_loop._LoopTurn.record_relayed(turn, "word " * n)
        learn_loop._LoopTurn._record_served(turn)  # complete()'s write too
    assert read.call_count == 1  # read once per turn
    marker.assert_called_once()
    rec.assert_not_called()
    (event,) = zpd.emit_zpd_reveal.call_args_list
    assert event.kwargs["unscanned"] is True


def test_the_overflow_marker_is_written_once_per_turn():
    from routes import learn_loop

    turn, posed = _scan_turn(ITEMS[:1], overflow=POSED)
    with (
        posed,
        patch("routes.learn_loop.record_reveals"),
        patch("routes.learn_loop.record_unscanned") as marker,
        patch("routes.learn_loop.zpd_events"),
    ):
        for n in range(1, 10):
            learn_loop._LoopTurn.record_relayed(turn, "word " * n)
    (call,) = marker.call_args_list
    assert call.kwargs["at"] == POSED


def _tok(text):
    return SaplingEvent(type="token", step="reply", message="", data={"delta": text})


def test_the_stream_scans_off_the_event_loop_before_each_chunk_goes_out():
    """(c): record_relayed runs in a worker thread, and the chunk that triggered
    it is yielded only after it returned."""
    from routes import learn_loop

    order: list = []
    main = threading.get_ident()
    turn = MagicMock()
    turn.tier, turn.paused = "standard", False
    turn.pre_events.return_value = []
    turn.record_relayed.side_effect = lambda text: order.append(("scan", text, threading.get_ident() != main))

    async def fake(**kw):
        for d in ["Hello ", "there."]:
            yield _tok(d)
        yield SaplingEvent(type="done", step="reply", message="Complete.", data={})

    async def drain():
        async for chunk in learn_loop._stream_turn(turn):
            if '"token"' in chunk or "token" in str(chunk)[:40]:
                order.append(("out", len([o for o in order if o[0] == "scan"])))

    with patch("routes.learn_loop.ai_budget"), patch("routes.learn_loop.stream_structured_turn", fake):
        asyncio.run(drain())
    scans = [o for o in order if o[0] == "scan"]
    assert [s[1] for s in scans] == ["Hello ", "Hello there."]
    assert all(s[2] for s in scans)  # off the event loop's thread
    outs = [o for o in order if o[0] == "out"]
    assert outs[0][1] >= 1 and outs[1][1] >= 2  # each chunk after its own scan


def test_a_cancelled_streams_final_scan_waits_for_the_in_flight_one():
    """The turn's lock: the synchronous final scan of a cancelled stream never
    runs concurrently with a worker-thread scan still in flight."""
    from routes import learn_loop

    turn, posed = _scan_turn(ITEMS[:1])
    inside = threading.Event()
    release = threading.Event()
    active = []
    real = learn_loop._LoopTurn._record_relayed

    def slow(self, text):
        active.append(text)
        assert len(active) == 1, "two scans of one turn ran at once"
        if not inside.is_set():
            inside.set()
            release.wait(5)
        real(self, text)
        active.pop()

    with (
        posed,
        patch.object(learn_loop._LoopTurn, "_record_relayed", slow),
        patch("routes.learn_loop.record_reveals"),
        patch("routes.learn_loop.zpd_events"),
    ):
        t = threading.Thread(target=learn_loop._LoopTurn.record_relayed, args=(turn, "At n == 0"))
        t.start()
        inside.wait(5)
        threading.Timer(0.05, release.set).start()
        learn_loop._LoopTurn.record_relayed(turn, "At n == 0 it returns 1.")  # blocks on the lock
        t.join(5)
    assert turn.reveal_hashes == ["qh-base"]


# ── minor 3: the ledger read's edge ──────────────────────────────────────────


def test_a_ledger_read_that_hits_its_row_limit_reports_an_edge():
    from learning import help_ledger

    rows = [{"question_hash": "same", "at": f"2026-09-30T0{9 - i}:00:00Z"} for i in range(8)]
    handle = MagicMock()
    handle.select.return_value = rows
    with patch("learning.help_ledger.table", return_value=handle):
        items, edge = help_ledger.ungraded_posed_window("u1", 2)  # fetch = 8 rows: the limit
    assert [h for h, _ in items] == ["same"]  # ONE distinct item among the rows read
    assert edge == datetime(2026, 9, 30, 2, tzinfo=timezone.utc)  # the oldest row read
    handle.select.return_value = rows[:3]
    with patch("learning.help_ledger.table", return_value=handle):
        _, edge = help_ledger.ungraded_posed_window("u1", 2)
    assert edge is None  # a short read left nothing out


def test_the_distinct_limit_still_reports_the_newest_left_out():
    from learning import help_ledger

    handle = MagicMock()
    handle.select.return_value = [
        {"question_hash": "c", "at": "2026-09-30T03:00:00Z"},
        {"question_hash": "b", "at": "2026-09-30T02:00:00Z"},
        {"question_hash": "a", "at": "2026-09-30T01:00:00Z"},
    ]
    with patch("learning.help_ledger.table", return_value=handle):
        items, edge = help_ledger.ungraded_posed_window("u1", 2)
    assert [h for h, _ in items] == ["c", "b"]
    assert edge == datetime(2026, 9, 30, 1, tzinfo=timezone.utc)


# ── the bound: 200 items, a 4k reply, 20-char deltas, the REAL path ──────────

#: generous CPU seconds for the whole streamed turn's scans (the first build
#: spent ~62 s on this shape; this build ~1 s)
SCAN_CPU_BUDGET_S = 10.0


def test_a_long_streamed_turn_over_200_items_stays_within_a_cpu_budget():
    from routes import learn_loop

    rnd = random.Random(5)
    items = _random_items(params.LOOP_SCAN_POSED_MAX, rnd)
    sentences, size = [], 0
    while size < 4000:
        s = " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(8, 16))) + rnd.choice([".", "?", ","])
        sentences.append(s)
        size += len(s) + 1
    text = " ".join(sentences)[:4200]
    turn, posed = _scan_turn(items)
    with (
        posed,
        patch("routes.learn_loop.record_reveals"),
        patch("routes.learn_loop.record_unscanned"),
        patch("routes.learn_loop.zpd_events"),
    ):
        t0 = time.process_time()
        shown = ""
        for k in range(0, len(text), 20):
            shown += text[k : k + 20]
            learn_loop._LoopTurn.record_relayed(turn, shown)
        learn_loop._LoopTurn._scan_served(turn, shown)  # complete()'s final scan
        spent = time.process_time() - t0
    assert spent < SCAN_CPU_BUDGET_S, f"{spent:.2f}s CPU"
    assert turn.reveal_hashes == ScanSet.build(items, given="").stated(text)


# ── PKG-14/15 review fix round (spec §13 A105): the window in word tokens ────

_PAD = " " + "-" * 60 + " "
_STACK = _item("qh-stack-pad", "the call stack", reference="Frames sit on the call stack.")
_FILL = "Let us think about this carefully together. " * 12


def _streamed(text, items, step):
    """What a stream finds, relaying `text` in `step`-char deltas (window_start)."""
    scan = ScanSet.build(items, given="")
    found, last, shown = set(), None, ""
    for k in range(0, len(text), step):
        shown += text[k : k + step]
        start = scan.window_start(shown, len(last)) if last and shown.startswith(last) else 0
        last = shown
        found |= set(scan.stated(shown, start=start, skip=found))
    return found


@pytest.mark.parametrize("step", [1, 7, 20, 64])
def test_an_ngram_padded_with_punctuation_between_its_words_is_caught_while_streaming(step):
    """Review m1: the n-gram rule reads word tokens and skips punctuation, so 60
    dashes between the words stretched the answer past a window counted in
    non-space characters — detect_leak caught it, the streamed scan did not."""
    text = _FILL + _PAD.join("Frames sit on the call stack".split()) + "."
    assert _detect_all(text, [_STACK]) == ["qh-stack-pad"]
    assert _streamed(text, [_STACK], step) == {"qh-stack-pad"}


def test_window_start_reaches_back_over_enough_word_tokens():
    scan = ScanSet.build([_STACK], given="")
    assert scan.overlap_tokens >= params.LEAK_NGRAM
    text = _FILL + _PAD.join(f"w{i}" for i in range(200))
    start = scan.window_start(text, len(text))
    words = [w for w in text[start:].split() if any(c.isascii() and c.isalnum() for c in w)]
    assert len(words) >= scan.overlap_tokens


def test_the_reviewers_probe_cases_stream_exactly_as_a_whole_text_scan():
    num = _item("qh-num", "1234567", canonical="1234567")
    frac = _item("qh-frac", "12.5", canonical="12.5")
    mc = _item(
        "qh-mc",
        "a sorted array",
        fmt="mc_reason",
        options=[
            Option(letter="A", text="a linked list"),
            Option(letter="B", text="a sorted array"),
            Option(letter="C", text="a hash map"),
        ],
        correct="B",
    )
    cases = [
        (_STACK, _FILL + "It is the" + _PAD + "call" + _PAD + "stack."),
        (_STACK, _FILL + _PAD.join("Frames sit on the call stack".split()) + "."),
        (_STACK, _FILL + "the " + "é" * 80 + " call " + "é" * 80 + " stack"),
        (num, _FILL + "The answer is one million two hundred thirty-four thousand five hundred sixty-seven."),
        (frac, _FILL + r"So $x = \dfrac{25}{2}$, which we write as $$\frac{ 25 }{ 2 }$$."),
        (mc, _FILL + "So the correct option, after weighing every single consideration we discussed, is B."),
        (mc, _FILL + "You want a sorted " + "=" * 120 + " array."),
    ]
    for item, text in cases:
        whole = set(_detect_all(text, [item]))
        for step in (1, 7, 20, 64):
            assert _streamed(text, [item], step) == whole, (item.question_hash, step)


def test_completes_final_scan_is_a_whole_text_scan():
    """Review m1 safety net: the turn's final text is scanned whole once at
    completion, so no windowing gap survives the turn — here a window that
    skips everything already scanned (start = upto) still ends in the hit."""
    from routes import learn_loop

    turn, posed = _scan_turn([_STACK])
    text = _FILL + "Frames sit on the call stack."
    with (
        posed,
        patch("routes.learn_loop.record_reveals"),
        patch("routes.learn_loop.record_unscanned"),
        patch("routes.learn_loop.zpd_events"),
        patch.object(ScanSet, "window_start", lambda self, t, upto: upto),
    ):
        shown = ""
        for k in range(0, len(text), 3):
            shown += text[k : k + 3]
            learn_loop._LoopTurn.record_relayed(turn, shown)
        assert turn.reveal_hashes == []  # the broken window missed it
        learn_loop._LoopTurn._scan_served(turn, text, whole=True)
    assert turn.reveal_hashes == ["qh-stack-pad"]


def _complete_turn(cls):
    turn = MagicMock()
    turn.__dict__["_scan_lock"] = threading.Lock()
    turn._leak_checked.return_value = ("the reply", False)
    turn._submission_extra.return_value = {}
    turn.reveal_fallback = None
    turn.planned.level = "soft"
    turn.ceiling = 2
    return turn


def test_both_completions_scan_the_final_text_whole():
    from routes import learn_loop

    turn = _complete_turn(learn_loop._LoopTurn)
    with (
        patch("routes.learn_loop._update_loop_state"),
        patch("routes.learn_loop.save_message"),
        patch("routes.learn_loop.events_service"),
        patch("routes.learn_loop.get_check_item"),
    ):
        learn_loop._LoopTurn.complete(turn, "the reply", {}, [])
    turn._scan_served.assert_called_once_with("the reply", whole=True)
    opener = _complete_turn(learn_loop._LoopOpener)
    try:
        learn_loop._LoopOpener.complete(opener, "hello", {}, [])
    except Exception:
        pass  # the opener's later bookkeeping needs a real request; the scan came first
    opener._scan_served.assert_called_once_with("hello", whole=True)


# ── review m4: a scan exception never skips its window silently ──────────────


def test_a_scan_exception_writes_the_unscanned_marker_and_keeps_the_window():
    from routes import learn_loop

    turn, posed = _scan_turn([_STACK])
    real = ScanSet.stated
    calls = []

    def flaky(self, text, *, start=0, skip=()):
        calls.append(start)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(self, text, start=start, skip=skip)

    first = _FILL + "Frames sit on the call stack."
    with (
        posed,
        patch("routes.learn_loop.record_reveals") as rec,
        patch("routes.learn_loop.record_unscanned") as marker,
        patch("routes.learn_loop.zpd_events") as zpd,
        patch.object(ScanSet, "stated", flaky),
    ):
        learn_loop._LoopTurn.record_relayed(turn, first)
        marker.assert_called_once()  # fail closed: posed items floor to assisted (A88/A93)
        assert zpd.emit_zpd_reveal.call_args.kwargs["unscanned"] is True
        assert "_scanned_text" not in turn.__dict__  # the failed window is NOT marked scanned
        learn_loop._LoopTurn.record_relayed(turn, first + " Next.")
    assert calls[1] == 0  # the next scan re-reads the window the failed one lost
    assert rec.call_args.args[1] == ["qh-stack-pad"]


# ── review m3: the stream's finally never blocks the event loop ──────────────


def _stream_mock(record):
    turn = MagicMock()
    turn.tier, turn.paused = "standard", False
    turn.pre_events.return_value = []
    turn.record_relayed.side_effect = record
    return turn


def test_a_cancelled_streams_final_scan_runs_off_the_event_loop_and_still_records():
    from routes import learn_loop

    main = threading.get_ident()
    started, release = threading.Event(), threading.Event()
    calls: list = []
    order: list = []

    def record(text):
        calls.append((text, threading.get_ident() != main))
        if len(calls) == 1:
            started.set()
        release.wait(5)  # the in-flight scan (and the lock a final scan waits on)

    turn = _stream_mock(record)

    async def fake(**kw):
        yield _tok("Frames sit")
        yield SaplingEvent(type="done", step="reply", message="Complete.", data={})

    async def main_():
        async def consume():
            async for _ in learn_loop._stream_turn(turn):
                pass

        task = asyncio.create_task(consume())
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        for _ in range(5):  # the loop stays free while the final scan waits
            await asyncio.sleep(0.01)
            order.append("tick")
        order.append("release")
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    with patch("routes.learn_loop.ai_budget"), patch("routes.learn_loop.stream_structured_turn", fake):
        asyncio.run(main_())
    assert order[:5] == ["tick"] * 5
    assert [c[0] for c in calls] == ["Frames sit", "Frames sit"]  # still recorded
    assert all(c[1] for c in calls)  # both off the event loop's thread
    turn.touch_served_at.assert_called_once()


def test_a_retracted_attempt_that_was_scanned_is_not_rescanned():
    from routes import learn_loop

    calls: list = []
    turn = _stream_mock(lambda text: calls.append(text))

    async def fake(**kw):
        yield _tok("A")
        yield _tok("B")
        yield SaplingEvent(type="retract", step="reply", message="", data={"reason": "retry"})
        yield _tok("C")
        yield SaplingEvent(type="done", step="reply", message="Complete.", data={})

    async def drain():
        async for _ in learn_loop._stream_turn(turn):
            pass

    with patch("routes.learn_loop.ai_budget"), patch("routes.learn_loop.stream_structured_turn", fake):
        asyncio.run(drain())
    assert calls == ["A", "AB", "C"]  # every delta once; "AB" was scanned, so no rescan
