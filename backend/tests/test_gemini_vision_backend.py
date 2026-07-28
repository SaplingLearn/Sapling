"""
Unit tests for services/extraction_backends/gemini_vision_backend.py

Gemini-vision OCR for pages that carry no extractable text layer -- scans and
photographed handwritten work. Docling already flags such pages (its
`fallback_pages`), but with no local OCR engine installed it returns "" for
them, which is how an unreadable upload reached the classify prompt with an
empty `Content:` block and got a fabricated summary.

The transcription is a Pydantic AI agent (`agents/ocr_vision.py`), so these
tests drive it through the `SAPLING_MODEL_MODE=function` seam (#391) rather
than mock-patching a client: a FunctionModel runs the REAL agent -- real
system prompt, real message construction, real usage accounting -- and only
substitutes the model itself. That makes assertions like "the image bytes
actually reached the model" and "the usage limit is enforced" true statements
about the shipped path instead of statements about a MagicMock.

No real API calls: FunctionModel sits above the google-genai transport, so
these tests never touch it (see tests/test_model_mode_seam.py).
"""
import pytest
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import BinaryContent, ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage

from agents import WORKER_LIMITS
from agents._providers import (
    clear_function_handlers,
    model_for,
    register_function_handler,
)
from agents.ocr_vision import BLANK_PAGE_SENTINEL, ocr_vision_agent
from services.extraction_backends.gemini_vision_backend import (
    GeminiVisionUnavailableError,
    extract_page_with_gemini_vision,
    vision_model_name,
)

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _text(content):
    """A model response carrying `content` as the page transcription."""
    return lambda messages, info: ModelResponse(parts=[TextPart(content=content)])


class TestEnablement:
    def test_raises_when_disabled(self, monkeypatch):
        """Off by default: this spends an LLM call per page, so it must be
        opted into explicitly rather than silently billing every scanned
        upload."""
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "false")
        with pytest.raises(GeminiVisionUnavailableError):
            extract_page_with_gemini_vision(PNG)

    def test_raises_when_api_key_missing(self, monkeypatch):
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiVisionUnavailableError):
            extract_page_with_gemini_vision(PNG)


class TestModelSelection:
    """The model is chosen by the ADR-0008 per-task router, not a private knob.

    `vision_model_name` feeds the OCR cache key, so it has to report the model
    that would actually transcribe -- a stale name would serve one model's
    transcription after an operator switched to another.
    """

    def test_defaults_to_the_task_default(self, monkeypatch):
        monkeypatch.delenv("SAPLING_MODEL_OCR_VISION", raising=False)
        assert vision_model_name() == "gemini-2.5-flash"

    def test_honors_the_adr_0008_env_override(self, monkeypatch):
        monkeypatch.setenv("SAPLING_MODEL_OCR_VISION", "gemini-2.5-pro")
        assert vision_model_name() == "gemini-2.5-pro"
        assert model_for("ocr_vision").model_name == "gemini-2.5-pro"

    def test_ignores_the_dropped_private_knob(self, monkeypatch):
        """GEMINI_VISION_OCR_MODEL was a competing knob that bypassed
        `model_for`; it is gone, so setting it must not change routing."""
        monkeypatch.delenv("SAPLING_MODEL_OCR_VISION", raising=False)
        monkeypatch.setenv("GEMINI_VISION_OCR_MODEL", "gemini-1.5-pro")
        assert vision_model_name() == "gemini-2.5-flash"


