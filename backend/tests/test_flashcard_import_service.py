"""Unit tests for services.flashcard_import_service."""
import io
import os
import sqlite3
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic_ai.exceptions import ContentFilterError, ModelHTTPError, UnexpectedModelBehavior

from services import flashcard_import_service as svc


# ── dedup_against_existing ───────────────────────────────────────────────────

class TestDedup:
    def _existing_rows(self, fronts):
        return [{"front": f} for f in fronts]

    def test_skips_exact_match(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = self._existing_rows(["What is mitosis?"])
            new = [{"front": "What is mitosis?", "back": "Cell division."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == []
        assert skipped == new

    def test_skips_near_match_within_levenshtein_3(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = self._existing_rows(["What is mitosis?"])
            new = [{"front": "what is mitosis", "back": "Cell division."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == []
        assert len(skipped) == 1

    def test_keeps_distinct_card(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = self._existing_rows(["What is mitosis?"])
            new = [{"front": "What is photosynthesis?", "back": "Plants making food."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == new
        assert skipped == []

    def test_filters_by_offering_id(self):
        # Migration 0025 renamed the flashcards link column course_id -> offering_id.
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = []
            svc.dedup_against_existing("u1", "off1", [])
            _, kwargs = t.return_value.select.call_args
            assert kwargs["filters"] == {"user_id": "eq.u1", "offering_id": "eq.off1"}

    def test_filters_by_topic_when_offering_id_is_none(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = []
            svc.dedup_against_existing("u1", None, [], topic="Bio")
            call_kwargs = t.return_value.select.call_args
            assert "Bio" in str(call_kwargs)
            assert "offering_id" not in str(call_kwargs)
            assert "course_id" not in str(call_kwargs)

    def test_dedup_matches_against_encrypted_existing_cards(self):
        # #518: dedupe must be decrypt-aware — existing rows are ciphertext.
        from services.encryption import encrypt
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = [
                {"front": encrypt("What is a variable?")}
            ]
            new = [{"front": "What is a variable?", "back": "A named storage location."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == []
        assert skipped == new

    def test_dedup_still_matches_legacy_plaintext_rows(self):
        # Pre-backfill rows are still plaintext — decrypt_if_present falls
        # back to the raw value, so dedupe keeps working unchanged.
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = [{"front": "What is a variable?"}]
            new = [{"front": "What is a variable?", "back": "A named storage location."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == []
        assert skipped == new


# ── check_rate_limit ─────────────────────────────────────────────────────────

class TestRateLimit:
    def setup_method(self):
        svc._rate_state.clear()

    def test_allows_first_5_calls(self):
        for _ in range(5):
            assert svc.check_rate_limit("u1") is None

    def test_sixth_call_returns_retry_after(self):
        for _ in range(5):
            svc.check_rate_limit("u1")
        retry = svc.check_rate_limit("u1")
        assert retry is not None
        assert 0 < retry <= 60

    def test_isolated_per_user(self):
        for _ in range(5):
            svc.check_rate_limit("u1")
        assert svc.check_rate_limit("u2") is None

    def test_resets_after_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(svc.time, "time", lambda: now[0])
        for _ in range(5):
            svc.check_rate_limit("u1")
        now[0] = 1061.0  # past 60-second window
        assert svc.check_rate_limit("u1") is None

    def test_retry_capped_at_window_on_coincident_timestamps(self, monkeypatch):
        # Windows' coarse timer (~15.6ms tick) reliably lands a tight loop of
        # calls on the identical time.time() value, so elapsed == 0.0 exactly
        # and the retry hint must still stay within (0, window] (#346).
        monkeypatch.setattr(svc.time, "time", lambda: 1000.0)
        for _ in range(5):
            svc.check_rate_limit("u1")
        assert svc.check_rate_limit("u1") == 60

    def test_retry_uses_ceiling_of_remaining_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(svc.time, "time", lambda: now[0])
        for _ in range(5):
            svc.check_rate_limit("u1")
        now[0] = 1059.5  # 0.5s of the window left -> ceil to 1
        assert svc.check_rate_limit("u1") == 1


# ── parse_xlsx ───────────────────────────────────────────────────────────────

from openpyxl import Workbook


def _build_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestParseXlsx:
    def test_extracts_first_two_columns(self):
        bytes_ = _build_xlsx([
            ("Mitosis", "Cell division for somatic cells"),
            ("Meiosis", "Halving for gametes"),
        ])
        cards = svc.parse_xlsx(bytes_)
        assert cards == [
            {"front": "Mitosis", "back": "Cell division for somatic cells"},
            {"front": "Meiosis", "back": "Halving for gametes"},
        ]

    def test_skips_blank_rows(self):
        bytes_ = _build_xlsx([
            ("Mitosis", "Cell division"),
            ("", ""),
            ("Meiosis", "Halving"),
        ])
        cards = svc.parse_xlsx(bytes_)
        assert len(cards) == 2

    def test_ignores_extra_columns(self):
        bytes_ = _build_xlsx([
            ("Mitosis", "Cell division", "Bio", "Chapter 5"),
        ])
        cards = svc.parse_xlsx(bytes_)
        assert cards == [{"front": "Mitosis", "back": "Cell division"}]

    def test_handles_unicode(self):
        bytes_ = _build_xlsx([("π", "Pi — circumference / diameter 🥧")])
        cards = svc.parse_xlsx(bytes_)
        assert cards[0]["back"].startswith("Pi")


# ── parse_anki_apkg ──────────────────────────────────────────────────────────

def _build_apkg(notes: list[tuple[str, str]]) -> bytes:
    """Build a minimal .apkg = zip containing collection.anki2 SQLite with a
    single notes table whose flds field is \\x1f-separated."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp:
        path = tmp.name
    try:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)")
        for i, (front, back) in enumerate(notes):
            conn.execute("INSERT INTO notes (id, flds) VALUES (?, ?)", (i + 1, f"{front}\x1f{back}"))
        conn.commit()
        conn.close()
        with open(path, "rb") as f:
            db_bytes = f.read()
    finally:
        os.unlink(path)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("collection.anki2", db_bytes)
    return zip_buf.getvalue()


class TestParseAnki:
    def test_extracts_notes(self):
        bytes_ = _build_apkg([("Mitosis", "Cell division"), ("Meiosis", "Halving")])
        cards = svc.parse_anki_apkg(bytes_)
        assert cards == [
            {"front": "Mitosis", "back": "Cell division"},
            {"front": "Meiosis", "back": "Halving"},
        ]

    def test_strips_html(self):
        bytes_ = _build_apkg([("<b>Mitosis</b>", "<i>Cell</i> division <br>here")])
        cards = svc.parse_anki_apkg(bytes_)
        assert cards[0]["front"] == "Mitosis"
        assert "Cell division here" in cards[0]["back"]

    def test_raises_on_corrupt_zip(self):
        with pytest.raises(ValueError, match="Anki"):
            svc.parse_anki_apkg(b"not a zip file")

    def test_raises_when_collection_missing(self):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as z:
            z.writestr("media", "{}")
        with pytest.raises(ValueError, match="collection.anki2"):
            svc.parse_anki_apkg(zip_buf.getvalue())


# ── scrape_quizlet_url ───────────────────────────────────────────────────────

_QUIZLET_PAYLOAD = """
<html><body>
<script>window.Quizlet = window.Quizlet || {}; window.Quizlet["setPageData"] = {"set":{"id":1,"terms":[{"word":"Mitosis","definition":"Cell division"},{"word":"Meiosis","definition":"Halving"}]}};</script>
</body></html>
"""


_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("104.16.1.1", 443))]


def _addrinfo(ip):
    family = 10 if ":" in ip else 2
    return [(family, 1, 6, "", (ip, 443))]


@pytest.fixture(autouse=False)
def public_dns():
    """Hermetic DNS: every lookup answers one public address."""
    with patch(
        "services.flashcard_import_service.socket.getaddrinfo",
        return_value=_PUBLIC_ADDRINFO,
    ) as gai:
        yield gai


def _mock_client(handler):
    """A stand-in for ``_quizlet_client`` that builds a real httpx.Client over
    a MockTransport, so status codes, Location headers and the client's
    redirect setting all behave exactly as in production. Records every
    fetched URL and every client the scrape built."""
    seen: list[str] = []
    clients: list[httpx.Client] = []

    def _handler(request):
        seen.append(str(request.url))
        return handler(request)

    def _factory(resolver):
        c = httpx.Client(transport=httpx.MockTransport(_handler), follow_redirects=False)
        clients.append(c)
        return c

    _factory.seen = seen
    _factory.clients = clients
    return _factory


def _patch_client(handler):
    factory = _mock_client(handler)
    return factory, patch("services.flashcard_import_service._quizlet_client", side_effect=factory)


def _ok(request):
    return httpx.Response(200, text=_QUIZLET_PAYLOAD)


@pytest.mark.usefixtures("public_dns")
class TestScrapeQuizlet:
    def test_extracts_terms_from_set_page_data(self):
        _, p = _patch_client(_ok)
        with p:
            cards = svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert cards == [
            {"front": "Mitosis", "back": "Cell division"},
            {"front": "Meiosis", "back": "Halving"},
        ]

    def test_raises_on_login_wall(self):
        _, p = _patch_client(lambda r: httpx.Response(200, text="<html><body>Please log in</body></html>"))
        with p, pytest.raises(svc.QuizletBlocked):
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")

    def test_raises_on_403(self):
        _, p = _patch_client(lambda r: httpx.Response(403, text=""))
        with p, pytest.raises(svc.QuizletBlocked):
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")


@pytest.mark.usefixtures("public_dns")
class TestScrapeQuizletSSRF:
    """The URL is user-supplied: only https quizlet.com hosts resolving to
    public addresses may be fetched, at every redirect hop."""

    def test_allowlisted_url_fetched_once(self):
        factory, p = _patch_client(_ok)
        with p:
            cards = svc.scrape_quizlet_url("https://www.quizlet.com/123/abc")
        assert len(cards) == 2
        assert factory.seen == ["https://www.quizlet.com/123/abc"]

    def test_http_submission_upgraded_to_https(self):
        factory, p = _patch_client(_ok)
        with p:
            svc.scrape_quizlet_url("http://quizlet.com/123/abc")
        assert factory.seen == ["https://quizlet.com/123/abc"]

    def test_http_submission_on_explicit_port_80_upgraded(self):
        factory, p = _patch_client(_ok)
        with p:
            svc.scrape_quizlet_url("http://www.quizlet.com:80/123/abc?x=1")
        assert factory.seen == ["https://www.quizlet.com/123/abc?x=1"]

    def test_follows_allowlisted_redirect_on_one_client(self):
        def handler(request):
            if request.url.host == "quizlet.com":
                return httpx.Response(301, headers={"location": "https://www.quizlet.com/123/abc"})
            return httpx.Response(200, text=_QUIZLET_PAYLOAD)

        factory, p = _patch_client(handler)
        with p:
            cards = svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert len(cards) == 2
        assert factory.seen == ["https://quizlet.com/123/abc", "https://www.quizlet.com/123/abc"]
        assert len(factory.clients) == 1  # one client reused across hops

    def test_relative_redirect_stays_on_host(self):
        def handler(request):
            if request.url.path == "/old":
                return httpx.Response(302, headers={"location": "/123/abc"})
            return httpx.Response(200, text=_QUIZLET_PAYLOAD)

        factory, p = _patch_client(handler)
        with p:
            svc.scrape_quizlet_url("https://quizlet.com/old")
        assert factory.seen[-1] == "https://quizlet.com/123/abc"

    def test_dns_resolved_once_per_host_per_scrape(self, public_dns):
        def handler(request):
            n = int(request.url.params.get("n", "0"))
            if n < 3:
                return httpx.Response(302, headers={"location": f"https://quizlet.com/s?n={n + 1}"})
            return httpx.Response(200, text=_QUIZLET_PAYLOAD)

        _, p = _patch_client(handler)
        with p:
            svc.scrape_quizlet_url("https://quizlet.com/s")
        assert public_dns.call_count == 1

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/123/abc",
            "https://quizlet.com.evil.example/123",
            "https://notquizlet.com/123",
            "https://quizlet.com@evil.example/123",
            "https://user:pw@quizlet.com/123",
            "https://quizlet.com:8443/123",
            "http://quizlet.com:8080/123/abc",
            "ftp://quizlet.com/123",
            "file:///etc/passwd",
            "https://127.0.0.1/",
            "https://localhost/",
            "http://169.254.169.254/latest/meta-data/",
            "https://169.254.169.254/latest/meta-data/",
            "https://[::1]/",
            "https://10.0.0.5/",
            "not a url",
            "",
        ],
    )
    def test_rejects_non_quizlet_urls_without_fetching(self, url):
        factory, p = _patch_client(_ok)
        with p, pytest.raises(svc.QuizletURLRejected):
            svc.scrape_quizlet_url(url)
        assert factory.seen == []

    @pytest.mark.parametrize(
        "location",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/admin",
            "https://[::1]/",
            "https://localhost:8000/api/internal/metrics",
            "http://www.quizlet.com/123/abc",
            "https://evil.example.com/",
        ],
    )
    def test_redirect_to_disallowed_target_is_blocked_not_rejected(self, location):
        # A hop leaving the policy is upstream behaviour, not a bad student
        # input: 422-class QuizletBlocked (Paste fallback), never fetched.
        def handler(request):
            if request.url.host == "quizlet.com":
                return httpx.Response(302, headers={"location": location})
            raise AssertionError(f"disallowed hop was fetched: {request.url}")

        factory, p = _patch_client(handler)
        with p, pytest.raises(svc.QuizletBlocked, match="redirected away") as ei:
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert not isinstance(ei.value, svc.QuizletURLRejected)
        assert factory.seen == ["https://quizlet.com/123/abc"]

    def test_redirect_chain_over_cap_is_blocked_not_rejected(self):
        def handler(request):
            n = int(request.url.params.get("n", "0"))
            return httpx.Response(302, headers={"location": f"https://quizlet.com/loop?n={n + 1}"})

        factory, p = _patch_client(handler)
        with p, pytest.raises(svc.QuizletBlocked, match="too many times") as ei:
            svc.scrape_quizlet_url("https://quizlet.com/loop")
        assert not isinstance(ei.value, svc.QuizletURLRejected)
        assert len(factory.seen) == svc._QUIZLET_MAX_REDIRECTS + 1

    def test_redirect_chain_at_cap_allowed(self):
        cap = svc._QUIZLET_MAX_REDIRECTS

        def handler(request):
            n = int(request.url.params.get("n", "0"))
            if n < cap:
                return httpx.Response(302, headers={"location": f"https://quizlet.com/s?n={n + 1}"})
            return httpx.Response(200, text=_QUIZLET_PAYLOAD)

        _, p = _patch_client(handler)
        with p:
            assert len(svc.scrape_quizlet_url("https://quizlet.com/s")) == 2

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.9",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "0.0.0.0",
            "224.0.0.1",
            "240.0.0.1",
            "::1",
            "::",
            "fe80::1",
            "fc00::1",
            "ff02::1",
            "::ffff:127.0.0.1",
            "::ffff:169.254.169.254",
            "64:ff9b::7f00:1",  # NAT64 of 127.0.0.1
            "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
            "2002:7f00:1::1",  # 6to4 of 127.0.0.1
            "2002:a00:1::1",  # 6to4 of 10.0.0.1
            "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # Teredo
        ],
    )
    def test_allowlisted_host_resolving_to_internal_ip_refused(self, public_dns, ip):
        public_dns.return_value = _addrinfo(ip)
        factory, p = _patch_client(_ok)
        with p, pytest.raises(svc.QuizletURLRejected):
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert factory.seen == []

    @pytest.mark.parametrize(
        "ip",
        [
            "64:ff9b::6810:101",  # NAT64 (DNS64 answer) of 104.16.1.1
            "2002:6810:101::1",  # 6to4 of 104.16.1.1
            "2606:4700::6810:101",  # plain global IPv6
        ],
    )
    def test_ipv6_wrapping_a_public_ipv4_is_allowed(self, public_dns, ip):
        # An IPv6-only/DNS64 host sees Quizlet as 64:ff9b::<v4>: judged by the
        # embedded IPv4, not the (reserved) wrapper prefix.
        public_dns.return_value = _addrinfo(ip)
        _, p = _patch_client(_ok)
        with p:
            assert len(svc.scrape_quizlet_url("https://quizlet.com/123/abc")) == 2

    def test_any_internal_address_in_answer_refused(self, public_dns):
        public_dns.return_value = _PUBLIC_ADDRINFO + _addrinfo("10.0.0.1")
        factory, p = _patch_client(_ok)
        with p, pytest.raises(svc.QuizletURLRejected):
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert factory.seen == []

    def test_redirect_hop_rechecks_dns(self, public_dns):
        # First host resolves public; the redirect target's lookup answers a
        # metadata address — the hop must be refused before it is fetched.
        public_dns.side_effect = [_PUBLIC_ADDRINFO, _addrinfo("169.254.169.254")]

        def handler(request):
            if request.url.host == "quizlet.com":
                return httpx.Response(301, headers={"location": "https://www.quizlet.com/123/abc"})
            raise AssertionError("internal hop was fetched")

        _, p = _patch_client(handler)
        with p, pytest.raises(svc.QuizletBlocked) as ei:
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert not isinstance(ei.value, svc.QuizletURLRejected)

    def test_dns_failure_is_blocked_not_rejected(self, public_dns):
        import socket as _socket

        public_dns.side_effect = _socket.gaierror("nope")
        with pytest.raises(svc.QuizletBlocked) as ei:
            svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert not isinstance(ei.value, svc.QuizletURLRejected)

    def test_dns_lookup_is_time_bounded(self, public_dns, monkeypatch):
        import threading

        release = threading.Event()
        public_dns.side_effect = lambda *a, **k: release.wait(5) or _PUBLIC_ADDRINFO
        monkeypatch.setattr(svc, "_QUIZLET_DNS_TIMEOUT_SECONDS", 0.05)
        try:
            with pytest.raises(svc.QuizletBlocked, match="timed out") as ei:
                svc.scrape_quizlet_url("https://quizlet.com/123/abc")
            assert not isinstance(ei.value, svc.QuizletURLRejected)
        finally:
            release.set()


class TestQuizletPinnedTransport:
    """The production client: proxies off, and the socket can only be
    opened to an address the resolver approved (no rebinding window)."""

    def test_client_ignores_proxy_env_and_does_not_follow_redirects(self, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
        monkeypatch.setenv("ALL_PROXY", "http://10.0.0.1:3128")
        with svc._quizlet_client(svc._QuizletResolver()) as c:
            assert c.trust_env is False
            assert c.follow_redirects is False
            assert isinstance(c._transport, svc._PinnedQuizletTransport)
            assert c._mounts == {}  # no proxy mounts picked up from the env

    def test_pinned_transport_dials_only_the_checked_ip(self, public_dns):
        # Drive a REAL request through the production client. The resolver
        # approved 104.16.1.1; a later (rebinding) DNS answer must not matter:
        # the dial goes to the cached, approved IP with the hostname kept
        # for SNI/Host. The dial itself is stubbed to stop before any I/O.
        resolver = svc._QuizletResolver()
        resolver.resolve("quizlet.com")
        public_dns.return_value = _addrinfo("127.0.0.1")  # rebinding attempt

        class _Stop(Exception):
            pass

        with patch("httpcore.SyncBackend.connect_tcp", side_effect=_Stop) as dial:
            with svc._quizlet_client(resolver) as c, pytest.raises(_Stop):
                c.get("https://quizlet.com/123/abc")
        assert dial.call_args.args[0] == "104.16.1.1"
        assert dial.call_args.args[1] == 443
        assert public_dns.call_count == 1  # connect reused the cached answer

    def test_pinned_backend_refuses_unchecked_host(self, public_dns):
        backend = svc._PinnedQuizletBackend(svc._QuizletResolver())
        with patch("httpcore.SyncBackend.connect_tcp") as dial:
            with pytest.raises(svc.QuizletBlocked):
                backend.connect_tcp("evil.example.com", 443)
            with pytest.raises(svc.QuizletBlocked):
                backend.connect_tcp("quizlet.com", 8443)
        dial.assert_not_called()

    def test_pinned_backend_refuses_internal_answer_at_connect(self, public_dns):
        public_dns.return_value = _addrinfo("10.0.0.1")
        backend = svc._PinnedQuizletBackend(svc._QuizletResolver())
        with patch("httpcore.SyncBackend.connect_tcp") as dial:
            with pytest.raises(svc.QuizletBlocked):
                backend.connect_tcp("quizlet.com", 443)
        dial.assert_not_called()

    def test_pinned_backend_tries_next_address_on_connect_error(self, public_dns):
        import httpcore

        public_dns.return_value = _addrinfo("104.16.1.1") + _addrinfo("104.16.1.2")
        backend = svc._PinnedQuizletBackend(svc._QuizletResolver())
        stream = object()
        with patch(
            "httpcore.SyncBackend.connect_tcp",
            side_effect=[httpcore.ConnectError("down"), stream],
        ) as dial:
            assert backend.connect_tcp("quizlet.com", 443) is stream
        assert [c.args[0] for c in dial.call_args_list] == ["104.16.1.1", "104.16.1.2"]


# ── flashcard agent helpers (#146) ───────────────────────────────────────────

def _agent_returning(cards):
    """AsyncMock for flashcard_agent.run returning a Flashcards of these dicts."""
    from agents.flashcard import Flashcards, FlashCard
    fc = Flashcards(cards=[FlashCard(front=c["front"], back=c["back"]) for c in cards])
    return AsyncMock(return_value=SimpleNamespace(output=fc))


# ── extract_cards_from_image ─────────────────────────────────────────────────

class TestExtractFromImage:
    def test_runs_extraction_then_agent_split(self):
        run = _agent_returning([
            {"front": "Mitosis", "back": "cell division"},
            {"front": "Meiosis", "back": "halving"},
        ])
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            ext.extract_text_from_file.return_value = "# Notes\nMitosis: cell division\nMeiosis: halving"
            cards = svc.extract_cards_from_image(b"\x89PNG_fake_bytes", filename="notes.png")

        ext.extract_text_from_file.assert_called_once()
        assert cards == [
            {"front": "Mitosis", "back": "cell division"},
            {"front": "Meiosis", "back": "halving"},
        ]

    def test_returns_empty_on_empty_extraction(self):
        run = _agent_returning([])
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            ext.extract_text_from_file.return_value = ""
            cards = svc.extract_cards_from_image(b"", filename="x.png")
        assert cards == []
        run.assert_not_called()


# ── gemini_generate_cards ────────────────────────────────────────────────────

class TestGenerateCards:
    def test_calls_agent_with_prompt_and_returns_cards(self):
        run = _agent_returning([
            {"front": "Q1", "back": "A1"},
            {"front": "Q2", "back": "A2"},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.gemini_generate_cards("source notes", count=2, difficulty="recall")
        assert cards == [{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]
        sent = run.call_args.args[0]  # the rendered prompt handed to the agent
        assert "source notes" in sent
        assert "recall" in sent
        assert "2" in sent

    def test_bad_model_output_degrades_to_empty(self):
        # A model whose output can't satisfy the schema is "bad output" → [].
        run = AsyncMock(side_effect=UnexpectedModelBehavior("unparseable"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            assert svc.gemini_generate_cards("x", count=5, difficulty="recall") == []

    def test_transport_failure_propagates(self):
        # Transport/runtime errors must NOT masquerade as "no cards" — they
        # propagate so the route surfaces a retryable 502.
        run = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(RuntimeError):
                svc.gemini_generate_cards("x", count=5, difficulty="recall")

    def test_content_filter_propagates(self):
        # A provider content-filter block (e.g. Gemini RECITATION, which the
        # close-grounding flashcard prompt invites) is NOT schema noncompliance.
        # ContentFilterError subclasses UnexpectedModelBehavior, so without its
        # own carve-out it would degrade to [] and the route would answer a
        # misleading 200 with zero cards; it must propagate → route 502 (#340).
        run = AsyncMock(side_effect=ContentFilterError("blocked: RECITATION"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(ContentFilterError):
                svc.gemini_generate_cards("x", count=5, difficulty="recall")

    def test_non_transient_http_error_propagates(self):
        run = AsyncMock(side_effect=ModelHTTPError(status_code=400, model_name="gemini-2.5-flash"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(ModelHTTPError):
                svc.gemini_generate_cards("x", count=5, difficulty="recall")

    def test_transient_http_error_retries_then_succeeds(self):
        # 429/5xx is retried once (mirrors the old call_gemini retries=1).
        from agents.flashcard import Flashcards, FlashCard
        ok = SimpleNamespace(output=Flashcards(cards=[FlashCard(front="Q1", back="A1")]))
        run = AsyncMock(side_effect=[
            ModelHTTPError(status_code=429, model_name="gemini-2.5-flash"),
            ok,
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run), \
             patch("services.flashcard_import_service.time.sleep") as sleep:
            cards = svc.gemini_generate_cards("x", count=1, difficulty="recall")
        assert cards == [{"front": "Q1", "back": "A1"}]
        assert run.call_count == 2
        sleep.assert_called_once()

    def test_transient_http_error_reraises_after_retries_exhausted(self):
        run = AsyncMock(side_effect=ModelHTTPError(status_code=503, model_name="gemini-2.5-flash"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run), \
             patch("services.flashcard_import_service.time.sleep"):
            with pytest.raises(ModelHTTPError):
                svc.gemini_generate_cards("x", count=1, difficulty="recall")
        assert run.call_count == 2  # initial + 1 retry

    def test_filters_cards_missing_a_side(self):
        run = _agent_returning([
            {"front": "keep", "back": "yes"},
            {"front": "", "back": "no front"},
            {"front": "no back", "back": ""},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.gemini_generate_cards("x", count=3, difficulty="recall")
        assert cards == [{"front": "keep", "back": "yes"}]


# ── gemini_cleanup_cards ─────────────────────────────────────────────────────

class TestCleanupCards:
    def test_replaces_cards_in_input_order(self):
        cards = [{"front": "miotsis", "back": "cell div."}]
        run = _agent_returning([{"front": "Mitosis", "back": "Cell division"}])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            out = svc.gemini_cleanup_cards(cards)
        assert out == [{"front": "Mitosis", "back": "Cell division"}]

    def test_falls_back_to_input_on_bad_output(self):
        # Cleanup is non-destructive polish: when the model returns nothing
        # usable it keeps the user's original cards rather than erroring.
        cards = [{"front": "X", "back": "Y"}]
        run = AsyncMock(side_effect=UnexpectedModelBehavior("unparseable"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            out = svc.gemini_cleanup_cards(cards)
        assert out == cards

    def test_transport_failure_propagates(self):
        # A real outage still propagates (→ route 502), not a silent no-op.
        cards = [{"front": "X", "back": "Y"}]
        run = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(RuntimeError):
                svc.gemini_cleanup_cards(cards)

    def test_content_filter_propagates(self):
        # A content-filter block propagates (→ route 502) even on the cleanup
        # path — unlike schema-noncompliant output, which falls back to the
        # user's original cards (#340).
        cards = [{"front": "X", "back": "Y"}]
        run = AsyncMock(side_effect=ContentFilterError("blocked: SAFETY"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(ContentFilterError):
                svc.gemini_cleanup_cards(cards)


# ── gemini_cloze ─────────────────────────────────────────────────────────────

class TestCloze:
    def test_generates_cloze_cards(self):
        run = _agent_returning([
            {"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.gemini_cloze("Mitochondria is the powerhouse of the cell.")
        assert cards == [{"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"}]


# ── generate_flashcards (moved off gemini_service in #146) ────────────────────

class TestGenerateFlashcards:
    def test_returns_agent_cards_with_grounded_prompt(self):
        run = _agent_returning([
            {"front": "What is a base case?", "back": "The stopping condition of a recursion."},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.generate_flashcards(
                "Recursion", count=1, weak_concepts=["base case"],
            )
        assert cards == [
            {"front": "What is a base case?", "back": "The stopping condition of a recursion."},
        ]
        sent = run.call_args.args[0]
        assert "Recursion" in sent
        assert "base case" in sent  # weak-concept focus threaded into the prompt

    def test_prompt_grounds_on_documents_and_context(self):
        # Exercises the doc_blocks/concept_notes loop and the extra_block branch:
        # the rendered prompt must carry the document, its concepts, and the
        # free-text context, and the category must be upper-cased.
        run = _agent_returning([{"front": "Q", "back": "A"}])
        documents = [
            {
                "file_name": "week3_lecture.pdf",
                "category": "lecture",  # lowercase → proves category.upper()
                "summary": "Overview of tree traversals.",
                "concept_notes": [
                    {"name": "DFS", "description": "Depth-first traversal."},
                    {"name": "BFS"},  # no description → bare "- BFS" line
                    "not-a-dict",  # non-dict entry is skipped, not fatal
                    {"description": "orphan"},  # missing name → skipped
                ],
            }
        ]
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.generate_flashcards(
                "Data Structures",
                count=3,
                context="Focus on the midterm review session.",
                documents=documents,
                weak_concepts=["recursion depth"],
            )
        assert cards == [{"front": "Q", "back": "A"}]
        sent = run.call_args.args[0]
        # Topic + weak-concept coverage preserved.
        assert "Data Structures" in sent
        assert "recursion depth" in sent
        # Document block: upper-cased category, file name, summary.
        assert "[LECTURE] week3_lecture.pdf" in sent
        assert "Overview of tree traversals." in sent
        # Concept notes: with and without a description.
        assert "- DFS: Depth-first traversal." in sent
        assert "- BFS" in sent
        # Free-text context branch.
        assert "Focus on the midterm review session." in sent


class TestRateLimitClockSkew:
    def test_retry_capped_when_clock_steps_backward(self, monkeypatch):
        # NTP can step time.time() BACKWARD between calls: now < bucket[0]
        # makes the remaining window exceed the 60s window, and bare ceil()
        # would report an impossible retry hint. The min() cap is load-bearing
        # exactly here (#346).
        now = [1000.0]
        monkeypatch.setattr(svc.time, "time", lambda: now[0])
        for _ in range(5):
            svc.check_rate_limit("u-skew")
        now[0] = 998.5  # clock stepped back 1.5s
        assert svc.check_rate_limit("u-skew") == 60
