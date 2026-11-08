"""
Server-side parsers and Gemini wrappers for flashcard import.

Pure functions only — no Supabase or HTTP coupling beyond the Gemini
client. Each function returns plain dicts the routes can serialize.
"""
from __future__ import annotations

import base64
import io
import ipaddress
import json
import logging
import math
import os
import re
import socket
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import TypedDict

import httpcore
from services import request_limits

import httpx
from bs4 import BeautifulSoup
from Levenshtein import distance as _levenshtein
from pydantic_ai.exceptions import (
    ContentFilterError,
    ModelHTTPError,
    UnexpectedModelBehavior,
)

from db.connection import table
from agents._run import run_agent_sync
from agents.flashcard import flashcard_agent
from agents.usage import record_agent_usage
from services import extraction_service
from services.encryption import decrypt_if_present

logger = logging.getLogger(__name__)


class Card(TypedDict):
    front: str
    back: str


class QuizletBlocked(Exception):
    """Raised when scrape_quizlet_url cannot extract cards."""


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()


def dedup_against_existing(
    user_id: str,
    offering_id: str | None,
    cards: list[Card],
    topic: str | None = None,
) -> tuple[list[Card], list[Card]]:
    """Return (keep, skipped) where skipped have a near-duplicate front
    (Levenshtein <= 3 on normalized front) among the user's existing cards
    in the same offering (or topic when offering_id is None).

    Flashcards key on the course offering after migration 0025 (the link column
    was renamed course_id -> offering_id)."""
    filters = {"user_id": f"eq.{user_id}"}
    if offering_id:
        filters["offering_id"] = f"eq.{offering_id}"
    elif topic:
        filters["topic"] = f"eq.{topic}"

    existing = table("flashcards").select("front", filters=filters) or []
    existing_norm = [
        _normalize(decrypt_if_present(r.get("front", "")) or "") for r in existing
    ]

    keep: list[Card] = []
    skipped: list[Card] = []
    for card in cards:
        norm = _normalize(card.get("front", ""))
        is_dup = any(_levenshtein(norm, e) <= 3 for e in existing_norm if e)
        (skipped if is_dup else keep).append(card)
    return keep, skipped


_RATE_WINDOW_SEC = 60
_RATE_LIMIT = 5
#: The shared limiter's state (#117): one store, so the `stateless_rate_limit`
#: flag moves this budget to Postgres along with every other limiter's.
_rate_state = request_limits._rate_state


def check_rate_limit(user_id: str) -> int | None:
    """Returns None if call allowed, else seconds until allowed again (the
    shared sliding window in services/request_limits, key
    ``flashcard_import:<user_id>``)."""
    return request_limits.check_rate_limit(
        f"flashcard_import:{user_id}", limit=_RATE_LIMIT, window_sec=_RATE_WINDOW_SEC,
    )