class TestTranscription:
    @pytest.fixture(autouse=True)
    def _function_mode(self, monkeypatch):
        """Enable the backend and swap in a FunctionModel for the ocr_vision
        task. Handlers are process-global, so clear them around each test."""
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
        clear_function_handlers()
        yield
        clear_function_handlers()

    @staticmethod
    def _transcribe(handler, image_bytes=PNG):
        register_function_handler("ocr_vision", handler)
        with ocr_vision_agent.override(model=model_for("ocr_vision")):
            return extract_page_with_gemini_vision(image_bytes)

    def test_returns_transcribed_text(self):
        latex = "Problem 2\nA. $\\lambda = -1, 8$"
        assert self._transcribe(_text(latex)) == latex

    def test_sends_the_image_bytes_to_the_model(self):
        """The page image has to reach the model as image content -- if it
        didn't, the agent would be transcribing an empty prompt and happily
        inventing a page."""
        seen = {}

        def handler(messages, info):
            seen["messages"] = messages
            return ModelResponse(parts=[TextPart(content="text")])

        self._transcribe(handler)

        parts = [p for m in seen["messages"] for p in m.parts]
        images = [
            c
            for p in parts
            for c in (p.content if isinstance(p.content, list) else [])
            if isinstance(c, BinaryContent)
        ]
        assert len(images) == 1
        assert images[0].data == PNG
        assert images[0].media_type == "image/png"

    def test_the_transcription_prompt_reaches_the_model(self):
        """The verbatim-transcription instruction (and the blank-page sentinel
        it promises) must be in the request, or the sentinel mapping below is
        asserting on a contract the model was never told about."""
        seen = {}

        def handler(messages, info):
            seen["system"] = "\n".join(
                p.content
                for m in messages
                for p in m.parts
                if type(p).__name__ == "SystemPromptPart"
            )
            return ModelResponse(parts=[TextPart(content="text")])

        self._transcribe(handler)

        assert "Transcribe ALL content" in seen["system"]
        assert BLANK_PAGE_SENTINEL in seen["system"]

    def test_blank_page_sentinel_returns_empty_string(self):
        """A genuinely blank page must come back as "" rather than the literal
        sentinel, or the sentinel becomes indexed course material."""
        assert self._transcribe(_text(BLANK_PAGE_SENTINEL)) == ""

    def test_empty_model_response_returns_empty_string(self):
        """A model that transcribes nothing (safety block, empty candidate) is
        a page outcome, not a document failure: the caller's `if text:` guard
        then keeps whatever Docling produced for that page."""
        assert self._transcribe(_text("")) == ""
        assert self._transcribe(_text("   \n  ")) == ""

    def test_transcribes_when_called_from_a_running_event_loop(self):
        """`routes/documents.py::_extract_text_or_422` is called straight from
        `async def upload_document`, so this sync seam is reached WITH a loop
        already running. A bare `asyncio.run` would raise there, and
        extraction_service's per-page `except Exception: continue` would
        swallow it -- vision OCR silently doing nothing on the main upload
        path. Pin that it still transcribes.
        """
        import asyncio

        register_function_handler("ocr_vision", _text("on-loop transcription"))

        async def _from_a_handler():
            return extract_page_with_gemini_vision(PNG)

        with ocr_vision_agent.override(model=model_for("ocr_vision")):
            assert asyncio.run(_from_a_handler()) == "on-loop transcription"

    def test_api_error_propagates_for_the_caller_to_handle(self):
        """Per-page failures are the caller's business -- extraction_service
        keeps the original page and moves on rather than losing the document."""

        def handler(messages, info):
            raise RuntimeError("429 quota")

        with pytest.raises(RuntimeError, match="429 quota"):
            self._transcribe(handler)

    def test_usage_limit_is_applied(self):
        """One LLM call per scanned page: a 200-page scan multiplies whatever a
        single runaway page costs, so the run must carry WORKER_LIMITS (#329,
        #345). Asserted by exceeding the limit and requiring the run to abort.
        """
        over = WORKER_LIMITS.total_tokens_limit + 1

        def handler(messages, info):
            return ModelResponse(
                parts=[TextPart(content="a very long transcription")],
                usage=RequestUsage(input_tokens=over, output_tokens=0),
            )

        with pytest.raises(UsageLimitExceeded):
            self._transcribe(handler)

    def test_unbounded_usage_would_not_raise(self):
        """Counter-check for the test above: the same response under no limits
        succeeds, so the failure there is the limit doing its job rather than
        an unrelated rejection of the oversized usage."""
        over = WORKER_LIMITS.total_tokens_limit + 1

        def handler(messages, info):
            return ModelResponse(
                parts=[TextPart(content="ok")],
                usage=RequestUsage(input_tokens=over, output_tokens=0),
            )

        register_function_handler("ocr_vision", handler)
        with ocr_vision_agent.override(model=model_for("ocr_vision")):
            result = ocr_vision_agent.run_sync(
                [BinaryContent(data=PNG, media_type="image/png")]
            )
        assert result.output == "ok"
