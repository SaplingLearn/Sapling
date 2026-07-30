"""Benchmark-only raw Gemini helper (D1, ADR 0024).

The application seam this descends from (`services/gemini_service.py`) was
deleted in #151b: every production LLM call runs as a Pydantic AI agent
under `backend/agents/` (model slots + mode gate in `agents/_providers.py`).
The offline benchmarks in this directory still need a raw google-genai call
for their non-agent baseline arms — benchmark_quiz.py's LLM judge and
benchmark_rag.py's answer generation — and that is the ONLY sanctioned use
of this module. Do NOT import it from `services/`, `routes/`, or `agents/`;
request-path LLM code is a Pydantic AI agent behind the `_providers` seam.
"""
from __future__ import annotations

import json

from google import genai
from google.genai import types

from config import GEMINI_API_KEY

_client = genai.Client(
    api_key=GEMINI_API_KEY or "dummy-key-for-import",
    http_options=types.HttpOptions(timeout=180_000),
)


def _generate(prompt: str, model: str, json_mode: bool) -> str:
    response = _client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
            # Pro rejects thinking_budget=0 (400 INVALID_ARGUMENT); cap it
            # instead. Flash tiers run un-thinking for latency.
            thinking_config=types.ThinkingConfig(
                thinking_budget=2048 if "pro" in model else 0,
            ),
            **({"response_mime_type": "application/json"} if json_mode else {}),
        ),
    )
    if not response.text:
        raise ValueError("Gemini returned an empty response")
    return response.text


def call_gemini(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """Single-turn plain-text call. Benchmark baseline arms only."""
    return _generate(prompt, model, json_mode=False)


def call_gemini_json(prompt: str, model: str = "gemini-2.5-flash"):
    """Single-turn JSON-mode call, parsed. Benchmark judges only."""
    return json.loads(_generate(prompt, model, json_mode=True))
