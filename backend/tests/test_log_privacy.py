"""Process log privacy (services/log_privacy.py): no outbound URL, no model
output in a traceback."""

from __future__ import annotations

import io
import logging

import pytest

from services import log_privacy


# ---------------------------------------------------------------------------
# Outbound: httpx logs each request URL at INFO (query string included), and
# PostgREST filters carry emails there. Both entry points quiet it.
# ---------------------------------------------------------------------------


@pytest.fixture
def root_at_info():
    """Root logger at INFO with a capturing handler, as both entry points run;
    the httpx/httpcore levels are restored afterwards."""
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    saved = {n: logging.getLogger(n).level for n in log_privacy.HTTP_CLIENT_LOGGERS}
    old_root = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_root)
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


def _httpx_request(url: str) -> None:
    import httpx

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as client:
        assert client.get(url).status_code == 200


_EMAIL_URL = "https://example.supabase.co/rest/v1/waitlist?or=(email.ilike.student%40bu.edu)"


def test_httpx_logs_the_url_at_info_unless_quieted(root_at_info):
    """The leak is real: an unquieted httpx at INFO writes the full URL."""
    for name in log_privacy.HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    _httpx_request(_EMAIL_URL)
    assert "student%40bu.edu" in root_at_info.getvalue()


def test_quieted_httpx_request_at_info_logs_no_url(root_at_info):
    log_privacy.quiet_http_clients()
    _httpx_request(_EMAIL_URL)
    out = root_at_info.getvalue()
    assert "student" not in out and "waitlist" not in out and "supabase" not in out


def test_main_quiets_http_clients():
    import main  # noqa: F401

    for name in log_privacy.HTTP_CLIENT_LOGGERS:
        assert logging.getLogger(name).level >= logging.WARNING


def test_worker_logging_quiets_http_clients(root_at_info):
    from worker.__main__ import _configure_logging

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    try:
        for name in log_privacy.HTTP_CLIENT_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)
        _configure_logging("text")
        for name in log_privacy.HTTP_CLIENT_LOGGERS:
            assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
    finally:
        root.handlers[:] = saved_handlers


# ---------------------------------------------------------------------------
# Tracebacks: an output-validation failure carries the model's text (which is
# derived from student content). The record factory redacts it.
# ---------------------------------------------------------------------------

SECRET = "STUDENT_ESSAY_SENTENCE_7f3a"


def _validation_failure() -> BaseException:
    """A real pydantic-ai run whose model keeps answering invalid output."""
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel

    class Out(BaseModel):
        score: int = Field(ge=0)

    def bad(messages, info):
        return ModelResponse(parts=[TextPart(f'{{"score": "{SECRET}"}}')])

    agent = Agent(FunctionModel(bad), output_type=Out, output_retries=1)
    try:
        agent.run_sync("x")
    except Exception as exc:  # noqa: BLE001 - the exception is the subject
        return exc
    raise AssertionError("the run should have failed validation")


@pytest.fixture
def redacting_handler():
    log_privacy.install_exception_redaction()
    logger = logging.getLogger("test.log_privacy")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    try:
        yield logger, stream
    finally:
        logger.removeHandler(handler)
        logger.propagate = True


def test_the_unredacted_traceback_would_carry_the_model_output():
    import traceback

    exc = _validation_failure()
    assert SECRET in "".join(traceback.format_exception(exc))


def test_logger_exception_on_a_validation_failure_carries_no_model_output(redacting_handler):
    logger, stream = redacting_handler
    exc = _validation_failure()
    try:
        raise exc
    except Exception:
        logger.exception("agent produced unusable output")
    out = stream.getvalue()
    assert SECRET not in out
    assert "agent produced unusable output" in out
    assert "UnexpectedModelBehavior" in out and "Traceback" in out


def test_exc_info_kwarg_is_redacted_too(redacting_handler):
    logger, stream = redacting_handler
    logger.warning("guardrails tripped", exc_info=_validation_failure())
    assert SECRET not in stream.getvalue()


def test_worker_json_formatter_uses_the_redacted_text():
    from worker.__main__ import _JsonFormatter

    log_privacy.install_exception_redaction()
    exc = _validation_failure()
    record = logging.getLogger("x").makeRecord(
        "x", logging.ERROR, __file__, 1, "boom", (), (type(exc), exc, exc.__traceback__),
    )
    assert SECRET not in _JsonFormatter().format(record)


def test_unrelated_exceptions_keep_their_traceback(redacting_handler):
    logger, stream = redacting_handler
    try:
        raise KeyError("course_42")
    except KeyError:
        logger.exception("lookup failed")
    out = stream.getvalue()
    assert "KeyError: 'course_42'" in out


@pytest.mark.parametrize("make", ["validation_error", "model_behavior_body", "model_retry"])
def test_safe_exception_text_drops_inputs(make):
    from pydantic import BaseModel
    from pydantic_ai.exceptions import ModelRetry, UnexpectedModelBehavior

    class M(BaseModel):
        n: int

    if make == "validation_error":
        try:
            M(n=SECRET)
        except Exception as e:  # noqa: BLE001
            exc = e
    elif make == "model_behavior_body":
        exc = UnexpectedModelBehavior("Received empty model response", body=SECRET)
    else:
        exc = ModelRetry(f"answer {SECRET} not among the options")
    text = log_privacy.safe_exception_text(exc)
    assert SECRET not in text
    assert text


def test_safe_exception_text_keeps_ordinary_messages():
    assert log_privacy.safe_exception_text(RuntimeError("db down")) == "db down"
