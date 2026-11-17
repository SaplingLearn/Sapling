"""Abuse guards on the routes that cost money or reach other people.

* Rate limits (services/abuse_limits.py): every guarded route answers 429 with
  ``Retry-After`` and a plain sentence once its budget is spent, before doing
  any work; public routes are keyed by client address.
* Request-body bounds (models/__init__.py, routes/notes.py): an overlong free
  text field or an unknown enum value is a 422 before the handler runs.
* Study-room messages carry the sender's server-side name, never the client's.
* Uploads are checked by extension AND signature, and capped while reading.
* Failures answer with generic text; the exception stays in the log.
"""
import io
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import abuse_limits, request_limits
from tests.split_patches import patch_documents, patch_social
from tests.upload_fixtures import PDF_BYTES, PNG_BYTES, docx_bytes

client = TestClient(app)

#: TestClient's `request.client.host`.
TESTCLIENT_IP = "testclient"


@contextmanager
def _issue_storage(status: int = 200):
    """Stub the async Storage client behind ``storage_service.upload_issue_screenshot``;
    yields the AsyncMock behind its ``put``."""
    put = AsyncMock(return_value=MagicMock(status_code=status, text=""))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=MagicMock(put=put))
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("services.storage_service.httpx.AsyncClient", return_value=ctx):
        yield put


def _exhaust(limit: request_limits.AbuseLimit, subject: str) -> None:
    """Spend `subject`'s whole budget under `limit`, as earlier calls would."""
    for _ in range(limit.limit):
        assert request_limits.check_rate_limit(
            f"{limit.name}:{subject}", limit=limit.limit, window_sec=limit.window_sec,
        ) is None


# Routes whose crisis screen (docs/safety/crisis-support.md) reads the note
# before any limit applies, so that a 429 carries the card when the note
# matched. That one read of the student's own note is the only table access
# allowed past a spent budget there; nothing is written and no model runs.
_CRISIS_SCREENS_NOTE = ("/summarize", "/extract-concepts", "/chat", "/send-to-tutor")


def _assert_no_handler_db(db, path: str = "") -> None:
    """No table was read or written, apart from the feature-flag snapshot a
    router-level nav gate reads (services/feature_flags.py) and, on the note
    routes the crisis screen covers, the read of the note itself."""
    allowed = ["feature_flag"]
    if path.startswith("/api/notes/") and path.endswith(_CRISIS_SCREENS_NOTE):
        allowed.append("/rest/v1/notes")
    reads = [c.args[0] for c in db.get.call_args_list if c.args]
    writes = [c.args[0] for verb in (db.post, db.patch, db.delete)
              for c in verb.call_args_list if c.args]
    assert all(any(a in p for a in allowed) for p in reads), reads
    assert all("feature_flag" in p for p in writes), writes


def _assert_rate_limited(r, limit: request_limits.AbuseLimit) -> None:
    assert r.status_code == 429, r.text
    retry = int(r.headers["Retry-After"])
    assert 1 <= retry <= limit.window_sec
    detail = r.json()["detail"]
    assert detail.startswith(limit.detail) and "Try again in" in detail
    # The frontend's humanizeError shows a short plain sentence as is.
    assert len(detail) <= 160 and not any(c in detail for c in "{}[]<>\n")


# ── 429 once the budget is spent ────────────────────────────────────────────

