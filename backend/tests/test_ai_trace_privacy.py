"""Public OTel and actual Pydantic AI exporter privacy contracts, no network."""

from __future__ import annotations

import json

import logfire
import pytest
from logfire.testing import SimpleSpanProcessor, TestExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Status, StatusCode

from services.ai_trace_privacy import ContentFreeTracerProvider


@pytest.fixture
def tracer():
    exporter = TestExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield ContentFreeTracerProvider(provider).get_tracer("synthetic"), exporter
    provider.shutdown()


def test_metadata_guard_covers_start_late_writes_events_status_and_exceptions(tracer):
    instrument, exporter = tracer
    error = RuntimeError("PRIVATE_EXCEPTION_TEXT")
    with pytest.raises(RuntimeError) as caught:
        with instrument.start_as_current_span(
            "PRIVATE_SPAN_NAME",
            attributes={
                "gen_ai.request.model": "gemini-2.5-flash-lite",
                "model_request_parameters": '{"PRIVATE_NESTED_KEY":"SHORT_PRIVATE_7"}',
                "gen_ai.usage.PRIVATE_UNTRUSTED_KEY": 1,
                "logfire.json_schema": '{"PRIVATE_SCHEMA_KEY":true}',
                "gen_ai.agent.name": "PRIVATE_USER_LABEL",
            },
        ) as span:
            span.set_attributes(
                {
                    "gen_ai.usage.input_tokens": 12,
                    "operation.cost": 0.001,
                    "gen_ai.output.messages": "PRIVATE_COMPLETION",
                    "unknown": "PRIVATE_UNKNOWN",
                }
            )
            span.set_attribute("model_request_parameters", "PRIVATE_INSTRUCTIONS")
            span.add_event("PRIVATE_EVENT_NAME", {"body": "PRIVATE_EVENT_TEXT"})
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, "PRIVATE_STATUS_DESCRIPTION"))
            raise error
    assert caught.value is error
    spans = exporter.exported_spans_as_dict()
    assert len(spans) == 1
    blob = json.dumps(spans)
    assert "PRIVATE_" not in blob
    attrs = spans[0]["attributes"]
    assert attrs["gen_ai.usage.input_tokens"] == 12 and attrs["operation.cost"] == 0.001
    assert (
        attrs["error.type"] == "RuntimeError"
        and attrs["gen_ai.request.model"] == "gemini-2.5-flash-lite"
    )
    assert not spans[0].get("events")
    assert exporter.exported_spans[0].status.status_code is StatusCode.ERROR
    assert exporter.exported_spans[0].status.description is None


def test_parent_child_context_and_non_context_span_updates_remain_operational(tracer):
    instrument, exporter = tracer
    with instrument.start_as_current_span("PRIVATE_PARENT") as parent:
        with instrument.start_as_current_span("PRIVATE_CHILD") as child:
            assert child.get_span_context().trace_id == parent.get_span_context().trace_id
            assert child.get_span_context().span_id != parent.get_span_context().span_id
            child.set_attribute("gen_ai.response.model", "gemini-2.5-flash")
    direct = instrument.start_span("PRIVATE_DIRECT", attributes={"gen_ai.tool.name": "read_source"})
    direct.update_name("PRIVATE_RENAME")
    direct.end()
    spans = exporter.exported_spans_as_dict()
    assert len(spans) == 3 and all(s["name"] == "AI operation" for s in spans)
    assert "PRIVATE_" not in json.dumps(spans)


@pytest.mark.parametrize(
    "value", [True, "PRIVATE_TEXT", {"PRIVATE_KEY": 1}, float("inf"), float("nan"), 10**1000]
)
def test_numeric_metadata_is_strict_finite_bounded_and_does_not_raise(tracer, value):
    instrument, exporter = tracer
    with instrument.start_as_current_span("synthetic", attributes={"operation.cost": value}):
        pass
    assert "operation.cost" not in exporter.exported_spans_as_dict()[0].get("attributes", {})


