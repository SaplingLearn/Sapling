"""PKG-14 review fix round (A92): a legacy turn records llm_usage.session_id only
for the caller's own session, so cost cannot be moved onto another student's
session in the per-session report."""

from unittest.mock import MagicMock

import pytest

from routes import learn
from tests.split_patches import patch_tutor


def _sessions(rows):
    t = MagicMock()
    t.select.return_value = rows
    return MagicMock(return_value=t)


@pytest.fixture(autouse=True)
def _no_pending():
    saved = dict(learn.PENDING_SESSIONS)
    learn.PENDING_SESSIONS.clear()
    yield
    learn.PENDING_SESSIONS.clear()
    learn.PENDING_SESSIONS.update(saved)


def test_own_session_is_recorded():
    with patch_tutor("table", _sessions([{"user_id": "u-a"}])):
        assert learn._usage_session_id("s-1", "u-a") == "s-1"


def test_someone_elses_session_records_null():
    with patch_tutor("table", _sessions([{"user_id": "u-b"}])):
        assert learn._usage_session_id("s-1", "u-a") is None


def test_missing_session_records_null():
    with patch_tutor("table", _sessions([])):
        assert learn._usage_session_id("s-404", "u-a") is None


def test_no_session_id_records_null_without_a_read():
    tbl = _sessions([{"user_id": "u-a"}])
    with patch_tutor("table", tbl):
        assert learn._usage_session_id(None, "u-a") is None
        assert learn._usage_session_id("", "u-a") is None
    tbl.assert_not_called()


def test_pending_session_counts_only_for_its_user_without_a_read():
    learn.PENDING_SESSIONS["s-p"] = {"user_id": "u-a"}
    tbl = _sessions([])
    with patch_tutor("table", tbl):
        assert learn._usage_session_id("s-p", "u-a") == "s-p"
        assert learn._usage_session_id("s-p", "u-b") is None
    tbl.assert_not_called()


def test_a_failed_read_records_null_and_never_raises():
    t = MagicMock()
    t.select.side_effect = RuntimeError("db down")
    with patch_tutor("table", MagicMock(return_value=t)):
        assert learn._usage_session_id("s-1", "u-a") is None


def test_every_body_sourced_legacy_usage_site_goes_through_the_owner_check():
    import inspect

    from services.tutor import run, streams, turns

    # #118 (spec §13 A149): the run sites live in services/tutor/. /chat (JSON
    # via _chat_via_agent), /chat/stream and /action resolve the owner check
    # ONCE per turn (off the event loop, #117) and record both the run and a
    # continuation against it; a continuation without a resolved id reads it.
    src = "".join(inspect.getsource(m) for m in (run, streams, turns))
    assert src.count("session_id=_usage_session_id(") == 0
    # Every binding of a turn's usage_session_id goes through the owner check
    # (/chat JSON, /action, /chat/stream: three resolution sites).
    import ast

    bound = [
        ast.unparse(node.value)
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "usage_session_id" for t in node.targets)
    ]
    assert len(bound) == 3 and all("_usage_session_id" in b for b in bound), bound
    assert inspect.getsource(streams).count(
        "usage_session_id = await asyncio.to_thread(_usage_session_id, body.session_id, body.user_id)"
    ) == 1
    # The continuation never reads ownership itself: its caller hands it the
    # turn's resolved id (pinned per call site below).
    assert "_usage_session_id" not in inspect.getsource(run._continuation_text)


#: Every `_continuation_text` call site -> the `usage_session_id=` it passes.
#: "usage_session_id" must be bound in that function from
#: `_usage_session_id(...)` (the A92 owner check); "session_id" is allowed only
#: for the openers, whose id the server just minted.
CONTINUATION_SITES = {
    ("services/tutor/turns.py", "_start_session_agent"): "session_id",
    ("services/tutor/turns.py", "_chat_via_agent"): "usage_session_id",
    ("services/tutor/turns.py", "_action_turn"): "usage_session_id",
    ("services/tutor/streams.py", "chat_stream"): "usage_session_id",
    ("services/tutor/streams.py", "start_session_stream"): "session_id",
}


def _continuation_calls():
    """(file, enclosing top-level function) -> [usage_session_id expr, ...]."""
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    found: dict[tuple[str, str], list[str | None]] = {}
    for rel in ("services/tutor/turns.py", "services/tutor/streams.py", "services/tutor/run.py"):
        tree = ast.parse((backend / rel).read_text())
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_continuation_text":
                    kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
                    found.setdefault((rel, fn.name), []).append(kw.get("usage_session_id"))
    return found


def test_every_continuation_records_against_an_owner_checked_or_minted_session():
    """A92: a continuation's llm_usage.session_id is never a body-supplied id
    that skipped the owner check — one student could otherwise move cost onto
    another's session in the per-session report."""
    import ast
    import inspect

    from services.tutor import streams, turns

    calls = _continuation_calls()
    assert {site: set(exprs) for site, exprs in calls.items()} == {
        site: {expr} for site, expr in CONTINUATION_SITES.items()
    }
    modules = {"services/tutor/turns.py": turns, "services/tutor/streams.py": streams}
    for (rel, fn_name), expr in CONTINUATION_SITES.items():
        if expr != "usage_session_id":
            continue
        fn = ast.parse(inspect.getsource(getattr(modules[rel], fn_name)))
        bound = [
            ast.unparse(node.value)
            for node in ast.walk(fn)
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "usage_session_id" for t in node.targets)
        ]
        assert bound and all("_usage_session_id" in b for b in bound), (rel, fn_name, bound)


def test_a_continuation_records_against_the_turns_resolved_session_without_a_second_read(monkeypatch):
    """A textless turn's continuation reuses the id the turn already resolved:
    no second ownership read, and the same llm_usage.session_id."""
    import asyncio
    from contextlib import nullcontext
    from unittest.mock import AsyncMock

    from services.tutor import run

    def no_read(*_a, **_k):
        raise AssertionError("the continuation re-read session ownership")

    recorded = {}
    monkeypatch.setattr(run, "_usage_session_id", no_read)
    monkeypatch.setattr(run, "record_agent_usage", lambda result, **kw: recorded.update(kw) or result)
    monkeypatch.setattr(run, "_new_run_text", lambda result: "rescued")
    agent = MagicMock()
    agent.override.return_value = nullcontext()
    agent.run = AsyncMock(return_value=MagicMock())
    first = MagicMock()
    first.all_messages.return_value = []
    deps = MagicMock(session_id="s-1", user_id="u-a")

    out = asyncio.run(run._continuation_text(
        agent, first, {"deps": deps}, request_id="r-1", usage_session_id="s-1",
    ))
    assert out == "rescued"
    assert recorded["session_id"] == "s-1" and recorded["request_id"] == "r-1"