JSON_ROUTES = [
    # (limit, subject, method, path, body)
    (abuse_limits.TUTOR_TURN, "u1", "post", "/api/learn/chat",
     {"session_id": "s1", "user_id": "u1", "message": "hi"}),
    (abuse_limits.TUTOR_TURN, "u1", "post", "/api/learn/chat/stream",
     {"session_id": "s1", "user_id": "u1", "message": "hi"}),
    (abuse_limits.TUTOR_TURN, "u1", "post", "/api/learn/action",
     {"session_id": "s1", "user_id": "u1", "action_type": "hint"}),
    (abuse_limits.TUTOR_TURN, "u1", "post", "/api/learn/mode-switch",
     {"session_id": "s1", "user_id": "u1", "new_mode": "expository"}),
    (abuse_limits.TUTOR_SESSION_START, "u1", "post", "/api/learn/start-session",
     {"user_id": "u1", "topic": "Recursion"}),
    (abuse_limits.TUTOR_SESSION_START, "u1", "post", "/api/learn/start-session/stream",
     {"user_id": "u1", "topic": "Recursion"}),
    (abuse_limits.NOTE_AI_ACTION, "u1", "post", "/api/notes/n1/summarize", {"user_id": "u1"}),
    (abuse_limits.NOTE_AI_ACTION, "u1", "post", "/api/notes/n1/extract-concepts", {"user_id": "u1"}),
    (abuse_limits.NOTE_AI_ACTION, "u1", "post", "/api/notes/n1/chat",
     {"user_id": "u1", "message": "explain"}),
    (abuse_limits.NOTE_LOOKUP, "u1", "post", "/api/notes/n1/send-to-tutor", {"user_id": "u1"}),
    (abuse_limits.NOTE_LOOKUP, "u1", "post", "/api/notes/n1/generate-quiz", {"user_id": "u1"}),
    (abuse_limits.SOCIAL_MESSAGE_SEND, "u1", "post", "/api/social/rooms/r1/messages",
     {"user_id": "u1", "text": "hello"}),
    (abuse_limits.SOCIAL_MESSAGE_EDIT, "u1", "patch", "/api/social/rooms/r1/messages/m1",
     {"user_id": "u1", "text": "edited"}),
    (abuse_limits.SOCIAL_REACTION, "u1", "post", "/api/social/rooms/r1/messages/m1/reactions",
     {"user_id": "u1", "emoji": "👍"}),
    # Session-authenticated: keyed by the session user (the conftest stub).
    (abuse_limits.FEEDBACK_SUBMIT, "user_andres", "post", "/api/feedback",
     {"user_id": "user_andres", "type": "global", "rating": 3}),
    (abuse_limits.ISSUE_REPORT_SUBMIT, "user_andres", "post", "/api/issue-reports",
     {"user_id": "user_andres", "topic": "Bug", "description": "It broke"}),
    # Public: TestClient's "testclient" is not a public address, so it falls
    # under the shared ceiling (request_limits.public_route_limit).
    (abuse_limits.NEWSLETTER_SUBSCRIBE_SHARED, "shared", "post", "/api/newsletter/subscribe",
     {"email": "x@example.com"}),
]


@pytest.mark.parametrize(
    "limit,subject,method,path,body", JSON_ROUTES,
    ids=[f"{m.upper()} {p}" for _, _, m, p, _ in JSON_ROUTES],
)
def test_json_route_answers_429_once_its_budget_is_spent(limit, subject, method, path, body):
    _exhaust(limit, subject)
    # Nothing past the gate may run: any DB access would fail the test.
    with patch("db.connection._client") as db:
        r = getattr(client, method)(path, json=body)
    _assert_rate_limited(r, limit)
    _assert_no_handler_db(db, path)


_NO_MODEL_NOTE_ACTIONS = [
    ("/api/notes/n1/generate-quiz", {"concept_node_id": "g1", "concept_name": "Recursion"}),
    ("/api/notes/n1/send-to-tutor", {"topic": "Recursion notes", "course_id": None, "preface": ""}),
]


