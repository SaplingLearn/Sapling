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


#: The ``db_user_scope`` refusals (db/scope.py) that main.py answers itself:
#: 404 (RLS denied), 503 (token unusable or rejected), 500 (no subject).
_SCOPE_ERRORS = ("ScopedAccessDenied", "ScopeUnavailable", "UnscopedQueryError")


def _scope_cause(exc: BaseException) -> BaseException | None:
    """A ``db.scope`` refusal this domain error was raised from, if any.
    Matched by module + name so this helper never imports db.scope."""
    seen: set[int] = set()
    cur: BaseException | None = exc.__cause__ or exc.__context__
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__module__ == "db.scope" and type(cur).__name__ in _SCOPE_ERRORS:
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


def domain_status(exc: BaseException, statuses: Mapping[type, int], default: int = 500) -> int:
    """The status of the first class in ``type(exc).__mro__`` that ``statuses`` maps.

    #115: a service that wraps every failure (``except Exception: raise
    StorageError(...) from e``) would otherwise turn a ``db_user_scope=enforce``
    refusal into its own status (a 500 carrying the refusal's text). When the
    domain error was raised from one, that refusal is re-raised instead, so
    main.py answers it the one way it answers it everywhere (404 / 503 / 500)."""
    scope_error = _scope_cause(exc)
    if scope_error is not None:
        raise scope_error
    for cls in type(exc).__mro__:
        status = statuses.get(cls)
        if status is not None:
            return status
    logger.error("unmapped domain error %s; answering %d", type(exc).__name__, default)
    return default
