"""The request-body ceiling (services/body_limit.py).

Before this, nothing bounded how many bytes a client could send. FastAPI
materialises a JSON body in memory before validation, so a `str` field with
no `max_length` was a direct route to exhausting the worker: the Pydantic
bound rejected the value only AFTER the allocation that would kill the
process.
"""

import io

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.body_limit import (
    DEFAULT_JSON_MAX_BYTES,
    DEFAULT_MULTIPART_MAX_BYTES,
    BodySizeLimitMiddleware,
)


def _app(**limits) -> TestClient:
    """A minimal app behind the middleware, so these tests pin the
    middleware's own behaviour rather than any particular route's."""
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, **limits)

    @app.post("/echo")
    async def echo(body: dict | None = None):
        return {"ok": True}

    @app.post("/upload")
    async def upload():
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
