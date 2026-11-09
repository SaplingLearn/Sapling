"""
backend/routes/_errors.py

Route-side helper (not a router) mapping a #118 domain error to the HTTP
status its route answered with before the split. The lookup walks the raised
class's MRO, so a subclass of a mapped error answers with its parent's status
and an error class the map does not name (a bare package base, or one added
later) answers ``default`` instead of failing the request with a KeyError.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


def domain_status(exc: BaseException, statuses: Mapping[type, int], default: int = 500) -> int:
    """The status of the first class in ``type(exc).__mro__`` that ``statuses`` maps."""
    for cls in type(exc).__mro__:
        status = statuses.get(cls)
        if status is not None:
            return status
    logger.error("unmapped domain error %s; answering %d", type(exc).__name__, default)
    return default