@pytest.mark.parametrize("path,answer", _NO_MODEL_NOTE_ACTIONS, ids=[p for p, _ in _NO_MODEL_NOTE_ACTIONS])
def test_a_note_action_that_runs_no_model_spends_no_note_ai_unit(path, answer):
    """generate-quiz picks a linked concept (the quiz itself is generated, and
    limited, by /api/quiz/generate); send-to-tutor hands the note to a tutor
    session (limited by /api/learn/start-session). Neither runs a model, so a
    spent note-AI budget does not refuse them and they spend none of it: they
    have their own cheap budget (NOTE_LOOKUP) instead."""
    from unittest.mock import AsyncMock

    linked = [{"id": "g1", "concept_name": "Recursion", "mastery_score": 0.2}]
    note = {"id": "n1", "user_id": "u1", "title": "Recursion notes", "offering_id": None}
    with patch("routes.notes.get_note", AsyncMock(return_value=note)), \
         patch("routes.notes.list_linked_concepts", AsyncMock(return_value=linked)):
        assert client.post(path, json={"user_id": "u1"}).status_code == 200
        _exhaust(abuse_limits.NOTE_AI_ACTION, "u1")  # every unit was still there to spend
        r = client.post(path, json={"user_id": "u1"})
    assert r.status_code == 200, r.text
    assert r.json() == answer


def test_no_model_note_actions_share_a_budget_of_their_own():
    lookup, ai = abuse_limits.NOTE_LOOKUP, abuse_limits.NOTE_AI_ACTION
    assert lookup.name != ai.name
    assert lookup.limit > ai.limit  # cheaper: no model behind it


