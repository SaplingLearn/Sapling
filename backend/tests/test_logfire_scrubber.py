"""No student content may reach Logfire (services/logfire_scrubber.py).

Three layers are covered here:

* the pure transformation (`scrub_attribute` / `redact` / `strip_query`) and
  the Logfire callback shape (`scrub_value`);
* REAL spans: a pydantic-ai agent run with a tool call, and a FastAPI request
  with a body and a query string, exported through Logfire configured exactly
  as main.py configures it, into an in-memory exporter. The assertion is the
  property itself: no run of `_WINDOW` consecutive characters of any content
  string survives anywhere in the exported spans;
* main.py's wiring (parsed, not imported) so a later edit cannot quietly turn
  content capture back on.

The content strings are drawn from letters that never occur in hex, so a
trace id or a sha256 fingerprint can never produce a false match.
"""

from __future__ import annotations

import ast
import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.logfire_scrubber import (
    ALL_PATTERNS,
    PYDANTIC_AI_INSTRUMENTATION,
    QueryStringStripProcessor,
    redact,
    scrub_attribute,
    scrub_value,
    strip_query,
    strip_query_request_hook,
)

# Any run of this many characters of content found in an exported span is a leak.
_WINDOW = 12
_NON_HEX = "GHJKLMNPQRSTUVWXYZ"


def _content(words: int = 40) -> str:
    """Unique, non-hex 'student text' (see module docstring)."""
    return " ".join(
        "".join(secrets.choice(_NON_HEX) for _ in range(7)) for _ in range(words)
    )


def _assert_no_content(blob: str, *contents: str) -> None:
    for text in contents:
        for i in range(0, max(1, len(text) - _WINDOW + 1)):
            window = text[i:i + _WINDOW]
            assert window not in blob, f"content leaked into a span: {window!r}"


# ── pure transformation ─────────────────────────────────────────────────────


@pytest.mark.parametrize("body", ["", "7", "student@example.invalid", "短い解答", "essay " * 300])
def test_every_content_value_is_length_and_hash_only(body):
    result = scrub_attribute("gen_ai.prompt", body)
    assert result.startswith("[redacted, type:string,") and "sha256:" in result
    assert f"length:{len(body)}" in result
    if len(body) > 1:
        assert body not in result  # no preview, however short
    fp = result.split("sha256:")[1].rstrip("]")
    assert len(fp) == 16 and all(c in "0123456789abcdef" for c in fp)


@pytest.mark.parametrize(
    "name",
    [
        # pydantic-ai 1.107 / logfire 4.37 names (see the scrubber docstring)
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "pydantic_ai.all_messages",
        "all_messages_events",
        "final_result",
        "tool_arguments",
        "tool_response",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "events",
        # other GenAI conventions
        "gen_ai.prompt",
        "gen_ai.completion",
        "input.value",
        "output.value",
        "user_prompt",
        "content",
    ],
)
def test_content_attribute_names_are_redacted(name):
    text = _content(3)
    result = scrub_attribute(name, text)
    assert text not in result and result.startswith("[redacted,")


@pytest.mark.parametrize(
    "value",
    [42, True, None, ["7", "student@example.invalid"],
     {"UNSAFE_STUDENT_KEY": {"answer": "7", "other": ["student@example.invalid"]}}],
)
def test_structured_values_are_replaced_whole_keys_included(value):
    result = scrub_attribute("tool_arguments", value)
    assert isinstance(result, str) and result.startswith("[redacted,")
    assert "UNSAFE_STUDENT_KEY" not in result and "student@example.invalid" not in result


def test_unserializable_and_cyclic_values_fail_closed_without_repr():
    class Sensitive:
        def __repr__(self):  # pragma: no cover — must never be called
            pytest.fail("must not stringify unknown objects")

        __str__ = __repr__

    assert redact(Sensitive()) == "[redacted]"
    cyclic: list = []
    cyclic.append(cyclic)
    assert redact(cyclic) == "[redacted]"
    assert redact(float("nan")) == "[redacted]"


def test_non_content_metadata_is_untouched():
    assert scrub_attribute("request_id", "req-123") == "req-123"
    assert scrub_attribute("http.route", "/notes/{id}") == "/notes/{id}"
    assert scrub_attribute("gen_ai.request.model", "claude-haiku-5-5") == "claude-haiku-5-5"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.example/x/y?q=my+essay&id=1#frag", "https://api.example/x/y"),
        ("/api/notes/search?q=photosynthesis", "/api/notes/search"),
        ("/api/notes/123", "/api/notes/123"),
    ],
)
def test_strip_query(url, expected):
    assert strip_query(url) == expected
    assert scrub_attribute("http.url", url) == expected
    assert scrub_attribute("url.full", url) == expected
    assert scrub_attribute("http.target", url) == expected


