"""Hermetic, real-exporter contracts for content-free telemetry."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from services.logfire_scrubber import EXTRA_PATTERNS, scrub_attribute, scrub_value


@pytest.mark.parametrize("body", ["", "7", "student@example.invalid", "短い解答", "essay " * 300])
def test_every_prompt_length_is_redacted_without_a_preview(body):
    result = scrub_attribute("gen_ai.prompt", body)
    assert result.startswith("[redacted, type:string,") and "sha256:" in result
    assert f"length:{len(body)}" in result
    if len(body) > 1:
        assert body not in result
    assert len(result.split("sha256:")[1].rstrip("]")) == 16


@pytest.mark.parametrize(
    "value",
    [
        42,
        True,
        None,
        ["7", "student@example.invalid"],
        {"UNSAFE_STUDENT_KEY": {"answer": "7", "other": ["student@example.invalid"]}},
    ],
)
def test_whole_risky_value_replaces_nested_keys_values_and_numeric_answers(value):
    result = scrub_attribute("all_messages_events", value)
    assert isinstance(result, str) and result.startswith("[redacted,")
    assert "UNSAFE_STUDENT_KEY" not in result and "student@example.invalid" not in result
    assert '"answer"' not in result


def test_unserializable_and_cyclic_values_fail_closed_without_repr():
    class Sensitive:
        def __str__(self):
            pytest.fail("must not stringify unknown objects")

        __repr__ = __str__

    assert scrub_attribute("content", Sensitive()) == "[redacted]"
    cyclic = []
    cyclic.append(cyclic)
    assert scrub_attribute("content", cyclic) == "[redacted]"
    assert scrub_attribute("content", float("nan")) == "[redacted]"


def test_non_risky_metadata_is_untouched():
    assert scrub_attribute("request_id", "req-123") == "req-123"
    assert scrub_attribute("http.route", "/notes/{id}") == "/notes/{id}"


def test_callback_redacts_routed_content_but_delegates_default_secrets():
    risky = SimpleNamespace(path=("attributes", "all_messages_events", 0, "content"), value="7")
    assert scrub_value(risky).startswith("[redacted,")
    secret = SimpleNamespace(path=("attributes", "password"), value="PRIVATE_PASSWORD")
    assert scrub_value(secret) is None


def test_agent_instrumentation_explicitly_disables_content_and_binary_capture():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "instrument_pydantic_ai"
    ]
    assert len(calls) == 1
    kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
    for name in ("include_content", "include_binary_content"):
        assert isinstance(kwargs[name], ast.Constant) and kwargs[name].value is False
    provider = kwargs["tracer_provider"]
    assert isinstance(provider, ast.Call) and isinstance(provider.func, ast.Name)
    assert provider.func.id == "content_free_tracer_provider"


def test_legacy_json_body_is_redacted_by_the_real_exporter_callback():
    import logfire
    from logfire.testing import SimpleSpanProcessor, TestExporter

    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
        scrubbing=logfire.ScrubbingOptions(
            callback=scrub_value, extra_patterns=list(EXTRA_PATTERNS)
        ),
    )
    raw = json.dumps(
        {"UNSAFE_STUDENT_KEY": {"answer": "SHORT_PRIVATE_7", "email": "student@example.invalid"}}
    )
    with logfire.span("synthetic legacy export", user_prompt=raw, request_id="safe-request"):
        pass
    blob = json.dumps(exporter.exported_spans_as_dict())
    assert "UNSAFE_STUDENT_KEY" not in blob and "SHORT_PRIVATE_7" not in blob
    assert "student@example.invalid" not in blob and "sha256:" in blob and "safe-request" in blob


def test_agent_tool_result_and_dynamic_output_keys_never_reach_real_exporter(monkeypatch):
    import logfire
    from logfire.testing import SimpleSpanProcessor, TestExporter
    from pydantic_ai import Agent, BinaryContent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import RequestUsage

    class Output(BaseModel):
        value: dict[str, str]

    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
        scrubbing=logfire.ScrubbingOptions(
            callback=scrub_value, extra_patterns=list(EXTRA_PATTERNS)
        ),
    )
    monkeypatch.setattr(Agent, "_instrument_default", Agent._instrument_default)
    from services.ai_trace_privacy import content_free_tracer_provider

    logfire.instrument_pydantic_ai(
        include_content=False,
        include_binary_content=False,
        tracer_provider=content_free_tracer_provider(),
    )
    calls = []

    def respond(_messages, info):
        calls.append(True)
        if len(calls) == 1:
            parts = [ToolCallPart("read_source", {"learner_text": "PRIVATE_TOOL_ARG"})]
        else:
            parts = [
                ToolCallPart(
                    info.output_tools[0].name,
                    {"value": {"PRIVATE_DYNAMIC_OUTPUT_KEY": "SHORT_PRIVATE_7"}},
                )
            ]
        return ModelResponse(
            parts,
            usage=RequestUsage(input_tokens=23, output_tokens=11),
            model_name="synthetic-model",
        )

    agent = Agent(
        FunctionModel(respond, model_name="synthetic-model"),
        instructions="PRIVATE_SYSTEM_INSTRUCTION",
        output_type=Output,
    )

    @agent.tool_plain
    def read_source(learner_text: str) -> dict[str, str]:
        assert learner_text == "PRIVATE_TOOL_ARG"
        return {"PRIVATE_DYNAMIC_TOOL_KEY": "student@example.invalid"}

    result = agent.run_sync(
        [
            "PRIVATE_STUDENT_PROMPT",
            BinaryContent(data=b"PRIVATE_BINARY_CONTENT", media_type="image/png"),
        ]
    )
    assert (
        result.output.value == {"PRIVATE_DYNAMIC_OUTPUT_KEY": "SHORT_PRIVATE_7"} and len(calls) == 2
    )
    spans = exporter.exported_spans_as_dict()
    blob = json.dumps(spans)
    for private in (
        "PRIVATE_SYSTEM_INSTRUCTION",
        "PRIVATE_TOOL_ARG",
        "PRIVATE_DYNAMIC_OUTPUT_KEY",
        "SHORT_PRIVATE_7",
        "PRIVATE_DYNAMIC_TOOL_KEY",
        "student@example.invalid",
        "PRIVATE_STUDENT_PROMPT",
        "PRIVATE_BINARY_CONTENT",
    ):
        assert private not in blob
    assert spans and "synthetic-model" in blob
    assert any(s["attributes"].get("gen_ai.usage.input_tokens") == 23 for s in spans)


# ── instrument_fastapi wiring: no request bodies/headers may egress ──────────
#
# The scrubber only sees the attributes Logfire routes through it — and it does
# NOT route the FastAPI endpoint-argument attribute (`fastapi.arguments.values`)
# nor `http.url`/`logfire.msg`. That argument attribute otherwise carries the
# request body and params: chat messages, note bodies, quiz answers, uploaded
# document text. A body field named e.g. `body` matches no risky pattern, so
# scrubbing can't be relied on here. main.py therefore drops the arguments at
# the source via a `request_attributes_mapper` that returns None, keeps headers
# off (`capture_headers=False`), and keeps the extra argument/endpoint spans off
# (`extra_spans=False`). These guards fail loudly if any of that regresses.


def _instrument_fastapi_kwargs():
    """Parse main.py (no import/side effects) and return the keyword
    arguments passed to logfire.instrument_fastapi(...), as an AST map."""
    import ast
    from pathlib import Path

    main_src = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(main_src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "instrument_fastapi"
        ):
            return {kw.arg: kw.value for kw in node.keywords}
    return None


def test_instrument_fastapi_is_wired():
    """FastAPI request traces (success criterion #1) require this call."""
    assert _instrument_fastapi_kwargs() is not None, (
        "logfire.instrument_fastapi(app) must be called in main.py so FastAPI "
        "request traces reach Logfire."
    )


def test_instrument_fastapi_drops_arguments_and_headers():
    """Egress guard: request bodies/params/headers must never leave the process.

    - `request_attributes_mapper` must be provided (it drops `fastapi.arguments`).
    - `capture_headers` / `extra_spans`, if present, must be explicitly False.
    Flipping any of these would ship un-scrubbed student content.
    """
    import ast

    kwargs = _instrument_fastapi_kwargs()
    assert kwargs is not None
    assert "request_attributes_mapper" in kwargs, (
        "instrument_fastapi must pass request_attributes_mapper to drop request "
        "bodies/params (fastapi.arguments.values), which the scrubber can't reach."
    )
    for flag in ("extra_spans", "capture_headers"):
        val = kwargs.get(flag)
        if val is not None:
            assert isinstance(val, ast.Constant) and val.value is False, (
                f"instrument_fastapi({flag}=...) must be False so request "
                f"bodies/headers are not sent to Logfire."
            )


def test_request_body_does_not_appear_in_exported_spans():
    """End-to-end: fire a real request with a body + query and assert the body
    never lands in any exported span attribute.

    This is the concrete proof of "no student content leaves un-fingerprinted"
    for the request-trace egress path introduced by instrument_fastapi. It
    mirrors main.py's wiring (mapper drops args) against an in-memory exporter.
    """
    import json

    import logfire
    from fastapi import FastAPI, Query
    from fastapi.testclient import TestClient
    from logfire.testing import SimpleSpanProcessor, TestExporter
    from pydantic import BaseModel

    from main import _drop_request_arguments  # noqa: PLC2701 — the exact mapper we ship

    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )

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
    )

    secret = "MITOCHONDRIA_POWERHOUSE_ESSAY_BODY"
    TestClient(app).post("/notes/note-123", json={"title": "Bio Notes", "body": secret + " " * 0})

    spans = exporter.exported_spans_as_dict()
    assert spans, "instrument_fastapi should emit a request span"
    blob = json.dumps(spans)
    assert secret not in blob, (
        "request body leaked into a span attribute — the request_attributes_mapper "
        "is not dropping fastapi.arguments.values"
    )
    # Sanity: the span still carries the useful ops fields.
    attrs = spans[-1]["attributes"]
    assert attrs.get("http.route") == "/notes/{note_id}"
    assert attrs.get("http.method") == "POST"
    assert "fastapi.arguments.values" not in attrs
