"""
GET /api/users (the bulk roster) is gone.

It returned every user's decrypted legal name and current room. #156 put it
behind a session, but any signed-in student could still pull the whole
roster, and its only caller (UserContext, on every page load) discarded the
result unread. The admin screens use the paginated admin user list instead,
so the route was deleted rather than re-gated: nothing can leak through an
endpoint that no longer exists.
"""
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_get_api_users_returns_no_roster_to_a_signed_in_user():
    # The autouse bypass makes this a signed-in request.
    r = client.get("/api/users")
    assert r.status_code in (404, 405)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    assert "users" not in body
