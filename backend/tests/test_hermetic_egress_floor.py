"""The session egress floor (spec §13 A123 review).

A test that calls `monkeypatch.undo()` undoes every per-test hermetic guard
that the conftest autouse fixtures installed with that same `monkeypatch`. The
A123 branch found such a test (tests/test_learning_review.py) that then sent a
real GET to the local stack at 127.0.0.1:54321.

`conftest._hermetic_egress_floor` sits under those guards for the whole
session, owned by a MonkeyPatch that no test can reach. Each test here undoes
its own monkeypatch first, as that test did. It then proves that the egress is
refused, and that no DNS lookup or socket connect was tried.
"""
import asyncio
import socket
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sockets():
    """Every DNS lookup or socket connect tried while active; each one is
    refused. It is on a MonkeyPatch of its own, so the test's
    `monkeypatch.undo()` keeps it: if the floor ever fails, the egress still
    stops here, and the test fails on what it records."""
    tried: list = []

    def _refuse(*args, **_kwargs):
        tried.append(args)
        raise OSError("network egress in a hermetic test")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket, "getaddrinfo", _refuse)
        mp.setattr(socket.socket, "connect", _refuse)
        mp.setattr(socket.socket, "connect_ex", _refuse)
        yield tried


def test_after_monkeypatch_undo_a_database_call_is_refused(monkeypatch, sockets):
    import db.connection as dbconn

    monkeypatch.undo()  # every per-test guard is gone, as in the A123 test
    assert not isinstance(dbconn._client, MagicMock), "the per-test stub should be gone"
    with pytest.raises(RuntimeError, match="unstubbed Supabase egress"):
        dbconn.table("learning_evidence_voids").select("event_id", filters={"user_id": "eq.u1"})
    with pytest.raises(RuntimeError, match="unstubbed Supabase egress"):
        dbconn.table("learning_evidence_voids").insert({"event_id": "e1"})
    with pytest.raises(RuntimeError, match="unstubbed Supabase egress"):
        dbconn.rpc("canopy_metrics", {})
    assert sockets == []


def test_after_monkeypatch_undo_a_model_call_is_refused(monkeypatch, sockets):
    from anthropic import Anthropic, AsyncAnthropic
    from google import genai

    monkeypatch.undo()
    message = {"model": "claude-haiku-5-5", "max_tokens": 1,
               "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
        Anthropic(api_key="dummy-key", max_retries=0).messages.create(**message)

    async def _agent_path():  # the agents build AsyncAnthropic
        await AsyncAnthropic(api_key="dummy-key", max_retries=0).messages.create(**message)

    with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
        asyncio.run(_agent_path())
    with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
        genai.Client(api_key="dummy-key").models.generate_content(
            model="gemini-2.5-flash-lite", contents="hi"
        )
    assert sockets == []


def test_after_monkeypatch_undo_a_jev_call_is_refused(monkeypatch, sockets):
    import httpx2

    from agents import _jev

    monkeypatch.undo()

    async def _call():
        async with httpx2.AsyncClient(transport=_jev._transport_override) as client:
            await client.get("https://api.typesafe.ai/v1/decide")

    with pytest.raises(httpx2.ConnectError, match="unstubbed Jev egress"):
        asyncio.run(_call())
    assert sockets == []


def test_after_monkeypatch_undo_an_email_send_is_refused(monkeypatch, sockets):
    import config
    from services import email_service

    monkeypatch.undo()
    assert config.RESEND_API_KEY == ""
    with pytest.raises(RuntimeError, match="unstubbed email egress"):
        email_service._client.post("https://api.resend.com/emails", json={})
    assert sockets == []


@pytest.mark.integration
def test_an_opt_in_lane_gets_the_live_client_for_that_test_only(_hermetic_egress_floor):
    """The opt-in lanes lift the floor with the test's own monkeypatch; nothing
    is called here, so the default lane runs it safely."""
    import db.connection as dbconn

    assert dbconn._client is _hermetic_egress_floor.supabase_client