def test_bare_query_attribute_is_redacted():
    out = scrub_attribute("url.query", "q=my+private+essay")
    assert out.startswith("[redacted,") and "essay" not in out


def test_callback_redacts_routed_content_but_delegates_default_secrets():
    risky = SimpleNamespace(path=("attributes", "all_messages_events", 0, "content"), value="7")
    assert scrub_value(risky).startswith("[redacted,")
    tool = SimpleNamespace(path=("attributes", "gen_ai.tool.call.result"), value='{"a": 1}')
    assert scrub_value(tool).startswith("[redacted,")
    url = SimpleNamespace(path=("attributes", "http.request.url"), value="https://h/p?q=x")
    assert scrub_value(url) == "https://h/p"
    secret = SimpleNamespace(path=("attributes", "password"), value="PRIVATE_PASSWORD")
    assert scrub_value(secret) is None  # Logfire's full redaction applies


def test_url_pattern_never_matches_a_value_that_merely_mentions_url():
    import re

    pat = re.compile("|".join(ALL_PATTERNS), re.IGNORECASE)
    assert not pat.search("see the url in the docs")
    assert pat.search("url.full") and pat.search("http.target")


# ── real spans through Logfire, configured as main.py configures it ─────────


@pytest.fixture
def exporter():
    import logfire
    from logfire.testing import SimpleSpanProcessor, TestExporter

    import main  # noqa: F401 — its import-time logfire.configure must run BEFORE ours

    exp = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        # Same order as main.py: the strip processor first, then the exporter.
        additional_span_processors=[QueryStringStripProcessor(), SimpleSpanProcessor(exp)],
        scrubbing=logfire.ScrubbingOptions(callback=scrub_value, extra_patterns=list(ALL_PATTERNS)),
    )
    return exp


def _run_agent_with_tool(instrumentation: dict, prompt: str, system: str,
                         tool_arg: str, tool_result: str, answer: str):
    """One agent run: the model calls `lookup(topic=tool_arg)`, the tool
    returns `tool_result`, the model answers `answer`."""
    import logfire
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def model(messages, info):
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart("lookup", {"topic": tool_arg})])
        return ModelResponse(parts=[TextPart(answer)])

    agent = Agent(FunctionModel(model), system_prompt=system, name="scrub_probe")

    @agent.tool_plain
    def lookup(topic: str) -> str:
        return tool_result

    logfire.instrument_pydantic_ai(agent, **instrumentation)
    result = agent.run_sync(prompt)
    assert result.output == answer
    return agent


def test_agent_run_with_tool_exports_no_content(exporter):
    prompt, system = _content(), _content()
    tool_arg, tool_result, answer = _content(5), _content(), _content()
    _run_agent_with_tool(PYDANTIC_AI_INSTRUMENTATION, prompt, system, tool_arg, tool_result, answer)

    spans = exporter.exported_spans_as_dict(_include_pending_spans=True)
    names = {s["name"] for s in spans}
    assert any("tool" in n for n in names), names  # a tool span really ran
    assert any("chat" in n for n in names), names  # and a model request span
    blob = json.dumps(spans, ensure_ascii=False)
    _assert_no_content(blob, prompt, system, tool_arg, tool_result, answer)
    # The useful metadata survives.
    assert "lookup" in blob and "gen_ai.usage.input_tokens" in blob


@pytest.mark.parametrize("version", [2, 3])
def test_callback_alone_redacts_tool_and_result_attributes(exporter, version):
    """Defence in depth: even with content capture ON (a regression of layer
    1), the attributes Logfire routes to the callback — the final result and
    the tool-call arguments/results, under both naming versions — carry no
    content. (The SAFE-keyed message attributes are why layer 1 exists.)"""
    tool_arg, tool_result, answer = _content(5), _content(), _content()
    _run_agent_with_tool({"include_content": True, "version": version},
                         _content(), _content(), tool_arg, tool_result, answer)

    spans = exporter.exported_spans_as_dict(_include_pending_spans=True)
    checked = 0
    for span in spans:
        for key in ("final_result", "tool_arguments", "tool_response",
                    "gen_ai.tool.call.arguments", "gen_ai.tool.call.result"):
            if key in span["attributes"]:
                checked += 1
                val = json.dumps(span["attributes"][key], ensure_ascii=False)
                assert "redacted" in val
                _assert_no_content(val, tool_arg, tool_result, answer)
    assert checked >= 3  # final_result + the tool span's arguments and result


