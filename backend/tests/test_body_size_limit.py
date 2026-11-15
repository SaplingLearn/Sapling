"""The request-body ceiling (services/body_limit.py).

Before this, nothing bounded how many bytes a client could send. FastAPI
materialises a JSON body in memory before validation, so a `str` field with
no `max_length` was a direct route to exhausting the worker: the Pydantic
bound rejected the value only AFTER the allocation that would kill the
process.
"""

import importlib
import inspect
import io
import pkgutil

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from services.body_limit import (
    ACCOUNT_IMPORT_PATH,
    DEFAULT_ACCOUNT_IMPORT_MAX_BYTES,
    DEFAULT_JSON_MAX_BYTES,
    DEFAULT_MULTIPART_MAX_BYTES,
    UPLOAD_PATHS,
    BodySizeLimitMiddleware,
)


def _app(**limits) -> TestClient:
    """A minimal app behind the middleware, so these tests pin the
    middleware's own behaviour rather than any particular route's."""
    app = FastAPI()
    limits.setdefault("upload_paths", frozenset({"/upload"}))
    app.add_middleware(BodySizeLimitMiddleware, **limits)

    @app.post("/echo")
    async def echo(body: dict | None = None):
        return {"ok": True}

    @app.post("/upload")
    async def upload():
        return {"ok": True}

    @app.post(ACCOUNT_IMPORT_PATH)
    async def account_import():
        return {"ok": True}

    @app.post(ACCOUNT_IMPORT_PATH + "/x")
    async def account_import_lookalike():
        return {"ok": True}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return TestClient(app)


class TestJsonBodies:
    def test_rejects_an_oversize_json_body_with_413(self):
        client = _app(json_max_bytes=1024)
        r = client.post("/echo", content=b'{"x":"' + b"a" * 2048 + b'"}',
                        headers={"content-type": "application/json"})
        assert r.status_code == 413
        assert "too large" in r.json()["detail"].lower()

    def test_allows_a_body_under_the_ceiling(self):
        client = _app(json_max_bytes=4096)
        r = client.post("/echo", json={"x": "a" * 100})
        assert r.status_code == 200

    def test_rejects_before_reading_when_content_length_is_declared(self):
        """The cheap path: refused on the header, so the body is never read."""
        client = _app(json_max_bytes=512)
        r = client.post("/echo", content=b"a" * 4096,
                        headers={"content-type": "application/json"})
        assert r.status_code == 413

    def test_a_chunked_body_cannot_walk_past_the_header_check(self):
        """No Content-Length is sent for a streamed body, so the declared-length
        check cannot see it; the running byte count must still refuse it."""
        client = _app(json_max_bytes=1024)

        def chunks():
            for _ in range(8):
                yield b"a" * 512

        r = client.post("/echo", content=chunks(),
                        headers={"content-type": "application/json"})
        assert r.status_code == 413


class TestMultipartBodies:
    def test_multipart_gets_the_larger_ceiling(self):
        """A file upload must not be measured against the JSON ceiling."""
        client = _app(json_max_bytes=1024, multipart_max_bytes=1024 * 1024)
        r = client.post("/upload",
                        files={"file": ("n.pdf", io.BytesIO(b"x" * 8192), "application/pdf")})
        assert r.status_code == 200

    def test_multipart_over_its_own_ceiling_is_still_refused(self):
        client = _app(json_max_bytes=1024, multipart_max_bytes=4096)
        r = client.post("/upload",
                        files={"file": ("n.pdf", io.BytesIO(b"x" * 16384), "application/pdf")})
        assert r.status_code == 413

    def test_a_multipart_label_does_not_raise_the_cap_off_an_upload_route(self):
        """Content-Type is the client's to choose: labelling a JSON body
        multipart must not buy a 120 MB allocation on a JSON route."""
        client = _app(json_max_bytes=1024, multipart_max_bytes=1024 * 1024)
        r = client.post("/echo",
                        files={"file": ("n.pdf", io.BytesIO(b"x" * 8192), "application/pdf")})
        assert r.status_code == 413

    def test_a_forged_multipart_header_on_a_json_route_is_refused(self):
        client = _app(json_max_bytes=1024, multipart_max_bytes=1024 * 1024)
        r = client.post("/echo", content=b"a" * 8192,
                        headers={"content-type": "multipart/form-data; boundary=x"})
        assert r.status_code == 413

    def test_an_upload_route_sent_a_non_multipart_body_gets_the_json_ceiling(self):
        client = _app(json_max_bytes=1024, multipart_max_bytes=1024 * 1024)
        r = client.post("/upload", content=b"a" * 8192,
                        headers={"content-type": "application/json"})
        assert r.status_code == 413

    def test_the_upload_paths_match_exactly(self):
        client = _app(json_max_bytes=1024, multipart_max_bytes=1024 * 1024,
                      upload_paths=frozenset({"/upload"}))
        r = client.post("/upload/x",
                        files={"file": ("n.pdf", io.BytesIO(b"x" * 8192), "application/pdf")})
        assert r.status_code == 413


