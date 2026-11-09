"""Shared plumbing for the one-off graph backfills (concept edges, junk prune)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

BASE = Path(__file__).parent.parent
_MODEL_KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY")


def load_env(model_env: str | None) -> None:
    """Fall back to backend/.env ONLY when no env file was wrapped around the
    run (`dotenv -f .env.<env> run -- ...` sets SUPABASE_URL). Filling the
    gaps of a staging/prod env from the local .env would leak local-only
    settings (SAPLING_MODEL_MODE, REDIS_URL, ...) into that run. `model_env`
    then OVERRIDES just the model API keys, so a placeholder key in the
    target env file cannot win."""
    if not os.environ.get("SUPABASE_URL"):
        load_dotenv(BASE / ".env")
    if model_env:
        values = dotenv_values(model_env)
        for k in _MODEL_KEYS:
            if values.get(k):
                os.environ[k] = values[k]
    sys.path.insert(0, str(BASE))


def target_project() -> str:
    return (os.environ.get("SUPABASE_URL") or "").split("//")[-1].split(".")[0]


def course_label(table, course_id: str) -> str:
    rows = table("courses").select(
        "course_code,course_name", filters={"id": f"eq.{course_id}"}, limit=1,
    ) or []
    if not rows:
        return "Course"
    code = (rows[0].get("course_code") or "").strip()
    name = (rows[0].get("course_name") or "").strip()
    return f"{code} — {name}" if code and name else (code or name or "Course")


def load_prior(path: str | None) -> dict[tuple[str, str], dict] | None:
    """A reviewed dry-run report keyed by (user_id, course_id), or None."""
    if not path:
        return None
    return {(c["user_id"], c["course_id"]): c for c in json.loads(Path(path).read_text())["courses"]}


def write_json(path: str | None, payload: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(payload, indent=1, default=str))
