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


def call_gemini(prompt: str, retries: int = 1, json_mode: bool = False, model: str = MODEL_DEFAULT) -> str:
    """Single-turn call to Gemini with a plain string prompt."""
    for attempt in range(retries + 1):
        try:
            config = types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                **({"response_mime_type": "application/json"} if json_mode else {}),
            )
            response = _client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            if not response.text:
                raise ValueError("Gemini returned empty response (content may have been filtered)")
            return response.text
        except Exception as e:
            err_str = str(e)
            if attempt < retries and ("429" in err_str or "500" in err_str):
                time.sleep(2)
                continue
            raise


def call_gemini_multiturn(system_prompt: str, history: list[dict], user_message: str, retries: int = 1, model: str = MODEL_DEFAULT) -> str:
    """
    Multi-turn call to Gemini using native chat history.

    history: list of {"role": "user"|"model", "content": "..."} dicts
             from the DB (role "assistant" is remapped to "model").
    Returns the assistant reply as a plain string.
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

    # gemini-2.5-pro requires thinking (budget=0 is rejected); flash allows
    # disabling it for latency. Cap pro at 2048 instead of -1 (dynamic) to keep
    # tutor replies snappy without losing multi-step reasoning quality.
    thinking_budget = 2048 if "pro" in model else 0
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
            if not response.text:
                raise ValueError("Gemini returned empty response (content may have been filtered)")
            return response.text
        except Exception as e:
            err_str = str(e)
            if attempt < retries and ("429" in err_str or "500" in err_str):
                time.sleep(2)
                continue
            raise


def call_gemini_json(prompt: str, model: str = MODEL_DEFAULT):
    raw = call_gemini(prompt, json_mode=True, model=model)
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
