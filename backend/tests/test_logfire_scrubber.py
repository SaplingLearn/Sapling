"""Smoke tests for the Logfire scrubber that redacts user content.

The scrubber's job is to keep document text out of Logfire spans without
losing the ability to fingerprint a body for debugging. These tests pin
the three observable behaviors:

1. Long strings on risky paths are truncated and fingerprinted.
2. Short strings on risky paths pass through unchanged (cheap to keep).
3. Non-risky attribute names pass through even when the value is long.
"""

from __future__ import annotations

from services.logfire_scrubber import _PREVIEW_CHARS, scrub_attribute  # noqa: PLC2701


def test_long_prompt_is_truncated_and_fingerprinted():
    body = "secret student essay text " * 50  # ~1300 chars
    result = scrub_attribute("gen_ai.prompt", body)

    assert isinstance(result, str)
    assert result.startswith(body[:_PREVIEW_CHARS])
    assert "redacted" in result
    assert f"{len(body)} chars" in result
    assert "sha256:" in result
    # Fingerprint is 16 hex chars.
    fp = result.split("sha256:")[1].rstrip("]")
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


def test_short_string_on_risky_attribute_passes_through():
    short = "Linear Regression"
    assert scrub_attribute("user_prompt", short) == short
    assert scrub_attribute("messages", short) == short


def test_non_risky_attribute_is_untouched_even_when_long():
    long_request_id = "req-" + "x" * 500
    assert scrub_attribute("request_id", long_request_id) == long_request_id
    assert scrub_attribute("http.route", long_request_id) == long_request_id
