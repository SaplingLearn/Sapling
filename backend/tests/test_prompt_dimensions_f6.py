"""F6: per-request prompt-composition dimensions.

`llm_usage.prompt_tokens` already records the truth about how big each
prompt was — but not what it was made OF, so nobody could say which block
to trim. These dimensions are the missing join key: they ride the same
`request_id` as the `llm_usage` row, so token counts become attributable to
sections instead of guessed at.

The load-bearing property is the cross-thread one. The route seeds the
accumulator, but the value that matters most (was the personal digest
present?) is only known inside an agent TOOL, which runs under
`asyncio.to_thread`. `contextvars.copy_context()` copies the mapping, not
the values — so mutating the shared dict propagates back to the route,
while rebinding the ContextVar would not. These tests pin that.
"""

import asyncio

import pytest

from services import prompt_dimensions as pd


@pytest.fixture(autouse=True)
def _clean():
    pd.clear()
    yield
    pd.clear()


def test_snapshot_is_empty_outside_a_capture_scope():
    assert pd.snapshot() == {}


def test_record_outside_a_capture_scope_is_a_noop():
    """Agent tools are called from routes that don't capture (the tutor
    today) and from unit tests. Recording must never require a scope."""
    pd.record(digest_present=True)
    assert pd.snapshot() == {}


def test_record_accumulates_within_a_scope():
    pd.start_capture()
    pd.record(k_chunks=4)
    pd.record(digest_present=True)
    assert pd.snapshot() == {"k_chunks": 4, "digest_present": True}


def test_later_record_overwrites_the_same_key():
    pd.start_capture()
    pd.record(k_chunks=1)
    pd.record(k_chunks=5)
    assert pd.snapshot()["k_chunks"] == 5


def test_snapshot_is_a_copy():
    """A caller stuffing the snapshot into an event payload must not be able
    to mutate the live accumulator by mutating what it got back."""
    pd.start_capture()
    pd.record(blocks=["rag"])
    snap = pd.snapshot()
    snap["blocks"] = ["tampered"]
    assert pd.snapshot()["blocks"] == ["rag"]


def test_start_capture_resets_previous_state():
    pd.start_capture()
    pd.record(k_chunks=9)
    pd.start_capture()
    assert pd.snapshot() == {}


def test_clear_ends_the_scope():
    pd.start_capture()
    pd.record(k_chunks=1)
    pd.clear()
    assert pd.snapshot() == {}
    pd.record(k_chunks=2)
    assert pd.snapshot() == {}


# ── The property everything else rests on ───────────────────────────────────


def test_record_from_a_worker_thread_reaches_the_caller():
    """THE test. Every agent read tool wraps its Supabase reads in
    `asyncio.to_thread`; if this didn't hold, `digest_present` would be
    silently absent from every quiz.started payload."""

    async def scenario():
        pd.start_capture()
        pd.record(k_chunks=2)

        def _in_tool():
            pd.record(digest_present=True)

        await asyncio.to_thread(_in_tool)
        return pd.snapshot()

    assert asyncio.run(scenario()) == {"k_chunks": 2, "digest_present": True}


def test_record_from_a_child_task_reaches_the_caller():
    """Pydantic AI may run tool calls as separate asyncio tasks, which copy
    the context at creation — same mutable-value reasoning."""

    async def scenario():
        pd.start_capture()

        async def _tool():
            pd.record(misconceptions=0)

        await asyncio.gather(_tool())
        return pd.snapshot()

    assert asyncio.run(scenario()) == {"misconceptions": 0}


def test_two_concurrent_requests_do_not_share_an_accumulator():
    """Each request seeds its own dict; a shared one would attribute one
    student's grounding to another's generation."""

    async def one(tag, k):
        pd.start_capture()
        pd.record(tag=tag, k_chunks=k)
        await asyncio.sleep(0)
        return pd.snapshot()

    async def scenario():
        return await asyncio.gather(one("a", 1), one("b", 5))

    a, b = asyncio.run(scenario())
    assert a == {"tag": "a", "k_chunks": 1}
    assert b == {"tag": "b", "k_chunks": 5}
