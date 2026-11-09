"""The session egress floor (spec §13 A123 review).

A test that calls `monkeypatch.undo()` undoes every per-test hermetic guard
that the conftest autouse fixtures installed with that same `monkeypatch`. The
A123 branch found such a test (tests/test_learning_review.py) that then sent a
real GET to the local stack at 127.0.0.1:54321.

`conftest._hermetic_egress_floor` sits under those guards for the whole
session, owned by a MonkeyPatch that no test can reach. Each test here undoes
its own monkeypatch first, as that test did. It then proves that the egress is
refused, and that no DNS lookup or socket connect was tried.

The opt-in lanes lift the floor. A test lifts it with its own monkeypatch. A
lane fixture that runs outside its test's own lift lifts it for its own block
only (`LiveEgress.supabase()`). An example is the integration lane's session
reseed, which runs before any test. The last tests here run that reseed from a
session fixture. They show that it reaches the live client, and that a unit
test in the same session still meets the floor.
"""
import asyncio
import importlib.util
import pathlib
import socket
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

INTEGRATION_CONFTEST = pathlib.Path(__file__).resolve().parent / "integration" / "conftest.py"


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


def _integration_conftest():
    """tests/integration/conftest.py, loaded as a module of its own. Its
    fixtures stay pytest's; this reads the reseed helper they call."""
    spec = importlib.util.spec_from_file_location(
        "_integration_conftest_under_test", INTEGRATION_CONFTEST
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def lane_session_reseed(_hermetic_egress_floor):
    """The integration lane's session reseed, run from a session fixture as
    `_require_local_stack` runs it: `_reseed_baseline(_hermetic_egress_floor)`.
    The seed itself is a recorder, so nothing is written and no request is
    sent. Records the database client the seed met, and the one in place
    before and after the reseed."""
    import db.connection as dbconn
    from db import seed_local_rich

    met = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(seed_local_rich, "main", lambda *_a, **_k: met.append(dbconn._client))
        before = dbconn._client
        _integration_conftest()._reseed_baseline(_hermetic_egress_floor)
        after = dbconn._client
    return SimpleNamespace(before=before, met=met, after=after)


@pytest.mark.integration
def test_an_integration_session_fixture_reaches_the_live_client(
    lane_session_reseed, _hermetic_egress_floor
):
    """The session reseed runs before any test's own lift. It lifts the floor
    for the seed only: the seed met the live client, and what was in place
    before the reseed is back after it."""
    live = _hermetic_egress_floor.supabase_client
    assert lane_session_reseed.met == [live]
    assert lane_session_reseed.before is not live
    assert lane_session_reseed.after is lane_session_reseed.before


def test_a_unit_test_in_the_same_session_still_meets_the_floor(
    lane_session_reseed, monkeypatch, sockets
):
    """A mixed session: the integration lane's session reseed has run (this
    test requests it, so it ran first). A unit test still gets its hermetic
    stub. After monkeypatch.undo() it meets the floor, never the client the
    reseed lifted to."""
    import db.connection as dbconn

    assert len(lane_session_reseed.met) == 1, "the session reseed ran first"
    assert isinstance(dbconn._client, MagicMock), "the per-test hermetic stub"
    monkeypatch.undo()
    assert dbconn._client is lane_session_reseed.after
    with pytest.raises(RuntimeError, match="unstubbed Supabase egress"):
        dbconn.table("misconceptions").select("id", filters={"user_id": "eq.u1"})
    assert sockets == []


def test_the_lift_ends_with_its_block_even_when_the_block_raises(
    _hermetic_egress_floor, sockets
):
    """A reseed that fails must not leave the live client behind for the tests
    after it. Nothing is called on the live client here."""
    import db.connection as dbconn

    stub = dbconn._client
    with pytest.raises(KeyError):
        with _hermetic_egress_floor.supabase() as client:
            assert client is _hermetic_egress_floor.supabase_client
            assert dbconn._client is client
            raise KeyError("the seed failed")
    assert dbconn._client is stub
    assert sockets == []