def test_actual_grader_explicit_settings_use_the_content_free_provider():
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import RequestUsage
    from agents.grader import grader_agent

    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[SimpleSpanProcessor(exporter)],
    )

    def respond(_messages, info):
        args = {
            "addresses_grader": False,
            "contradicts_reference": False,
            "item_results": ["PRIVATE_LABEL:no"],
            "support": [],
            "confidence": 0.9,
            "feedback_hint": "PRIVATE_FEEDBACK_HINT",
        }
        return ModelResponse(
            [ToolCallPart(info.output_tools[0].name, args)],
            model_name="synthetic-model",
            usage=RequestUsage(input_tokens=29, output_tokens=13),
        )

    with grader_agent.override(model=FunctionModel(respond)):
        result = grader_agent.run_sync("PRIVATE_STUDENT_ANSWER_AND_RUBRIC")
    assert result.output.feedback_hint == "PRIVATE_FEEDBACK_HINT"
    spans = exporter.exported_spans_as_dict()
    blob = json.dumps(spans)
    assert spans and "PRIVATE_" not in blob
    assert any(s.get("attributes", {}).get("gen_ai.usage.input_tokens") == 29 for s in spans)


@pytest.mark.parametrize(
    "record_exception,set_status_on_exception",
    [(False, False), (False, True), (True, False), (True, True)],
)
def test_context_exception_control_flags_are_preserved_without_text(
    tracer, record_exception, set_status_on_exception
):
    instrument, exporter = tracer
    error = RuntimeError("PRIVATE_CONTROL_FLOW_TEXT")
    with pytest.raises(RuntimeError) as caught:
        with instrument.start_as_current_span(
            "PRIVATE_CONTROL_FLOW_NAME",
            record_exception=record_exception,
            set_status_on_exception=set_status_on_exception,
        ):
            raise error
    assert caught.value is error
    span = exporter.exported_spans[0]
    assert (span.attributes.get("error.type") == "RuntimeError") is record_exception
    assert span.status.status_code is (
        StatusCode.ERROR if set_status_on_exception else StatusCode.UNSET
    )
    assert span.status.description is None
    assert not span.events
    assert "PRIVATE_" not in json.dumps(exporter.exported_spans_as_dict())


def test_late_links_forward_context_but_never_raw_link_attributes(tracer):
    instrument, exporter = tracer
    with instrument.start_as_current_span("synthetic") as original:
        context = original.get_span_context()
    later = instrument.start_span("synthetic")
    later.add_link(
        context,
        {"gen_ai.request.model": "gemini-2.5-flash-lite", "PRIVATE_LINK_KEY": "PRIVATE_LINK_BODY"},
    )
    later.end()
    links = exporter.exported_spans[-1].links
    assert len(links) == 1 and links[0].context == context
    assert dict(links[0].attributes) == {"gen_ai.request.model": "gemini-2.5-flash-lite"}
    assert "PRIVATE_" not in json.dumps(exporter.exported_spans_as_dict())


def test_async_decorator_keeps_recording_context_through_await_and_concurrent_calls(tracer):
    import asyncio
    from opentelemetry import trace

    instrument, exporter = tracer

    @instrument.start_as_current_span("PRIVATE_ASYNC_NAME")
    async def work(value):
        before = trace.get_current_span().get_span_context()
        assert trace.get_current_span().is_recording()
        await asyncio.sleep(0)
        assert trace.get_current_span().is_recording()
        assert trace.get_current_span().get_span_context() == before
        return value, before.span_id

    async def run():
        return await asyncio.gather(work(1), work(2))

    values = asyncio.run(run())
    assert [v[0] for v in values] == [1, 2] and values[0][1] != values[1][1]
    assert len(exporter.exported_spans) == 2
    assert "PRIVATE_" not in json.dumps(exporter.exported_spans_as_dict())


def test_sync_decorator_is_reusable_and_preserves_function_result(tracer):
    from opentelemetry import trace

    instrument, exporter = tracer

    @instrument.start_as_current_span("PRIVATE_SYNC_NAME")
    def work(value):
        assert trace.get_current_span().is_recording()
        return value + 1

    assert work(1) == 2 and work(2) == 3
    assert len(exporter.exported_spans) == 2
