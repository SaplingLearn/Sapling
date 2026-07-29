from __future__ import annotations

import json
import re
import time
import os
import sys

from google import genai
from google.genai import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import GEMINI_API_KEY

_HTTP_TIMEOUT_MS = 180_000

_client = genai.Client(
    api_key=GEMINI_API_KEY or "dummy-key-for-import",
    http_options=types.HttpOptions(timeout=_HTTP_TIMEOUT_MS),
)
MODEL_DEFAULT = "gemini-2.5-flash"
MODEL_LITE = "gemini-2.5-flash-lite"
MODEL_SMART = "gemini-2.5-pro"


def _log_gemini_usage(response, *, feature: str, model: str) -> None:
    """Record token usage for a direct Gemini call (#118).

    Reads ``response.usage_metadata`` and hands it to the fire-and-forget
    events writer. Import is local to avoid a module-load cycle
    (events_service → db/connection) and any import cost when Gemini is unused;
    events_service.log_llm_usage is itself failure-isolated, but we still guard
    here so a missing/odd ``usage_metadata`` can never break a real call.
    """
    try:
        from services.events_service import log_llm_usage

        log_llm_usage(
            feature=feature,
            task=None,
            model=model,
            usage=getattr(response, "usage_metadata", None),
            provider="gemini",
        )
    except Exception:
        pass


def _thinking_budget_for(model: str) -> int:
    """Thinking-token budget for a model, shared by every call path here.

    gemini-2.5-pro rejects thinking_budget=0 (400 INVALID_ARGUMENT — "This
    model only works in thinking mode"); Flash/Flash-Lite are fine with it
    disabled for latency. Cap Pro at 2048 (not -1/dynamic) to keep replies
    snappy without losing multi-step reasoning. Centralizing the decision
    stops call_gemini and call_gemini_multiturn from drifting apart.
    """
    # `model and ...` guards against a None/empty model: `"pro" in None`
    # raises TypeError, and an empty string is not a Pro model anyway.
    return 2048 if model and "pro" in model else 0


def _strip_backtick_fencing(text: str) -> str:
    """Extract JSON content, handling backtick fences anywhere in the text."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def _extract_json(text: str) -> str:
    """Find the first complete JSON object or array in text."""
    text = _strip_backtick_fencing(text)
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass
    for start_char in ('{', '['):
        idx = text.find(start_char)
        if idx == -1:
            continue
        end_char = '}' if start_char == '{' else ']'
        depth = 0
        for i, ch in enumerate(text[idx:], idx):
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    candidate = text[idx:i + 1]
                    try:
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        break
    return text


def call_gemini(
    prompt: str,
    retries: int = 1,
    json_mode: bool = False,
    model: str = MODEL_DEFAULT,
    feature: str = "misc",
) -> str:
    """Single-turn call to Gemini with a plain string prompt.

    Pro's thinking cap (`_thinking_budget_for`) also applies here — that
    fix originally lived only in call_gemini_multiturn (PR #74), so any
    caller passing model="gemini-2.5-pro" here (e.g. an LLM-judge model
    override) used to 400 on thinking_budget=0.

    ``feature`` tags the resulting llm_usage row (#118); it defaults to
    ``"misc"`` so uninstrumented callers still attribute somewhere.
    """
    thinking_budget = _thinking_budget_for(model)
    for attempt in range(retries + 1):
        try:
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
                **({"response_mime_type": "application/json"} if json_mode else {}),
            )
            response = _client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            _log_gemini_usage(response, feature=feature, model=model)
            if not response.text:
                raise ValueError("Gemini returned empty response (content may have been filtered)")
            return response.text
        except Exception as e:
            err_str = str(e)
            if attempt < retries and ("429" in err_str or "500" in err_str):
                time.sleep(2)
                continue
            raise


def call_gemini_multiturn(system_prompt: str, history: list[dict], user_message: str, retries: int = 1, model: str = MODEL_DEFAULT, feature: str = "misc") -> str:
    """
    Multi-turn call to Gemini using native chat history.

    history: list of {"role": "user"|"model", "content": "..."} dicts
             from the DB (role "assistant" is remapped to "model").
    Returns the assistant reply as a plain string.

    ``feature`` tags the resulting llm_usage row (#118).
    """
    # Gemini expects role to be "user" or "model" (not "assistant")
    def _normalise_role(role: str) -> str:
        return "model" if role == "assistant" else role

    gemini_history = [
        types.Content(
            role=_normalise_role(msg["role"]),
            parts=[types.Part(text=msg["content"])],
        )
        for msg in history
    ]

    # Pro requires thinking (budget=0 is rejected); Flash allows disabling it
    # for latency. Shared with the single-turn path via _thinking_budget_for.
    thinking_budget = _thinking_budget_for(model)
    for attempt in range(retries + 1):
        try:
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=16384,
                system_instruction=system_prompt,
                thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
            )
            chat = _client.chats.create(model=model, config=config, history=gemini_history)
            response = chat.send_message(user_message)
            _log_gemini_usage(response, feature=feature, model=model)
            if not response.text:
                raise ValueError("Gemini returned empty response (content may have been filtered)")
            return response.text
        except Exception as e:
            err_str = str(e)
            if attempt < retries and ("429" in err_str or "500" in err_str):
                time.sleep(2)
                continue
            raise


def call_gemini_json(prompt: str, model: str = MODEL_DEFAULT, feature: str = "misc"):
    # Delegates to call_gemini, which logs usage — so JSON-mode calls are
    # captured exactly once (no double-count here).
    raw = call_gemini(prompt, json_mode=True, model=model, feature=feature)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = _extract_json(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Gemini response was not valid JSON: {e}\nRaw response: {raw[:200]!r}") from e


def extract_graph_update(response_text: str) -> tuple:
    """
    Extract <graph_update>...</graph_update> block from AI response.
    Returns (conversational_text, graph_update_dict).
    """
    pattern = r"<graph_update>(.*?)</graph_update>"
    match = re.search(pattern, response_text, re.DOTALL)

    graph_update = {
        "new_nodes": [],
        "updated_nodes": [],
        "new_edges": [],
        "recommended_next": [],
    }

    if match:
        raw_json = match.group(1).strip()
        try:
            graph_update = json.loads(_strip_backtick_fencing(raw_json))
        except json.JSONDecodeError:
            pass
        conversational = response_text[: match.start()] + response_text[match.end():]
    else:
        conversational = response_text

    return conversational.strip(), graph_update
