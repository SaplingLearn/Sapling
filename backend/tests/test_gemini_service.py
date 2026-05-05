"""
Unit tests for services/gemini_service.py

Tests pure utility functions without hitting the real Gemini API.
API-calling functions (call_gemini, call_gemini_json) are tested with
a mocked client so no API key is required.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from services.gemini_service import (
    _strip_backtick_fencing,
    _extract_json,
    extract_graph_update,
    call_gemini,
    call_gemini_json,
    call_gemini_multiturn,
)


# ── _strip_backtick_fencing ───────────────────────────────────────────────────

class TestStripBacktickFencing:
    def test_plain_text_unchanged(self):
        text = '{"key": "value"}'
        assert _strip_backtick_fencing(text) == text

    def test_json_fenced_block(self):
        text = '```json\n{"key": "value"}\n```'
        assert _strip_backtick_fencing(text) == '{"key": "value"}'

    def test_plain_fenced_block(self):
        text = '```\n{"key": "value"}\n```'
        assert _strip_backtick_fencing(text) == '{"key": "value"}'

    def test_strips_surrounding_whitespace(self):
        assert _strip_backtick_fencing('  hello  ') == 'hello'

    def test_empty_string(self):
        assert _strip_backtick_fencing('') == ''

    def test_fenced_block_with_extra_text_before(self):
        text = 'Here is the output:\n```json\n{"a": 1}\n```'
        assert _strip_backtick_fencing(text) == '{"a": 1}'


# ── _extract_json ─────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_plain_object(self):
        assert json.loads(_extract_json('{"key": "value"}')) == {"key": "value"}

    def test_plain_array(self):
        assert json.loads(_extract_json('[1, 2, 3]')) == [1, 2, 3]

    def test_json_in_fenced_block(self):
        text = '```json\n{"key": "value"}\n```'
        assert json.loads(_extract_json(text)) == {"key": "value"}

    def test_json_embedded_in_prose(self):
        text = 'The answer is: {"score": 42} — hope that helps!'
        assert json.loads(_extract_json(text)) == {"score": 42}

    def test_nested_json(self):
        text = '{"outer": {"inner": true}}'
        assert json.loads(_extract_json(text)) == {"outer": {"inner": True}}

    def test_array_embedded_in_prose(self):
        text = 'Results: [1, 2, 3] done.'
        assert json.loads(_extract_json(text)) == [1, 2, 3]


# ── extract_graph_update ──────────────────────────────────────────────────────

class TestExtractGraphUpdate:
    def test_no_graph_update_block_returns_defaults(self):
        reply, update = extract_graph_update("Hello, I am Sapling!")
        assert reply == "Hello, I am Sapling!"
        assert update == {
            "new_nodes": [],
            "updated_nodes": [],
            "new_edges": [],
            "recommended_next": [],
        }

    def test_extracts_valid_graph_update(self):
        gu = json.dumps({
            "new_nodes": [{"concept_name": "Recursion", "subject": "CS", "initial_mastery": 0.0}],
            "updated_nodes": [],
            "new_edges": [],
            "recommended_next": [],
        })
        text = f"Great question!\n<graph_update>{gu}</graph_update>\nKeep going!"
        reply, update = extract_graph_update(text)

        assert "<graph_update>" not in reply
        assert "Great question!" in reply
        assert "Keep going!" in reply
        assert update["new_nodes"][0]["concept_name"] == "Recursion"

    def test_malformed_json_returns_default_update(self):
        text = "Some text\n<graph_update>not valid json</graph_update>\nMore text"
        _, update = extract_graph_update(text)
        assert update["new_nodes"] == []
        assert update["updated_nodes"] == []

    def test_reply_stripped_of_graph_block(self):
        gu = json.dumps({"new_nodes": [], "updated_nodes": [], "new_edges": [], "recommended_next": []})
        text = f"Before\n<graph_update>{gu}</graph_update>\nAfter"
        reply, _ = extract_graph_update(text)
        # The function concatenates text before and after the tag, leaving a double newline
        assert "Before" in reply
        assert "After" in reply
        assert "<graph_update>" not in reply

    def test_graph_update_with_updated_nodes(self):
        gu = json.dumps({
            "new_nodes": [],
            "updated_nodes": [{"concept_name": "Loops", "mastery_delta": 0.15}],
            "new_edges": [],
            "recommended_next": [],
        })
        _, update = extract_graph_update(f"<graph_update>{gu}</graph_update>")
        assert update["updated_nodes"][0]["mastery_delta"] == 0.15


# ── call_gemini ───────────────────────────────────────────────────────────────

class TestCallGemini:
    def test_returns_response_text(self):
        mock_resp = MagicMock()
        mock_resp.text = "Hello from Gemini"
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.return_value = mock_resp
            result = call_gemini("test prompt")
        assert result == "Hello from Gemini"

    def test_raises_on_empty_response(self):
        mock_resp = MagicMock()
        mock_resp.text = ""
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.return_value = mock_resp
            with pytest.raises(ValueError, match="empty response"):
                call_gemini("test prompt")

    def test_retries_on_429_then_succeeds(self):
        good_resp = MagicMock()
        good_resp.text = "OK"
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("429 Too Many Requests")
            return good_resp

        with patch("services.gemini_service._client") as mock_client:
            with patch("services.gemini_service.time.sleep"):
                mock_client.models.generate_content.side_effect = side_effect
                result = call_gemini("test prompt", retries=1)

        assert result == "OK"
        assert call_count["n"] == 2

    def test_does_not_retry_on_non_retryable_error(self):
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.side_effect = Exception("400 Bad Request")
            with pytest.raises(Exception, match="400"):
                call_gemini("test prompt", retries=1)


# ── call_gemini_json ──────────────────────────────────────────────────────────

class TestCallGeminiJson:
    def test_returns_parsed_dict(self):
        mock_resp = MagicMock()
        mock_resp.text = '{"questions": [{"id": 1}]}'
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.return_value = mock_resp
            result = call_gemini_json("test prompt")
        assert result == {"questions": [{"id": 1}]}

    def test_handles_fenced_json(self):
        mock_resp = MagicMock()
        mock_resp.text = '```json\n{"result": "ok"}\n```'
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.return_value = mock_resp
            result = call_gemini_json("test prompt")
        assert result == {"result": "ok"}

    def test_raises_value_error_on_invalid_json(self):
        mock_resp = MagicMock()
        mock_resp.text = "This is not JSON at all!"
        with patch("services.gemini_service._client") as mock_client:
            mock_client.models.generate_content.return_value = mock_resp
            with pytest.raises(ValueError, match="not valid JSON"):
                call_gemini_json("test prompt")


# ── call_gemini_multiturn — thinking_budget cap ─────────────────────────────

def _capture_multiturn_thinking_budget(model: str) -> int:
    """Run call_gemini_multiturn against a mocked client and return the
    thinking_budget the route configured on the GenerateContentConfig.
    """
    captured: dict = {}

    def fake_chats_create(*, model, config, history):
        captured["thinking_budget"] = config.thinking_config.thinking_budget
        chat = MagicMock()
        resp = MagicMock()
        resp.text = "ok"
        chat.send_message.return_value = resp
        return chat

    with patch("services.gemini_service._client") as mock_client:
        mock_client.chats.create.side_effect = fake_chats_create
        call_gemini_multiturn("sys", [], "msg", model=model)

    return captured["thinking_budget"]


class TestCallGeminiMultiturnThinking:
    """Pin the legacy-path thinking_budget contract.

    Mirrors the agent-path coverage in test_learn_routes.py
    (TestChatViaAgent.test_*_attaches_thinking_cap). Symmetric guard so
    a future edit can't silently restore Pro to dynamic (-1) thinking
    on the legacy fallback either — that was the original latency
    regression PR #80 fixed.
    """

    def test_pro_uses_capped_thinking_budget(self):
        """gemini-2.5-pro must run with a capped budget (2048), NOT -1
        (dynamic). Pin the literal value, not just "any positive int"."""
        assert _capture_multiturn_thinking_budget("gemini-2.5-pro") == 2048

    def test_flash_disables_thinking(self):
        """Non-pro models (Flash, Flash-Lite) get thinking_budget=0 —
        Pro is the only model that actually thinks on this path."""
        assert _capture_multiturn_thinking_budget("gemini-2.5-flash") == 0
        assert _capture_multiturn_thinking_budget("gemini-2.5-flash-lite") == 0
