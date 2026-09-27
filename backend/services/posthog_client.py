"""Process-wide PostHog client initialized during the FastAPI lifespan."""

import atexit

from posthog import Posthog

from config import POSTHOG_HOST, POSTHOG_PROJECT_TOKEN

_posthog_client: Posthog | None = None


def initialize_posthog() -> Posthog | None:
    """Construct the optional PostHog client once for this process."""
    global _posthog_client

    if _posthog_client is not None:
        return _posthog_client
    if not POSTHOG_PROJECT_TOKEN or not POSTHOG_HOST:
        return None

    _posthog_client = Posthog(
        project_api_key=POSTHOG_PROJECT_TOKEN,
        host=POSTHOG_HOST,
        enable_exception_autocapture=True,
    )
    atexit.register(_posthog_client.shutdown)
    return _posthog_client


def get_posthog_client() -> Posthog | None:
    """Return the lifespan-managed PostHog client, if analytics is configured."""
    return _posthog_client
