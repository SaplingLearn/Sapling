"""Issue-report screenshots against REAL Supabase Storage.

The unit tests (tests/test_issue_screenshot_auth.py) stub the storage client,
so they prove the route's contract but not that the object exists where the
returned path says. This uploads through the real route, files a report with
the returned path, and reads the object back out of Storage by the path the
report kept.

The reads do not go back through the code under test: the report row is read
with raw SQL (`db_conn`), and the object is fetched from the Storage API with
this test's own request.
"""
import httpx
import pytest

from services.encryption import decrypt_if_present
from tests.integration.conftest import USER_ACTIVE

pytestmark = pytest.mark.integration

BUCKET = "issues-media-files"
PNG = b"\x89PNG\r\n\x1a\n" + b"integration screenshot " * 64
TOPIC = "integration: screenshot round trip"


def _storage(method: str, path: str) -> httpx.Response:
    from db.connection import SUPABASE_KEY, SUPABASE_URL

    return httpx.request(
        method,
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        timeout=30.0,
    )


@pytest.fixture
def issue_bucket(db_conn):
    # A bare `supabase start` (this lane in CI) has no app buckets; the dev and
    # E2E stacks get this one from scripts/lib/local-common.sh. Private, as in
    # production.
    db_conn.execute(
        "INSERT INTO storage.buckets (id, name, public) VALUES (%s, %s, false) "
        "ON CONFLICT (id) DO NOTHING",
        (BUCKET, BUCKET),
    )


def test_screenshot_is_stored_at_the_path_the_report_keeps(authed_client, db_conn, issue_bucket):
    # The filename lies about the type; the extension must follow the content type.
    up = authed_client.post(
        "/api/issue-reports/screenshot",
        files={"file": ("evil.html", PNG, "image/png")},
    )
    assert up.status_code == 200, up.text
    path = up.json()["path"]
    assert path.startswith(f"{USER_ACTIVE}/")
    assert path.endswith(".png")

    try:
        filed = authed_client.post(
            "/api/issue-reports",
            json={
                "user_id": USER_ACTIVE,
                "topic": TOPIC,
                "description": "The screenshot is attached.",
                "screenshot_urls": [path],
            },
        )
        assert filed.status_code == 200, filed.text
        # The seed already holds a report for this user, so pick ours by topic.
        rows = db_conn.execute(
            "SELECT topic, screenshot_urls FROM issue_reports WHERE user_id = %s", (USER_ACTIVE,)
        ).fetchall()
        kept = [r["screenshot_urls"] for r in rows if decrypt_if_present(r["topic"]) == TOPIC]
        assert kept == [[path]]

        got = _storage("GET", kept[0][0])
        assert got.status_code == 200, got.text
        assert got.content == PNG
        assert got.headers["content-type"] == "image/png"
    finally:
        _storage("DELETE", path)


def test_missing_bucket_is_a_502_not_a_500(authed_client, monkeypatch):
    """What production looked like before the bucket existed: Storage's own
    answer is mapped to a 502, on the real client and the real error body."""
    from services import storage_service

    monkeypatch.setattr(storage_service, "ISSUE_BUCKET", "issues-media-files-not-created")
    up = authed_client.post(
        "/api/issue-reports/screenshot",
        files={"file": ("shot.png", PNG, "image/png")},
    )
    assert up.status_code == 502, up.text
    assert "Bucket not found" in up.json()["detail"]
