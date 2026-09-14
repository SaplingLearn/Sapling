"""decrypt_json_column: the read-boundary guard for JSONB columns that may
hold legacy plaintext (dict/list from PostgREST) or ciphertext (str). #521."""
from services.encryption import decrypt_json_column, encrypt_json


def test_none_passes_through():
    assert decrypt_json_column(None) is None


def test_legacy_plaintext_dict_passes_through():
    v = {"asked": 3, "misconceptions": ["off-by-one"]}
    assert decrypt_json_column(v) is v


def test_legacy_plaintext_list_passes_through():
    v = [{"q": "Q1"}]
    assert decrypt_json_column(v) is v


def test_ciphertext_string_decrypts():
    payload = {"asked": 3, "misconceptions": ["off-by-one"]}
    assert decrypt_json_column(encrypt_json(payload)) == payload


def test_plaintext_json_string_falls_back():
    # A TEXT-era row that stored raw JSON — decrypt_json's fallback parses it.
    assert decrypt_json_column('{"a": 1}') == {"a": 1}