def _pdf_upload():
    return {"file": ("notes.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}


@pytest.mark.parametrize("path", ["/api/documents/upload/sync", "/api/documents/upload"])
def test_document_upload_answers_429_once_its_budget_is_spent(path):
    _exhaust(abuse_limits.DOCUMENT_UPLOAD, "u1")
    with patch_documents("_validate_user", return_value=None), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch_documents("extract_text_from_file") as ocr:
        r = client.post(path, files=_pdf_upload(), data={"course_id": "c1", "user_id": "u1"})
    _assert_rate_limited(r, abuse_limits.DOCUMENT_UPLOAD)
    ocr.assert_not_called()


def test_a_replayed_upload_is_not_charged():
    """A retry with the same X-Request-ID returns the stored row; only a new
    upload spends the budget."""
    _exhaust(abuse_limits.DOCUMENT_UPLOAD, "u1")
    stored = {"id": "doc-1", "file_name": "notes.pdf"}
    with patch_documents("_validate_user", return_value=None), \
         patch_documents("_existing_doc_by_request_id", return_value=stored):
        r = client.post("/api/documents/upload/sync", files=_pdf_upload(),
                        data={"course_id": "c1", "user_id": "u1"})
    assert r.status_code == 200 and r.json()["id"] == "doc-1"


def test_syllabus_extract_answers_429_once_its_budget_is_spent():
    _exhaust(abuse_limits.SYLLABUS_EXTRACT, "u1")
    with patch("routes.calendar.extract_assignments_from_file") as run:
        r = client.post("/api/calendar/extract", files={"file": ("s.pdf", PDF_BYTES, "application/pdf")},
                        data={"user_id": "u1"})
    _assert_rate_limited(r, abuse_limits.SYLLABUS_EXTRACT)
    run.assert_not_called()


def test_issue_screenshot_answers_429_once_its_budget_is_spent():
    _exhaust(abuse_limits.ISSUE_SCREENSHOT_UPLOAD, "user_andres")
    with _issue_storage() as put:
        r = client.post("/api/issue-reports/screenshot",
                        files={"file": ("s.png", PNG_BYTES, "image/png")})
    _assert_rate_limited(r, abuse_limits.ISSUE_SCREENSHOT_UPLOAD)
    put.assert_not_called()


CAREERS_FORM = {
    "position": "Engineer", "full_name": "Ada Lovelace",
    "email": "ada@example.com", "linkedin_url": "https://www.linkedin.com/in/ada",
}


def test_careers_apply_is_limited_per_client_address():
    _exhaust(abuse_limits.CAREERS_APPLY, "9.9.9.9")
    with patch("services.request_limits.client_ip", return_value="9.9.9.9"), \
         patch("routes.careers.table") as t:
        r = client.post("/api/careers/apply", data=CAREERS_FORM)
    _assert_rate_limited(r, abuse_limits.CAREERS_APPLY)
    t.assert_not_called()


def test_public_budgets_are_per_address_not_global():
    """Another address's spent budget does not limit this one."""
    _exhaust(abuse_limits.CAREERS_APPLY, "9.9.9.9")
    with patch("services.request_limits.client_ip", return_value="1.1.1.1"), \
         patch("routes.careers.httpx"), patch("routes.careers.table") as t:
        t.return_value.insert.return_value = [{"id": "app1"}]
        r = client.post("/api/careers/apply", data=CAREERS_FORM)
    assert r.status_code == 200


def test_a_proxy_address_falls_under_the_shared_ceiling_not_the_strict_one():
    """Behind an untrusted proxy every caller shares its private address: the
    strict per-address budget would lock everyone out at once, so the looser
    shared ceiling applies instead."""
    _exhaust(abuse_limits.CAREERS_APPLY, "10.0.0.5")
    with patch("services.request_limits.client_ip", return_value="10.0.0.5"), \
         patch("routes.careers.httpx"), patch("routes.careers.table") as t:
        t.return_value.insert.return_value = [{"id": "app1"}]
        r = client.post("/api/careers/apply", data=CAREERS_FORM)
    assert r.status_code == 200


def test_the_shared_ceiling_still_stops_a_flood_from_behind_a_proxy():
    _exhaust(abuse_limits.CAREERS_APPLY_SHARED, "shared")
    with patch("services.request_limits.client_ip", return_value="10.0.0.5"), \
         patch("routes.careers.table") as t:
        r = client.post("/api/careers/apply", data=CAREERS_FORM)
    _assert_rate_limited(r, abuse_limits.CAREERS_APPLY_SHARED)
    t.assert_not_called()


@pytest.mark.parametrize("host,public", [
    ("203.0.113.9", False),  # TEST-NET documentation range: not global
    ("8.8.8.8", True), ("2606:4700:4700::1111", True),
    ("10.0.0.5", False), ("100.64.0.1", False), ("127.0.0.1", False),
    ("::1", False), ("testclient", False), ("unknown", False),
])
def test_only_globally_routable_addresses_count_as_public(host, public):
    assert request_limits.is_public_address(host) is public


def test_a_forwarding_header_does_not_buy_a_fresh_budget():
    """The address is request.client, never a client-set header."""
    _exhaust(abuse_limits.NEWSLETTER_SUBSCRIBE_SHARED, "shared")
    r = client.post("/api/newsletter/subscribe", json={"email": "x@example.com"},
                    headers={"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "198.51.100.7"})
    assert r.status_code == 429


def test_budgets_are_per_user():
    """One student's spent tutor budget never limits another's."""
    _exhaust(abuse_limits.TUTOR_TURN, "someone-else")
    # the loop's entry check (#761) is the first step past the limiter
    with patch("services.tutor.turns._require_turn_session", side_effect=HTTPException(404, "x")):
        r = client.post("/api/learn/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 404  # past the limiter


def test_the_multiplier_scales_every_budget(monkeypatch):
    monkeypatch.setenv(request_limits.ABUSE_LIMIT_MULTIPLIER_ENV, "100")
    assert request_limits.abuse_limit("x", limit=3, window_sec=60, detail="d").limit == 300
    for bad in ("0", "-1", "lots", "1.5"):
        monkeypatch.setenv(request_limits.ABUSE_LIMIT_MULTIPLIER_ENV, bad)
        assert request_limits.abuse_limit("x", limit=3, window_sec=60, detail="d").limit == 3


def test_every_limit_is_documented_and_sane():
    limits = [v for v in vars(abuse_limits).values() if isinstance(v, request_limits.AbuseLimit)]
    assert len(limits) >= 12
    assert len({lim.name for lim in limits}) == len(limits), "each budget has its own key"
    for lim in limits:
        assert lim.limit >= 1 and lim.window_sec >= 60
        assert lim.detail.endswith((".", "!")) and len(lim.detail) < 100


# ── 422 on overlong fields and unknown enum values ──────────────────────────

LONG = "x" * 8001

OVERLONG = [
    ("post", "/api/learn/chat", {"session_id": "s1", "user_id": "u1", "message": LONG}),
    ("post", "/api/learn/chat/stream", {"session_id": "s1", "user_id": "u1", "message": LONG}),
    ("post", "/api/learn/chat", {"session_id": "s1", "user_id": "u1", "message": "hi", "mode": "evil"}),
    ("post", "/api/learn/start-session", {"user_id": "u1", "topic": "t", "mode": "Socratic!"}),
    ("post", "/api/learn/action", {"session_id": "s1", "user_id": "u1", "action_type": "solve-it"}),
    ("post", "/api/notes/n1/chat", {"user_id": "u1", "message": LONG}),
    ("post", "/api/notes", {"user_id": "u1", "course_id": "c1", "body": "x" * 200_001}),
    ("post", "/api/notes", {"user_id": "u1", "course_id": "c1", "title": "x" * 301}),
    ("post", "/api/notes", {"user_id": "u1", "course_id": "c1", "tags": ["t"] * 51}),
    ("patch", "/api/notes/n1", {"user_id": "u1", "body": "x" * 200_001}),
    ("patch", "/api/notes/n1", {"user_id": "u1", "title": "x" * 301}),
    ("post", "/api/social/rooms/r1/messages", {"user_id": "u1", "text": "x" * 4001}),
    ("patch", "/api/social/rooms/r1/messages/m1", {"user_id": "u1", "text": "x" * 4001}),
    ("post", "/api/social/rooms/r1/messages/m1/reactions", {"user_id": "u1", "emoji": "x" * 33}),
    ("patch", "/api/profile/u1", {"bio": "x" * 501}),
    ("post", "/api/issue-reports", {"user_id": "u1", "topic": "t", "description": "x" * 10_001}),
    ("post", "/api/issue-reports", {"user_id": "u1", "topic": "t", "description": "d",
                                    "screenshot_urls": ["p"] * 11}),
    ("post", "/api/feedback", {"user_id": "u1", "type": "global", "rating": 3, "comment": "x" * 10_001}),
    ("post", "/api/feedback", {"user_id": "u1", "type": "global", "rating": 99}),
    ("post", "/api/feedback", {"user_id": "u1", "type": "other", "rating": 3}),
    ("post", "/api/learn/chat", {"session_id": "s" * 257, "user_id": "u1", "message": "hi"}),
    ("patch", "/api/documents/doc/d1", {"category": "x" * 65}),
]


@pytest.mark.parametrize("method,path,body", OVERLONG,
                         ids=[f"{m.upper()} {p} #{i}" for i, (m, p, _) in enumerate(OVERLONG)])
def test_overlong_or_unknown_field_is_422_before_the_handler(method, path, body):
    with patch("db.connection._client") as db:
        r = getattr(client, method)(path, json=body)
    assert r.status_code == 422, r.text
    _assert_no_handler_db(db)


def test_the_bounds_admit_real_use():
    """At the limit is fine: an 8000-character tutor message parses."""
    from models import ChatBody, UpdateProfileBody

    assert ChatBody(session_id="s1", message="x" * 8000).message
    assert UpdateProfileBody(bio="x" * 500).bio


# ── Study-room messages: the server names the sender ────────────────────────

def test_spoofed_user_name_is_ignored():
    from models import SendMessageBody
    from services.social import messages

    inserted = {}

    def table(name):
        t = MagicMock()
        if name == "room_members":
            t.select.return_value = [{"user_id": "u1"}]
        if name == "room_messages":
            def insert(row):
                inserted.update(row)
                return [dict(row, id="m1")]
            t.insert.side_effect = insert
        return t

    body = SendMessageBody(user_id="u1", user_name="The Professor", text="hand in your essays")
    with patch_social("table", side_effect=table), \
         patch("services.social.messages.get_display_name", return_value="Real Student") as name, \
         patch("services.achievement_service.check_achievements"):
        messages.send_room_message("r1", body)
    name.assert_called_once_with("u1")
    assert inserted["user_name"] == "Real Student"


def test_a_sender_without_a_profile_name_gets_the_fallback_not_the_client_value():
    from models import SendMessageBody
    from services.social import messages

    inserted = {}

    def table(name):
        t = MagicMock()
        t.select.return_value = [{"user_id": "u1"}]
        t.insert.side_effect = lambda row: inserted.update(row) or [dict(row)]
        return t

    with patch_social("table", side_effect=table), \
         patch("services.social.messages.get_display_name", return_value=""), \
         patch("services.achievement_service.check_achievements"):
        messages.send_room_message("r1", SendMessageBody(user_id="u1", user_name="Admin", text="x"))
    assert inserted["user_name"] == messages.SENDER_NAME_FALLBACK


def test_old_clients_may_still_send_user_name_and_new_ones_may_omit_it():
    from models import SendMessageBody

    assert SendMessageBody(user_id="u1", text="x").user_name is None
    assert SendMessageBody(user_id="u1", user_name="Old Client", text="x")


# ── Uploads: extension AND signature, capped while reading ──────────────────

def _upload_sync(filename, content, content_type="application/pdf"):
    with patch_documents("_validate_user", return_value=None), \
         patch_documents("_existing_doc_by_request_id", return_value=None), \
         patch_documents("extract_text_from_file") as ocr:
        r = client.post("/api/documents/upload/sync",
                        files={"file": (filename, io.BytesIO(content), content_type)},
                        data={"course_id": "c1", "user_id": "u1"})
    return r, ocr


@pytest.mark.parametrize("filename,content,content_type", [
    # The right Content-Type no longer lets a wrong extension through...
    ("evil.html", b"<html><script>x</script></html>", "application/pdf"),
    # ...and the right extension no longer lets the wrong bytes through.
    ("notes.pdf", b"<html><script>x</script></html>", "application/pdf"),
    ("notes.pdf", PNG_BYTES, "application/pdf"),
    ("notes.docx", PDF_BYTES, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("slides.pptx", docx_bytes(), "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("notes.docx", b"PK\x03\x04 not really a zip", "application/octet-stream"),
])
def test_document_upload_needs_extension_and_signature(filename, content, content_type):
    r, ocr = _upload_sync(filename, content, content_type)
    assert r.status_code == 400, r.text
    ocr.assert_not_called()


def test_document_upload_uses_the_sniffed_type_not_the_declared_one():
    r, ocr = _upload_sync("notes.pdf", PDF_BYTES, "text/html")
    # Past validation (extraction is mocked to return nothing usable -> 422).
    assert r.status_code == 422
    assert ocr.call_args.args[2] == "application/pdf"


def test_document_upload_stops_reading_at_the_cap(monkeypatch):
    """An oversize upload is refused after at most one chunk past the cap,
    not read whole first."""
    from services import upload_validation

    monkeypatch.setattr("routes.documents.MAX_FILE_SIZE", 1024 * 1024)
    reads = []
    real_read = upload_validation.UploadFile.read

    async def counting_read(self, size=-1):
        data = await real_read(self, size)
        reads.append(len(data))
        return data

    monkeypatch.setattr(upload_validation.UploadFile, "read", counting_read)
    r, ocr = _upload_sync("big.pdf", b"%PDF-" + b"0" * (8 * 1024 * 1024))
    assert r.status_code == 400 and "1 MB" in r.json()["detail"]
    assert sum(reads) <= 2 * 1024 * 1024
    ocr.assert_not_called()


@pytest.mark.parametrize("filename,content", [
    ("syllabus.exe", b"MZ\x90\x00"),
    ("syllabus.pdf", b"MZ\x90\x00 not a pdf"),
    ("syllabus.png", PDF_BYTES),
])
def test_syllabus_extract_rejects_mistyped_files(filename, content):
    with patch("routes.calendar.extract_assignments_from_file") as run:
        r = client.post("/api/calendar/extract", files={"file": (filename, content, "application/pdf")},
                        data={"user_id": "u1"})
    assert r.status_code == 400
    run.assert_not_called()


def test_syllabus_extract_rejects_an_oversize_file(monkeypatch):
    monkeypatch.setattr("services.calendar_service.EXTRACT_MAX_BYTES", 1024)
    with patch("routes.calendar.extract_assignments_from_file") as run:
        r = client.post("/api/calendar/extract",
                        files={"file": ("s.pdf", PDF_BYTES + b"0" * 2048, "application/pdf")},
                        data={"user_id": "u1"})
    assert r.status_code == 413
    run.assert_not_called()


def test_issue_screenshot_rejects_markup_labelled_as_an_image():
    with _issue_storage() as put:
        r = client.post("/api/issue-reports/screenshot",
                        files={"file": ("shot.png", b"<svg onload='alert(1)'/>", "image/png")})
    assert r.status_code == 415
    put.assert_not_called()


def test_issue_screenshot_is_stored_as_what_its_bytes_are():
    from tests.upload_fixtures import JPEG_BYTES

    with _issue_storage() as put:
        r = client.post("/api/issue-reports/screenshot",
                        files={"file": ("shot.html", JPEG_BYTES, "image/png")})
    assert r.status_code == 200
    assert r.json()["path"].endswith(".jpg")
    assert put.call_args.kwargs["headers"]["Content-Type"] == "image/jpeg"


def test_careers_resume_must_be_a_document_by_its_bytes():
    with patch("routes.careers.httpx") as hx, patch("routes.careers.table"):
        r = client.post("/api/careers/apply", data=CAREERS_FORM,
                        files={"resume": ("cv.pdf", b"<html>not a pdf</html>", "application/pdf")})
    assert r.status_code == 415
    hx.put.assert_not_called()


# ── Generic error text ──────────────────────────────────────────────────────

SECRET = "SECRET_INTERNALS: connect to 10.0.0.5 failed (/srv/app/creds.json)"


def test_syllabus_extract_failure_is_generic():
    with patch("routes.calendar.extract_assignments_from_file", side_effect=RuntimeError(SECRET)):
        r = client.post("/api/calendar/extract",
                        files={"file": ("s.pdf", PDF_BYTES, "application/pdf")}, data={"user_id": "u1"})
    assert r.status_code == 200
    assert SECRET not in r.text and "10.0.0.5" not in r.text
    assert r.json()["assignments"] == []


def test_pdf_ocr_failure_is_generic():
    with patch("routes.extract.extract_text_from_pdf_native", return_value=("", 0)), \
         patch("routes.extract.extract_text_from_pdf_ocr", side_effect=ValueError(SECRET)):
        r = client.post("/api/extract/pdf", files={"file": ("a.pdf", PDF_BYTES, "application/pdf")})
    assert r.status_code == 500
    assert SECRET not in r.text and "10.0.0.5" not in r.text


def test_ocr_unavailable_is_generic():
    with patch("routes.extract.extract_text_from_image_bytes",
               side_effect=RuntimeError("tesseract not found at /usr/local/bin/tesseract")):
        r = client.post("/api/extract/image", files={"file": ("a.png", PNG_BYTES, "image/png")})
    assert r.status_code == 503
    assert "/usr/local/bin" not in r.text


def test_gradescope_upstream_failure_is_generic():
    import services.gradescope_service as gs
    from tests.split_patches import patch_gradescope

    with patch_gradescope("table"), \
         patch.object(gs, "login", side_effect=gs.GradescopeFetchError(f"Failed to list courses: {SECRET}")):
        r = client.post("/api/gradescope/credentials", json={
            "user_id": "u1", "email": "s@example.edu", "password": "pw",
        })
    assert r.status_code == 502
    assert SECRET not in r.text and "10.0.0.5" not in r.text
