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