def test_request_query_string_and_body_never_reach_spans(exporter):
    import logfire
    from fastapi import FastAPI, Query
    from fastapi.testclient import TestClient
    from pydantic import BaseModel

    from main import _drop_request_arguments  # noqa: PLC2701 — the mapper we ship

    app = FastAPI()

    class NoteIn(BaseModel):
        title: str
        body: str

    @app.post("/notes/{note_id}")
    def create_note(note_id: str, note: NoteIn, q: str = Query("")):
        return {"ok": True}

    logfire.instrument_fastapi(
        app,
        capture_headers=False,
        extra_spans=False,
        request_attributes_mapper=_drop_request_arguments,
        server_request_hook=strip_query_request_hook,
    )
    body, query = _content(), _content(4)
    TestClient(app).post(f"/notes/note-123?q={query.replace(' ', '+')}",
                         json={"title": "Bio", "body": body})

    spans = exporter.exported_spans_as_dict(_include_pending_spans=True)
    assert spans
    blob = json.dumps(spans, ensure_ascii=False)
    _assert_no_content(blob, body, query, query.replace(" ", "+"))
    server = [s for s in spans if s["attributes"].get("http.route") == "/notes/{note_id}"]
    assert server
    attrs = server[-1]["attributes"]
    assert attrs.get("http.method") == "POST"
    assert "fastapi.arguments.values" not in attrs
    for key in ("http.target", "http.url", "url.full"):
        if key in attrs:
            assert "?" not in attrs[key]
    assert "?" not in attrs.get("logfire.msg", "")


# ── main.py wiring (parsed, never imported for this) ────────────────────────


def _main_calls(attr: str) -> list[ast.Call]:
    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8"))
    return [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    ]


def test_settings_disable_agent_content_capture():
    assert PYDANTIC_AI_INSTRUMENTATION == {"include_content": False, "include_binary_content": False}


def test_main_instruments_pydantic_ai_without_content():
    calls = _main_calls("instrument_pydantic_ai")
    assert len(calls) == 1
    (call,) = calls
    assert not call.args
    starred = [kw for kw in call.keywords if kw.arg is None]
    assert len(starred) == 1 and isinstance(starred[0].value, ast.Name)
    assert starred[0].value.id == "PYDANTIC_AI_INSTRUMENTATION"
    assert all(kw.arg is None for kw in call.keywords), "no override of the content settings"


def test_main_configures_the_scrubber_with_every_pattern():
    (call,) = _main_calls("ScrubbingOptions")
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    assert isinstance(kwargs["callback"], ast.Name) and kwargs["callback"].id == "scrub_value"
    assert "ALL_PATTERNS" in ast.unparse(kwargs["extra_patterns"])


def test_main_registers_the_query_string_processor():
    (call,) = _main_calls("configure")
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    assert "QueryStringStripProcessor()" in ast.unparse(kwargs["additional_span_processors"])


def test_query_string_processor_strips_at_start():
    class FakeSpan:
        def __init__(self):
            self.attributes = {"http.target": "/a?q=essay", "url.full": "https://h/a?q=essay#x",
                               "url.query": "q=essay", "http.route": "/a"}

        def set_attribute(self, k, v):
            self.attributes[k] = v

    span = FakeSpan()
    QueryStringStripProcessor().on_start(span)
    assert span.attributes["http.target"] == "/a"
    assert span.attributes["url.full"] == "https://h/a"
    assert "essay" not in span.attributes["url.query"]
    assert span.attributes["http.route"] == "/a"


def _instrument_fastapi_kwargs():
    calls = _main_calls("instrument_fastapi")
    return {kw.arg: kw.value for kw in calls[0].keywords} if calls else None


def test_instrument_fastapi_drops_arguments_headers_and_query_strings():
    """Request bodies/params/headers and query strings must never leave the
    process; flipping any of these would ship un-scrubbed student content."""
    kwargs = _instrument_fastapi_kwargs()
    assert kwargs is not None, "logfire.instrument_fastapi(app) must be called in main.py"
    assert "request_attributes_mapper" in kwargs
    hook = kwargs.get("server_request_hook")
    assert isinstance(hook, ast.Name) and hook.id == "strip_query_request_hook"
    for flag in ("extra_spans", "capture_headers"):
        val = kwargs.get(flag)
        if val is not None:
            assert isinstance(val, ast.Constant) and val.value is False
