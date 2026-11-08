"""Whether a billable live-model test may run (enforced in tests/conftest.py).

A `live_llm` test calls a real model and costs money. Having a key is not
consent: config.py loads backend/.env, so a developer checkout that holds real
keys would otherwise make billable calls on every full-suite run. A live lane
runs only when it is asked for by name, with its own RUN_LIVE_<LANE>=1
variable (RUN_LIVE_OCR, RUN_LIVE_QUIZ, RUN_LIVE_OCR_PIPELINE, ...).
"""
from collections.abc import Mapping

LIVE_OPT_IN_PREFIX = "RUN_LIVE_"


def live_opt_in(environ: Mapping[str, str]) -> bool:
    """True when some RUN_LIVE_<LANE>=1 is set, i.e. a live lane was asked for
    by name. Each live test still checks its own lane's variable."""
    return any(
        name.startswith(LIVE_OPT_IN_PREFIX) and value == "1" for name, value in environ.items()
    )


def billable(marker) -> bool:
    """True for a `live_llm` marker whose test may make a real model call.

    `live_llm(offline=True)` marks a test that lifts the hermetic LLM guard but
    calls no model (the guard's own pin that live lanes are left alone)."""
    return marker is not None and not marker.kwargs.get("offline", False)
