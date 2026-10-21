"""Recognize schema deployment mismatches without exposing database internals."""
import httpx

SCHEMA_UPDATE_DETAIL = (
    "This feature needs a database update for this version of Sapling. "
    "Ask the project maintainer to apply the pending database migrations, then retry."
)


def is_missing_schema(error: httpx.HTTPStatusError) -> bool:
    if error.response.status_code not in (400, 404):
        return False
    try:
        body = error.response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") in {
        "42703", "42P01", "42883", "PGRST202", "PGRST204", "PGRST205",
    }
