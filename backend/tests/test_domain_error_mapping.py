"""The #118 domain-error -> HTTP mapping walks the MRO (PR #851 review).

routes/social.py, routes/admin.py and routes/gradescope.py each map a domain
package's error classes to the status the route answered with before the
split. An exact-type lookup turned a subclass of a mapped error, or the bare
package base, into a KeyError -> 500 with the wrong body. These pin that a
subclass answers with its mapped parent's status and the base answers 500
with its own detail.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException

from routes import admin as admin_routes
from routes import gradescope as gradescope_routes
from routes import social as social_routes
from routes._errors import domain_status
from services.admin.errors import AdminError, Conflict as AdminConflict
from services.gradescope.errors import AmbiguousLink, GradescopeLinkError
from services.social.errors import NotFound as SocialNotFound, SocialError


class _Base(Exception):
    pass


class _Mapped(_Base):
    pass


class _Sub(_Mapped):
    pass


def test_domain_status_walks_the_mro():
    statuses = {_Mapped: 404}
    assert domain_status(_Mapped(), statuses) == 404
    assert domain_status(_Sub(), statuses) == 404


def test_domain_status_unmapped_answers_the_default_and_logs(caplog):
    with caplog.at_level(logging.ERROR, logger="routes._errors"):
        assert domain_status(_Base(), {_Mapped: 404}) == 500
        assert domain_status(_Base(), {_Mapped: 404}, default=503) == 503
    assert "unmapped domain error _Base" in caplog.text


def _raised(ctx_factory, exc):
    with pytest.raises(HTTPException) as info:
        with ctx_factory():
            raise exc
    return info.value


# ── routes/social.py ─────────────────────────────────────────────────────────

class _GoneRoom(SocialNotFound):
    pass


def test_social_maps_a_subclass_to_its_parents_status():
    err = _raised(social_routes._social_errors, _GoneRoom("Room not found"))
    assert (err.status_code, err.detail) == (404, "Room not found")


def test_social_maps_the_bare_base_to_500():
    err = _raised(social_routes._social_errors, SocialError("boom"))
    assert (err.status_code, err.detail) == (500, "boom")


# ── routes/admin.py ──────────────────────────────────────────────────────────

class _LastAdmin(AdminConflict):
    pass


def test_admin_maps_a_subclass_to_its_parents_status():
    err = _raised(admin_routes._admin_errors, _LastAdmin("last admin"))
    assert (err.status_code, err.detail) == (409, "last admin")


def test_admin_maps_the_bare_base_to_500():
    err = _raised(admin_routes._admin_errors, AdminError("boom"))
    assert (err.status_code, err.detail) == (500, "boom")


# ── routes/gradescope.py ─────────────────────────────────────────────────────

class _AmbiguousTermLink(AmbiguousLink):
    pass


def test_gradescope_maps_a_subclass_to_its_parents_status():
    err = gradescope_routes._link_http_error(_AmbiguousTermLink("ambiguous"))
    assert (err.status_code, err.detail) == (409, "ambiguous")


def test_gradescope_maps_the_bare_base_to_500():
    err = gradescope_routes._link_http_error(GradescopeLinkError("boom"))
    assert (err.status_code, err.detail) == (500, "boom")


# ── #115: a db_user_scope refusal wrapped in a domain error ──────────────────

def _scope_errors():
    from db.scope import ScopeUnavailable, UnscopedQueryError

    return [ScopeUnavailable("token rejected"), UnscopedQueryError("no subject")]


@pytest.mark.parametrize("index", [0, 1], ids=["unavailable", "unscoped"])
def test_domain_status_reraises_a_wrapped_scope_refusal(index):
    """A service that wraps every failure in its own domain error (flashcards'
    StorageError) must not turn an enforce refusal into a 500 carrying the
    refusal's text: the refusal itself reaches main.py's handler."""
    original = _scope_errors()[index]
    try:
        try:
            raise original
        except Exception as e:
            raise _Mapped(str(e)) from e
    except _Mapped as wrapped:
        with pytest.raises(type(original)) as info:
            domain_status(wrapped, {_Mapped: 500})
    assert info.value is original


def test_domain_status_respects_a_refusal_dropped_with_from_none():
    """`raise X from None` means the service handled the refusal and chose
    its own answer; it is not dug back out of the suppressed context."""
    from db.scope import ScopeUnavailable

    try:
        try:
            raise ScopeUnavailable("token rejected")
        except ScopeUnavailable:
            raise _Mapped("handled") from None
    except _Mapped as wrapped:
        assert domain_status(wrapped, {_Mapped: 409}) == 409


def test_domain_status_still_finds_an_implicit_context():
    """A refusal that merely happened during handling (no `from`) still counts."""
    from db.scope import ScopeUnavailable

    original = ScopeUnavailable("token rejected")
    try:
        try:
            raise original
        except ScopeUnavailable:
            raise _Mapped("wrapped")
    except _Mapped as wrapped:
        with pytest.raises(ScopeUnavailable):
            domain_status(wrapped, {_Mapped: 500})


def test_flashcards_list_answers_503_when_the_token_is_rejected(monkeypatch):
    """Seen under enforce in the E2E lane: a rejected token on the flashcards
    list came back as a 500 StorageError instead of the fail-closed 503."""
    from fastapi.testclient import TestClient

    import main
    from db.scope import ScopeUnavailable
    from services.flashcards import cards

    def rejected(*_a, **_k):
        raise ScopeUnavailable("PostgREST rejected the user-scoped token (flashcards)")

    monkeypatch.setattr(cards, "list_flashcards", rejected)
    monkeypatch.setattr("routes.flashcards.require_self", lambda *_a, **_k: None)
    r = TestClient(main.app, raise_server_exceptions=False).get("/api/flashcards/user/u1")
    assert r.status_code == 503, r.text
    assert "PostgREST" not in r.text
