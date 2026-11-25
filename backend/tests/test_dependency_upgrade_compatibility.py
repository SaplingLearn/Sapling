"""Offline public-API compatibility for the reviewed security dependency bump.

No provider, database, OCR model, credential or production ciphertext is used.
"""

import base64
from types import SimpleNamespace

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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