def _multipart_routes(app) -> set[str]:
    """Every path whose request body FastAPI declares as multipart — i.e. the
    routes with an `UploadFile`/`File(...)`/`Form(...)` parameter. Read off the
    OpenAPI document (public API, unlike `app.routes`, whose shape changed
    across FastAPI versions)."""
    paths = set()
    for path, ops in app.openapi()["paths"].items():
        for op in ops.values():
            content = ((op.get("requestBody") or {}).get("content")) or {}
            if "multipart/form-data" in content:
                paths.add(path)
    return paths


class TestUploadAllowlist:
    def test_the_allowlist_is_exactly_the_apps_upload_routes(self):
        """A new upload route missing from UPLOAD_PATHS would have its files
        refused at 12 MB; a stale entry would hand 120 MB to a JSON route."""
        from main import app

        assert _multipart_routes(app) == set(UPLOAD_PATHS)

    def test_no_upload_route_is_hidden_from_the_schema(self):
        """The test above reads OpenAPI, so an upload route with
        include_in_schema=False would slip past it. None exists today; this
        fails if one appears, so the allowlist test can be widened with it."""
        import routes

        hidden = []
        for info in pkgutil.iter_modules(routes.__path__):
            router = getattr(importlib.import_module(f"routes.{info.name}"), "router", None)
            for route in getattr(router, "routes", []):
                if not isinstance(route, APIRoute) or route.include_in_schema:
                    continue
                params = inspect.signature(route.endpoint).parameters.values()
                if any("UploadFile" in str(p.annotation) for p in params):
                    hidden.append(f"routes/{info.name}.py {route.path}")
        assert hidden == []


class TestAccountImport:
    """The server-to-server account copy carries a whole account's bundle as
    ONE JSON body, so the ordinary JSON ceiling would 413 a big account."""

    def test_the_import_route_gets_its_own_larger_ceiling(self):
        client = _app(json_max_bytes=1024, account_import_max_bytes=64 * 1024)
        r = client.post(ACCOUNT_IMPORT_PATH, content=b"a" * 8192,
                        headers={"content-type": "application/json"})
        assert r.status_code == 200

    def test_the_import_route_over_its_own_ceiling_is_still_refused(self):
        client = _app(json_max_bytes=1024, account_import_max_bytes=4096)
        r = client.post(ACCOUNT_IMPORT_PATH, content=b"a" * 8192,
                        headers={"content-type": "application/json"})
        assert r.status_code == 413

    def test_the_import_ceiling_is_an_exact_path_match_not_a_prefix(self):
        client = _app(json_max_bytes=1024, account_import_max_bytes=64 * 1024)
        r = client.post(ACCOUNT_IMPORT_PATH + "/x", content=b"a" * 8192,
                        headers={"content-type": "application/json"})
        assert r.status_code == 413

    def test_the_constant_names_the_mounted_import_route(self):
        """If the route moves, the ceiling must move with it."""
        from main import app

        assert app.url_path_for("import_") == ACCOUNT_IMPORT_PATH

    def test_the_import_ceiling_is_far_above_the_json_ceiling(self):
        assert DEFAULT_ACCOUNT_IMPORT_MAX_BYTES >= 200 * 1024 * 1024
        assert DEFAULT_ACCOUNT_IMPORT_MAX_BYTES > DEFAULT_JSON_MAX_BYTES


class TestPassThrough:
    def test_a_get_is_untouched(self):
        assert _app(json_max_bytes=1).get("/ping").status_code == 200


class TestProductionCeilings:
    """The shipped values must clear the largest body each path honestly
    sends, or the backstop would refuse legitimate traffic."""

    def test_multipart_ceiling_clears_the_document_upload_cap(self):
        from routes.documents import MAX_FILE_SIZE

        assert DEFAULT_MULTIPART_MAX_BYTES > MAX_FILE_SIZE

    def test_json_ceiling_clears_the_base64_flashcard_import(self):
        from services.flashcards.import_flow import MAX_UPLOAD_BYTES

        # base64 inflates by 4/3, plus the surrounding JSON object.
        assert DEFAULT_JSON_MAX_BYTES > MAX_UPLOAD_BYTES * 4 / 3

    def test_json_ceiling_clears_every_bounded_base64_field(self):
        """#890 bounded each base64 JSON field at parse time; the backstop
        must sit above the largest of those bounds, or it would answer 413
        where the route has its own, better-worded 422."""
        from models import AchievementIconBody, CosmeticAssetBody
        from routes.flashcards import ImportParseBody
        from routes.profile import _AvatarUploadBody

        fields = (
            (_AvatarUploadBody, "file_b64"),
            (ImportParseBody, "payload"),
            (AchievementIconBody, "file_base64"),
            (CosmeticAssetBody, "file_base64"),
        )
        for model, name in fields:
            bound = next(m.max_length for m in model.model_fields[name].metadata
                         if getattr(m, "max_length", None))
            assert DEFAULT_JSON_MAX_BYTES > bound + 64 * 1024, f"{model.__name__}.{name}"
