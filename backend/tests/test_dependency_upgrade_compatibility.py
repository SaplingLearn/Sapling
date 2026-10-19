"""Offline public-API compatibility for the reviewed security dependency bump.

No provider, database, OCR model, credential or production ciphertext is used.
"""

import base64
import io
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google_auth_oauthlib.flow import Flow
from PIL import Image
from pypdf import PdfReader
import pytest

from services import encryption


# Generated with cryptography45.0.7, a public all-zero synthetic key and fixed
# nonce. This is the existing nonce || ciphertext || 16-byte-tag storage format,
# not an application secret or any student's stored value.
_OLD_CIPHERTEXT = (
    "AAECAwQFBgcICQoL4KJAJm+P5pqjFHKWhG2qZDEYwfmf70xfvL6JyCQ/dE2PmMnLOEULzkVJ+T6Uog75BwDMqJybsCb7"
)
_OLD_PLAINTEXT = 'historical synthetic résumé\n{"count":2}'


def test_historical_aes_gcm_storage_bytes_remain_readable_and_writable(monkeypatch):
    monkeypatch.setattr(encryption, "_AESGCM", AESGCM(bytes(32)))
    monkeypatch.setattr(encryption, "os", SimpleNamespace(urandom=lambda size: bytes(range(size))))
    assert encryption.decrypt(_OLD_CIPHERTEXT) == _OLD_PLAINTEXT
    assert encryption.encrypt(_OLD_PLAINTEXT) == _OLD_CIPHERTEXT


def test_historical_aes_gcm_tag_and_wrong_key_still_fail_closed(monkeypatch):
    altered = bytearray(base64.b64decode(_OLD_CIPHERTEXT))
    altered[-1] ^= 1
    monkeypatch.setattr(encryption, "_AESGCM", AESGCM(bytes(32)))
    with pytest.raises(InvalidTag):
        encryption.decrypt(base64.b64encode(altered).decode())
    monkeypatch.setattr(encryption, "_AESGCM", AESGCM(bytes([1]) * 32))
    with pytest.raises(InvalidTag):
        encryption.decrypt(_OLD_CIPHERTEXT)


def test_reviewed_pdf_reader_keeps_real_fixture_page_and_text_contract():
    fixture = Path(__file__).with_name("fixtures") / "sample_syllabus.pdf"
    reader = PdfReader(io.BytesIO(fixture.read_bytes()))
    assert reader.pages
    assert any((page.extract_text() or "").strip() for page in reader.pages)


def test_pillow_preserves_rgba_upload_bytes_without_optional_ocr():
    image = Image.new("RGBA", (3, 2), (12, 34, 56, 78))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    with Image.open(io.BytesIO(stream.getvalue())) as loaded:
        loaded.load()
        assert loaded.size == (3, 2)
        assert loaded.mode == "RGBA"
        assert loaded.tobytes() == bytes((12, 34, 56, 78)) * 6


def test_google_oauth_client_still_builds_state_bound_pkce_request_offline():
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": "synthetic-client",
                "client_secret": "synthetic-not-a-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["https://example.invalid/callback"],
            }
        },
        scopes=["openid", "email"],
        autogenerate_code_verifier=True,
    )
    flow.redirect_uri = "https://example.invalid/callback"
    uri, state = flow.authorization_url(state="synthetic-state", access_type="offline")
    query = parse_qs(urlsplit(uri).query)
    assert state == "synthetic-state" and query["state"] == [state]
    assert query["redirect_uri"] == [flow.redirect_uri]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] and flow.code_verifier
