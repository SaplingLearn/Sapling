"""Tests for the Logfire scrubber that redacts user content.

The scrubber's job is to keep document text out of Logfire spans without
losing the ability to fingerprint a body for debugging. Two layers:

* `scrub_attribute(name, value)` — pure transformation, used here for
  fast unit coverage of the redaction logic.
* `scrub_value(match)` — the Logfire callback shape; takes a real
  `ScrubMatch` and returns either a sanitized value or `None` (delegating
  to Logfire's default redaction).
"""

from __future__ import annotations

from types import SimpleNamespace

from services.logfire_scrubber import (  # noqa: PLC2701
    _PREVIEW_CHARS,
    scrub_attribute,
    scrub_value,
)


# ── scrub_attribute: pure transformation ────────────────────────────────────

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


def test_nested_list_redacts_each_string_member():
    """A list under a risky attribute name is sanitized member-wise."""
    long_a = "alpha " * 30
    long_b = "beta " * 30
    short = "ok"
    result = scrub_attribute("messages", [long_a, long_b, short, 42])
    assert isinstance(result, list)
    assert "redacted" in result[0] and "sha256:" in result[0]
    assert "redacted" in result[1] and "sha256:" in result[1]
    assert result[2] == short  # short string unchanged
    assert result[3] == 42      # non-string passes through


def test_nested_dict_redacts_string_values():
    """A dict under a risky attribute redacts string leaves regardless of key."""
    body = "long body content " * 20
    result = scrub_attribute(
        "all_messages_events",
        {"role": "user", "content": body, "ts": 12345},
    )
    assert isinstance(result, dict)
    assert result["role"] == "user"   # short, untouched
    assert "redacted" in result["content"]
    assert result["ts"] == 12345      # int, untouched


def test_deeply_nested_structure_recurses():
    """Pydantic AI's all_messages_events shape: list of dicts with content fields."""
    body = "deep " * 50
    payload = [
        {"role": "user", "parts": [{"content": body, "type": "text"}]},
        {"role": "model", "parts": [{"content": "ok", "type": "text"}]},
    ]
    result = scrub_attribute("all_messages_events", payload)
    assert isinstance(result, list)
    inner = result[0]["parts"][0]["content"]
    assert "redacted" in inner and "sha256:" in inner
    # The "ok" string under a different risky path is short, passes through.
    assert result[1]["parts"][0]["content"] == "ok"


# ── scrub_value: Logfire callback shape ─────────────────────────────────────

def _scrub_match(path, value):
    """Build a ScrubMatch-like duck for the callback. Logfire passes a real
    ScrubMatch with .path (tuple) and .value attributes; SimpleNamespace
    matches the shape the callback uses."""
    return SimpleNamespace(path=path, value=value, pattern_match=None)


def test_scrub_value_sanitizes_when_path_is_risky():
    body = "x" * 500
    match = _scrub_match(("attributes", "gen_ai.prompt"), body)
    result = scrub_value(match)
    assert isinstance(result, str)
    assert "redacted" in result and "sha256:" in result


def test_scrub_value_returns_none_for_non_risky_path():
    """Lets Logfire apply its default full-redaction for password/secret/etc."""
    match = _scrub_match(("attributes", "password"), "hunter2")
    result = scrub_value(match)
    assert result is None  # delegates to Logfire's default behavior


def test_scrub_value_redacts_when_inner_path_segment_is_risky():
    """The `messages` token inside a deeper path triggers the callback."""
    body = "y" * 300
    match = _scrub_match(("attributes", "all_messages_events", 0, "content"), body)
    result = scrub_value(match)
    assert isinstance(result, str)
    assert "redacted" in result
