from unittest.mock import patch

import httpx

from services import note_originals


def test_original_is_encrypted_and_download_restores_exact_bytes():
    content = b"%PDF-1.7\noriginal bytes\x00"
    with patch.object(note_originals.httpx, "post") as post:
        post.return_value = httpx.Response(200, request=httpx.Request("POST", "http://storage.test"))
        size = note_originals.store_original("u1", "n1", content)
    ciphertext = post.call_args.kwargs["content"]
    assert ciphertext.startswith(b"enc2:")
    assert size == len(ciphertext)
    assert content not in ciphertext

    note = {"user_id": "u1", "id": "n1", "original_filename": "My syllabus.pdf",
            "original_type": "application/pdf"}
    with patch.object(note_originals.httpx, "get") as get:
        get.return_value = httpx.Response(
            200, content=ciphertext, request=httpx.Request("GET", "http://storage.test"),
        )
        response = note_originals.download_original(note)
    assert response.body == content
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''My%20syllabus.pdf"
    assert response.headers["cache-control"] == "private, no-store"
