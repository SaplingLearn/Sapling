"""Uvicorn's access log without query strings.

Uvicorn logs every request as ``'%s - "%s %s HTTP/%s" %d'`` with the path AND
its query string (``uvicorn.protocols.utils.get_path_with_query_string``), and
that line goes to stdout, i.e. Railway's log store. Query parameters can carry
student text (search terms, usernames), so the access log keeps the path only.

``install()`` attaches ``StripQueryStringFilter`` to the ``uvicorn.access``
logger at app import (main.py), so it applies however uvicorn is launched (the
Dockerfile CMD, ``python main.py``, the E2E script) and survives uvicorn's own
``dictConfig``, which runs before the app is imported and leaves existing
loggers enabled. A logger-level filter sees every record logged on that logger,
which is where both uvicorn protocol implementations (h11, httptools) log.
"""

from __future__ import annotations

import logging

ACCESS_LOGGER = "uvicorn.access"
# Position of the path in uvicorn's access-log args:
# (client_addr, method, full_path, http_version, status_code).
_PATH_ARG = 2


def strip_query(path: str) -> str:
    """``path`` without ``?query`` or ``#fragment``."""
    for sep in ("?", "#"):
        cut = path.find(sep)
        if cut != -1:
            path = path[:cut]
    return path


class StripQueryStringFilter(logging.Filter):
    """Rewrites the path argument of a uvicorn access record; never drops one."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > _PATH_ARG and isinstance(args[_PATH_ARG], str):
            path = args[_PATH_ARG]
            stripped = strip_query(path)
            if stripped != path:
                record.args = args[:_PATH_ARG] + (stripped,) + args[_PATH_ARG + 1:]
        return True


def install() -> None:
    """Attach the filter to uvicorn's access logger (idempotent)."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, StripQueryStringFilter) for f in logger.filters):
        logger.addFilter(StripQueryStringFilter())
