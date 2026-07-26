"""
Unit tests for services/extraction_backends/gemini_vision_backend.py

Gemini-vision OCR for pages that carry no extractable text layer -- scans and
photographed handwritten work. Docling already flags such pages (its
`fallback_pages`), but with no local OCR engine installed it returns "" for
them, which is how an unreadable upload reached the classify prompt with an
empty `Content:` block and got a fabricated summary.

No real API calls: the client is patched everywhere.
"""
from unittest.mock import MagicMock, patch

import pytest

from services.extraction_backends.gemini_vision_backend import (
    GeminiVisionUnavailableError,
    extract_page_with_gemini_vision,
)

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _resp(text):
    """Minimal stand-in for the google-genai response object."""
    return MagicMock(text=text)


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


class TestTranscription:
    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.setenv("GEMINI_VISION_OCR_ENABLED", "true")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def test_returns_transcribed_text(self):
        latex = "Problem 2\nA. $\\lambda = -1, 8$"
        client = MagicMock()
        client.models.generate_content.return_value = _resp(latex)
        with patch(
            "services.extraction_backends.gemini_vision_backend._client",
            return_value=client,
        ):
            assert extract_page_with_gemini_vision(PNG) == latex

    def test_sends_the_image_bytes_to_the_model(self):
        client = MagicMock()
        client.models.generate_content.return_value = _resp("text")
        with patch(
            "services.extraction_backends.gemini_vision_backend._client",
            return_value=client,
        ):
            extract_page_with_gemini_vision(PNG)

        kwargs = client.models.generate_content.call_args.kwargs
        blob = str(kwargs.get("contents"))
        assert "image/png" in blob

    def test_blank_page_sentinel_returns_empty_string(self):
        """A genuinely blank page must come back as "" rather than the literal
        sentinel, or the sentinel becomes indexed course material."""
        client = MagicMock()
        client.models.generate_content.return_value = _resp("[BLANK PAGE]")
        with patch(
            "services.extraction_backends.gemini_vision_backend._client",
            return_value=client,
        ):
            assert extract_page_with_gemini_vision(PNG) == ""

    def test_empty_model_response_returns_empty_string(self):
        client = MagicMock()
        client.models.generate_content.return_value = _resp(None)
        with patch(
            "services.extraction_backends.gemini_vision_backend._client",
            return_value=client,
        ):
            assert extract_page_with_gemini_vision(PNG) == ""

    def test_api_error_propagates_for_the_caller_to_handle(self):
        """Per-page failures are the caller's business -- extraction_service
        keeps the original page and moves on rather than losing the document."""
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("429 quota")
        with patch(
            "services.extraction_backends.gemini_vision_backend._client",
            return_value=client,
        ):
            with pytest.raises(RuntimeError):
                extract_page_with_gemini_vision(PNG)