def parse_xlsx(file_bytes: bytes) -> list[Card]:
    """Read a .xlsx workbook, treating col A as front and col B as back."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    cards: list[Card] = []
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        front = (str(row[0]) if len(row) > 0 and row[0] is not None else "").strip()
        back = (str(row[1]) if len(row) > 1 and row[1] is not None else "").strip()
        if front and back:
            cards.append({"front": front, "back": back})
    return cards


def _strip_html(text: str) -> str:
    soup = BeautifulSoup(text or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def parse_anki_apkg(file_bytes: bytes) -> list[Card]:
    """Extract notes from an Anki .apkg (zip with a SQLite collection.anki2)."""
    import tempfile

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            names = z.namelist()
            if "collection.anki2" not in names:
                raise ValueError("Anki package is missing collection.anki2")
            db_bytes = z.read("collection.anki2")
    except zipfile.BadZipFile as e:
        raise ValueError(f"Anki file is not a valid .apkg: {e}")

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp:
        tmp.write(db_bytes)
        path = tmp.name

    try:
        conn = sqlite3.connect(path)
        rows = conn.execute("SELECT flds FROM notes").fetchall()
        conn.close()
    finally:
        os.unlink(path)

    cards: list[Card] = []
    for (flds,) in rows:
        if not flds:
            continue
        parts = flds.split("\x1f")
        if len(parts) < 2:
            continue
        front = _strip_html(parts[0])
        back = _strip_html(parts[1])
        if front and back:
            cards.append({"front": front, "back": back})
    return cards


_QUIZLET_PAYLOAD_RE = re.compile(
    r'window\.Quizlet\["setPageData"\]\s*=\s*(\{.*?\});',
    re.DOTALL,
)


class QuizletURLRejected(QuizletBlocked):
    """Raised when the URL the STUDENT submitted fails the SSRF policy: not
    http(s), not an allowlisted Quizlet host, a non-default port, embedded
    credentials, or a host that resolves to a non-public IP. The route maps
    it to a 400 (the student's input is wrong), unlike the 422 a plain
    QuizletBlocked gets. A redirect HOP failing the policy is upstream
    behaviour, not a bad input, so it raises plain QuizletBlocked (422) and
    the UI offers its Paste-tab fallback."""


# The ONLY hosts the server will fetch for a Quizlet import. Quizlet serves
# sets from the apex and www; country/mobile subdomains are not accepted —
# a student can paste the canonical quizlet.com link instead.
_QUIZLET_HOSTS = frozenset({"quizlet.com", "www.quizlet.com"})
_QUIZLET_MAX_REDIRECTS = 5
_QUIZLET_TIMEOUT_SECONDS = 15.0
# getaddrinfo has no timeout of its own; a hung resolver would otherwise pin
# the request thread for the OS resolver's full retry schedule.
_QUIZLET_DNS_TIMEOUT_SECONDS = 5.0
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_URL_REJECTED_MSG = "Only https://quizlet.com set links can be imported."
_REDIRECTED_AWAY_MSG = (
    "Quizlet redirected away from quizlet.com, so the set could not be "
    "fetched. Try exporting the set and pasting the text instead."
)
_TOO_MANY_REDIRECTS_MSG = (
    "Quizlet redirected too many times, so the set could not be fetched. "
    "Try exporting the set and pasting the text instead."
)
# NAT64 well-known prefix (RFC 6052): the low 32 bits ARE the IPv4 target.
_NAT64_WKP = ipaddress.IPv6Network("64:ff9b::/96")


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 transition wrapper actually reaches, if any:
    IPv4-mapped (``::ffff:a.b.c.d``), NAT64 well-known prefix
    (``64:ff9b::a.b.c.d`` — what a DNS64 resolver answers on an IPv6-only
    host) and 6to4 (``2002:AABB:CCDD::``). Teredo (2001::/32) is left to the
    generic checks, which already refuse it as non-global."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip in _NAT64_WKP:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour is not None:
        return ip.sixtofour
    return None


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for a globally routable unicast address.

    ``is_global`` alone is not enough: it is True for multicast (224/4), so
    every disqualifying property is checked explicitly. An IPv6 wrapper that
    embeds an IPv4 target (mapped / NAT64 / 6to4) is judged as the IPv4
    address it reaches — the wrapper prefix itself is ``is_reserved``, which
    would otherwise refuse every IPv6-only/DNS64 deployment."""
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = _embedded_ipv4(ip)
        if embedded is not None:
            ip = embedded
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _getaddrinfo_bounded(host: str) -> list:
    """``socket.getaddrinfo`` with a wall-clock bound. The lookup runs on a
    throwaway worker thread; on timeout the caller stops waiting (the worker
    finishes or dies on its own — it holds no locks and nothing reads it)."""
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quizlet-dns")
    try:
        future = pool.submit(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
        try:
            return future.result(timeout=_QUIZLET_DNS_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            raise QuizletBlocked("Could not reach Quizlet: DNS lookup timed out")
    finally:
        pool.shutdown(wait=False)


class _QuizletResolver:
    """Per-scrape DNS: each host is resolved ONCE (bounded), every address
    must be public, and the answer is cached for the rest of the scrape.

    The same object backs both the pre-fetch URL check and the connection
    (``_PinnedQuizletBackend``), so the socket can only ever be opened to an
    address this check approved — a DNS answer that changes between check
    and connect (rebinding) never reaches a socket."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, ...]] = {}

    def resolve(self, host: str) -> tuple[str, ...]:
        cached = self._cache.get(host)
        if cached is not None:
            return cached
        try:
            infos = _getaddrinfo_bounded(host)
        except (socket.gaierror, UnicodeError) as e:
            raise QuizletBlocked(f"Could not reach Quizlet: {e}")
        addrs: list[str] = []
        for info in infos:
            addr = str(info[4][0]).split("%", 1)[0]  # drop an IPv6 zone id
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                raise QuizletURLRejected(_URL_REJECTED_MSG)
            if not _is_public_ip(ip):
                logger.warning("quizlet import refused: %s resolved to %s", host, ip)
                raise QuizletURLRejected(_URL_REJECTED_MSG)
            if addr not in addrs:
                addrs.append(addr)
        if not addrs:
            raise QuizletBlocked("Could not reach Quizlet: no addresses")
        self._cache[host] = tuple(addrs)
        return self._cache[host]


class _PinnedQuizletBackend(httpcore.SyncBackend):
    """httpcore network backend that connects ONLY to addresses the scrape's
    resolver approved, and only for an allowlisted host.

    httpcore passes the URL's hostname here and later uses that same
    hostname for TLS SNI + certificate verification, and httpx sends it as
    the Host header — so connecting to the pinned IP changes nothing about
    the request except WHICH socket it rides."""

    def __init__(self, resolver: _QuizletResolver) -> None:
        self._resolver = resolver

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host.lower().rstrip(".") not in _QUIZLET_HOSTS or port != 443:
            raise QuizletBlocked(_REDIRECTED_AWAY_MSG)
        try:
            addrs = self._resolver.resolve(host)
        except QuizletURLRejected:
            # Every URL is validated (and so resolved + cached) before it is
            # fetched; reaching here means the pre-check was bypassed.
            raise QuizletBlocked(_REDIRECTED_AWAY_MSG) from None
        last_exc: Exception | None = None
        for addr in addrs:
            try:
                return super().connect_tcp(
                    addr,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectError as e:
                last_exc = e
        assert last_exc is not None  # addrs is never empty
        raise last_exc


class _PinnedQuizletTransport(httpx.HTTPTransport):
    """An HTTPTransport whose connection pool dials through
    ``_PinnedQuizletBackend``. httpx (0.28, pinned in requirements) does not
    expose ``network_backend``, so the pool is rebuilt here with httpx's
    default TLS context (certifi, or SSL_CERT_FILE — the CA bundle the old
    ``httpx.get`` used; only PROXY env is ignored, via the client's
    ``trust_env=False``). ``test_pinned_transport_dials_only_the_checked_ip`` drives a
    real request through it, so an httpx upgrade that changes this seam
    fails loudly instead of silently un-pinning."""

    def __init__(self, resolver: _QuizletResolver) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(),
            network_backend=_PinnedQuizletBackend(resolver),
        )


def _quizlet_client(resolver: _QuizletResolver) -> httpx.Client:
    """The ONE client a scrape reuses across hops. ``trust_env=False`` so
    HTTP(S)_PROXY / ALL_PROXY env vars can never route the fetch through a
    proxy (which would dial the proxy, not the checked address)."""
    return httpx.Client(
        transport=_PinnedQuizletTransport(resolver),
        trust_env=False,
        timeout=_QUIZLET_TIMEOUT_SECONDS,
        headers={"User-Agent": "Mozilla/5.0 (Sapling flashcard import)"},
        follow_redirects=False,
    )


def _validate_quizlet_url(
    url: str | httpx.URL, resolver: _QuizletResolver, *, submitted: bool = False
) -> httpx.URL:
    """Return the parsed URL if it passes the SSRF policy, else raise
    QuizletURLRejected. Applied to the submitted URL AND every redirect hop.

    Only the SUBMITTED URL may be upgraded from ``http://`` to ``https://``
    (students paste http links; Quizlet would 301 them to https anyway). A
    redirect hop that downgrades to http is refused."""
    try:
        parsed = url if isinstance(url, httpx.URL) else httpx.URL(str(url).strip())
    except (httpx.InvalidURL, TypeError, ValueError):
        raise QuizletURLRejected(_URL_REJECTED_MSG)
    if submitted and parsed.scheme == "http" and parsed.port in (None, 80):
        parsed = parsed.copy_with(scheme="https", port=None)
    host = (parsed.host or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or host not in _QUIZLET_HOSTS
        or parsed.port not in (None, 443)
        or parsed.userinfo
    ):
        raise QuizletURLRejected(_URL_REJECTED_MSG)
    resolver.resolve(host)
    return parsed


def scrape_quizlet_url(url: str) -> list[Card]:
    """Best-effort fetch of a public Quizlet set. Raises QuizletBlocked on
    bot wall, login redirect, unparseable payload, or a redirect that leaves
    the policy (off-host, too many hops), and QuizletURLRejected (a
    QuizletBlocked subclass) when the SUBMITTED URL is not a Quizlet URL
    resolving to a public address.

    Redirects are followed by hand (never ``follow_redirects=True``) so each
    hop is re-validated before it is fetched — the input is user-supplied, so
    an unchecked hop is a server-side request forgery. One client (one
    resolver cache, one pinned pool) serves every hop."""
    resolver = _QuizletResolver()
    current = _validate_quizlet_url(url, resolver, submitted=True)
    with _quizlet_client(resolver) as client:
        for _ in range(_QUIZLET_MAX_REDIRECTS + 1):
            try:
                resp = client.get(current)
            except httpx.HTTPError as e:
                raise QuizletBlocked(f"Could not reach Quizlet: {e}")
            if resp.status_code not in _REDIRECT_STATUSES:
                break
            location = resp.headers.get("location")
            if not location:
                raise QuizletBlocked(f"Quizlet returned status {resp.status_code}")
            try:
                current = _validate_quizlet_url(current.join(location), resolver)
            except QuizletURLRejected:
                logger.warning("quizlet import: redirect refused (%s)", location[:200])
                raise QuizletBlocked(_REDIRECTED_AWAY_MSG) from None
            except (httpx.InvalidURL, TypeError, ValueError):
                raise QuizletBlocked(_REDIRECTED_AWAY_MSG) from None
        else:
            raise QuizletBlocked(_TOO_MANY_REDIRECTS_MSG)

    if resp.status_code != 200:
        raise QuizletBlocked(f"Quizlet returned status {resp.status_code}")

    match = _QUIZLET_PAYLOAD_RE.search(resp.text)
    if not match:
        raise QuizletBlocked(
            "Couldn't extract cards from this URL. Quizlet may be blocking "
            "scrapers — try exporting the set and pasting the text instead."
        )

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise QuizletBlocked(f"Quizlet payload was not valid JSON: {e}")

    terms = (data.get("set") or {}).get("terms") or []
    cards: list[Card] = []
    for t in terms:
        front = (t.get("word") or "").strip()
        back = (t.get("definition") or "").strip()
        if front and back:
            cards.append({"front": front, "back": back})
    if not cards:
        raise QuizletBlocked("No terms found in the Quizlet payload.")
    return cards


def _guess_content_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/png"


# Transient provider statuses the legacy call_gemini path retried on. 429 =
# rate limit, 5xx = upstream/transport hiccups, 529 = Anthropic's
# `overloaded_error` (the Anthropic SDK already retries these twice itself;
# this is the route-level retry on top, same as it was for Gemini).
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
# Mirror the old call_gemini(retries=1): one retry with a ~2s backoff.
_AGENT_RETRIES = 1


def _run_flashcard_agent(prompt: str) -> list[Card]:
    """Run the flashcard agent on a rendered prompt and return front/back dicts.

    Filters out cards missing either side. Error contract (unified across the
    generate + import seams):

    * A model whose output can't satisfy the ``Flashcards`` schema is treated as
      "bad LLM output" and degrades to ``[]`` — logged, never silent. This
      matches the import seams' long-standing bad-JSON ``[]`` resilience; note
      it is a deliberate contract change for ``/generate``, whose legacy path
      *raised* (surfacing a 502) on malformed output.
    * Provider content-filter blocks (``ContentFilterError``, e.g. a Gemini
      RECITATION/SAFETY stop — which this prompt's close grounding to course
      material invites) are carved out of that degrade: the exception
      subclasses ``UnexpectedModelBehavior`` but propagates so the route
      surfaces a 502 instead of a misleading success with zero cards (#340).
    * Transient provider errors (HTTP 429/5xx) are retried once with a ~2s
      backoff, then re-raised.
    * Every other failure — transport, a missing provider API key,
      ``run_agent_sync`` misuse from a running event loop, etc. — propagates so
      the route surfaces a retryable 502 instead of a misleading 200 with zero
      cards.
    """
    result = None
    for attempt in range(_AGENT_RETRIES + 1):
        try:
            result = record_agent_usage(
                run_agent_sync(flashcard_agent.run(prompt)),
                feature="flashcard", task="flashcard",
            )
            break
        except ContentFilterError:
            # Subclasses UnexpectedModelBehavior, so this carve-out must come
            # first: a content-filter block is not schema noncompliance and
            # must reach the route's 502 handler, not degrade to [] (#340).
            logger.exception("flashcard agent blocked by provider content filter")
            raise
        except UnexpectedModelBehavior:
            logger.exception("flashcard agent produced unusable output; degrading to []")
            return []
        except ModelHTTPError as e:
            if attempt < _AGENT_RETRIES and e.status_code in _TRANSIENT_STATUSES:
                time.sleep(2)
                continue
            logger.exception("flashcard agent HTTP error (status=%s)", e.status_code)
            raise
        except Exception:
            logger.exception("flashcard agent call failed")
            raise

    out: list[Card] = []
    for c in result.output.cards:
        front = (c.front or "").strip()
        back = (c.back or "").strip()
        if front and back:
            out.append({"front": front, "back": back})
    return out


def extract_cards_from_image(file_bytes: bytes, filename: str = "image.png") -> list[Card]:
    """OCR the image via the existing extraction pipeline, then ask the agent
    to split the markdown into Q/A pairs."""
    content_type = _guess_content_type(filename)
    markdown = extraction_service.extract_text_from_file(file_bytes, filename, content_type) or ""
    if not markdown.strip():
        return []
    prompt = _load_prompt("flashcard_ocr_split.txt").replace("{markdown}", markdown)
    return _run_flashcard_agent(prompt)


def gemini_generate_cards(source_text: str, count: int, difficulty: str) -> list[Card]:
    prompt = (
        _load_prompt("flashcard_generation.txt")
        .replace("{count}", str(count))
        .replace("{difficulty}", difficulty)
        .replace("{source}", source_text)
    )
    return _run_flashcard_agent(prompt)


def gemini_cleanup_cards(cards: list[Card]) -> list[Card]:
    prompt = _load_prompt("flashcard_cleanup.txt").replace(
        "{cards_json}", json.dumps(cards, ensure_ascii=False)
    )
    out = _run_flashcard_agent(prompt)
    return out if out else cards


def gemini_cloze(paragraph: str) -> list[Card]:
    prompt = _load_prompt("flashcard_cloze.txt").replace("{paragraph}", paragraph)
    return _run_flashcard_agent(prompt)


def generate_flashcards(
    topic: str,
    count: int = 5,
    context: str = "",
    documents: list[dict] | None = None,
    weak_concepts: list[str] | None = None,
) -> list[dict]:
    """Generate flashcards grounded in the student's course material, via the
    flashcard agent. Moved off gemini_service in #146.

    Args:
        topic:          The course or concept name.
        count:          Number of cards to generate.
        context:        Optional free-text context (e.g. session summary).
        documents:      Document dicts (file_name, category, summary, concept_notes).
        weak_concepts:  Concept names the student has low mastery on, weighted higher.
    """
    # ── Build document context block ──────────────────────────────────────────
    doc_blocks = []
    if documents:
        for doc in documents:
            parts = [f"[{doc.get('category', 'document').upper()}] {doc.get('file_name', '')}"]
            if doc.get("summary"):
                parts.append(f"Summary: {doc['summary']}")
            notes = doc.get("concept_notes")
            if notes and isinstance(notes, list):
                concept_lines = []
                for n in notes:
                    if not isinstance(n, dict):
                        continue
                    name = n.get("name")
                    desc = n.get("description")
                    if not name:
                        continue
                    concept_lines.append(f"- {name}: {desc}" if desc else f"- {name}")
                if concept_lines:
                    parts.append("Key concepts:\n" + "\n".join(concept_lines))
            doc_blocks.append("\n".join(parts))

    doc_context = ""
    if doc_blocks:
        doc_context = (
            "\n\nCOURSE MATERIAL (use this as the primary source for flashcard content):\n"
            + "\n\n---\n\n".join(doc_blocks)
        )

    # ── Weak concept focus block ──────────────────────────────────────────────
    weak_block = ""
    if weak_concepts:
        weak_block = (
            "\n\nThe student has LOW MASTERY on these concepts — prioritize them: "
            + ", ".join(weak_concepts)
        )

    # ── Free-text context (e.g. session summary) ──────────────────────────────
    extra_block = f"\n\nAdditional context:\n{context}" if context else ""

    prompt = f"""You are an expert tutor creating study flashcards for a student.

Course/Topic: "{topic}"{doc_context}{weak_block}{extra_block}

Generate exactly {count} flashcards.

Rules:
- Base card content on the course material provided above, not generic knowledge.
- Each card must have a clear FRONT (question or term) and a BACK (answer or definition).
- Vary difficulty: include recall, conceptual, and application questions.
- Prioritize concepts the student has low mastery on if listed above.
- Be specific — avoid vague or trivially obvious cards.
- Do NOT repeat questions already listed in the existing Q&A pairs above."""

    return _run_flashcard_agent(prompt)
