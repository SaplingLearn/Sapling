"""#484 / ADR 0025: `course_chunks.chunk_text` is ciphertext at rest.

The same student text has been encrypted into `documents.extracted_text` since
0030 and chunked into `course_chunks.chunk_text` in the clear ever since — one
column treated as PII and the other not, for no reason anyone had written down.
ADR 0025 closes that, with two halves that are easy to get backwards:

* **Ids stay on the plaintext.** AES-GCM draws a fresh nonce per call, so the
  same passage encrypts differently every time; a ciphertext-derived id would
  make every re-upload a new row and destroy content-addressing.
* **Encryption happens after embedding.** The embed pass reads `chunk_text` off
  the record, so encrypting a moment too early embeds base64 — every vector
  becomes noise and retrieval silently ranks nothing. That failure has no
  symptom at the write boundary at all, which is why it gets its own test.

The ADR does NOT claim chunk confidentiality: `embedding` cannot be encrypted
(pgvector must compute distance over it) and embeddings are partially
invertible. This is boundary consistency, and the residual exposure is recorded
in the ADR itself.
"""
from unittest.mock import MagicMock, patch

import pytest

from services.encryption import decrypt, encrypt


# ── Write ───────────────────────────────────────────────────────────────────


@patch("services.rag_service._embed_documents_batch")
def test_chunk_text_is_stored_as_ciphertext(mock_embed):
    mock_embed.return_value = [[0.1] * 768]
    text = "Gradient descent follows the negative gradient of the loss."
    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.record_contributors"),
        patch("services.chunk_visibility.shares_class_context", return_value=True),
    ):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", [text],
            visibility="shared", category="lecture_notes",
        )
        stored = mock_table.return_value.upsert.call_args[0][0][0]["chunk_text"]

    assert stored != text
    assert decrypt(stored) == text


@patch("services.rag_service._embed_documents_batch")
def test_the_embedding_is_computed_from_PLAINTEXT(mock_embed):
    """The ordering trap. Encrypting when the record is built would hand
    `_embed_documents_batch` base64, and nothing at the write boundary would
    notice: the upsert succeeds, the count is right, the row looks indexed —
    and every vector is noise, so retrieval ranks nothing for reasons no log
    line would ever mention."""
    mock_embed.return_value = [[0.1] * 768]
    text = "Memoization caches subproblem results."
    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.record_contributors"),
        patch("services.chunk_visibility.shares_class_context", return_value=True),
    ):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", [text],
            visibility="shared", category="lecture_notes",
        )

    assert mock_embed.call_args[0][0] == [text]


@patch("services.rag_service._embed_documents_batch")
def test_the_id_is_still_the_plaintext_content_hash(mock_embed):
    """Content-addressing is what makes two students' identical slides one row.
    A ciphertext-derived id would give every upload a fresh id — unbounded
    duplication of the same passage, and #629's contributor ledger keyed on ids
    that never recur."""
    mock_embed.return_value = [[0.1] * 768]
    text = "Dynamic programming trades space for time."
    with (
        patch("services.rag_service.table") as mock_table,
        patch("services.rag_service.record_contributors"),
        patch("services.chunk_visibility.shares_class_context", return_value=True),
    ):
        mock_table.return_value.upsert.return_value = []
        from services.rag_service import chunk_id, index_document_chunks
        index_document_chunks(
            "CAS CS 330", "doc-1", "u1", [text],
            visibility="shared", category="lecture_notes",
        )
        row = mock_table.return_value.upsert.call_args[0][0][0]

    assert row["id"] == chunk_id("CAS CS 330", text)
    assert row["chunk_hash"] == row["id"]


@patch("services.rag_service._embed_documents_batch")
def test_two_uploads_of_one_passage_still_converge_on_one_id(mock_embed):
    """Belt and braces on the same property, from the direction that actually
    breaks: the two ciphertexts differ (fresh nonce), the two ids must not."""
    mock_embed.return_value = [[0.1] * 768]
    text = "The learning rate governs convergence."
    ids, ciphertexts = [], []
    for uploader in ("u1", "u2"):
        with (
            patch("services.rag_service.table") as mock_table,
            patch("services.rag_service.record_contributors"),
            patch("services.chunk_visibility.shares_class_context", return_value=True),
        ):
            mock_table.return_value.upsert.return_value = []
            from services.rag_service import index_document_chunks
            index_document_chunks(
                "CAS CS 330", f"doc-{uploader}", uploader, [text],
                visibility="shared", category="lecture_notes",
            )
            row = mock_table.return_value.upsert.call_args[0][0][0]
            ids.append(row["id"])
            ciphertexts.append(row["chunk_text"])

    assert ids[0] == ids[1]
    assert ciphertexts[0] != ciphertexts[1]


# ── Read ────────────────────────────────────────────────────────────────────


@patch("services.rag_service._client")
def test_retrieval_hands_back_plaintext(mock_client, monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    resp = MagicMock()
    resp.embeddings = [MagicMock(values=[0.1] * 768)]
    mock_client.models.embed_content.return_value = resp
    text = "Backprop computes the gradient via the chain rule."
    rows = [{"id": "c1", "course_id": "CAS CS 330",
             "chunk_text": encrypt(text), "category": "lecture_notes",
             "similarity": 0.81}]

    with patch("services.rag_service.rpc", return_value=rows):
        from services.rag_service import retrieve_chunks
        got = retrieve_chunks("chain rule", course_id="CAS CS 330", user_id="u1")

    assert got[0]["chunk_text"] == text


@patch("services.rag_service._client")
def test_a_plaintext_row_still_reads_back(mock_client, monkeypatch):
    """There is a window between deploying this code and finishing the backfill
    in which the table holds both shapes. `decrypt_if_present` returns the raw
    value when it cannot decrypt, so those rows keep working — with a WARNING,
    which is the correct signal while the window is open and a real alarm once
    it is closed."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    resp = MagicMock()
    resp.embeddings = [MagicMock(values=[0.1] * 768)]
    mock_client.models.embed_content.return_value = resp
    rows = [{"id": "c1", "chunk_text": "still plaintext", "similarity": 0.9}]

    with patch("services.rag_service.rpc", return_value=rows):
        from services.rag_service import retrieve_chunks
        got = retrieve_chunks("q", course_id="CAS CS 330", user_id="u1")

    assert got[0]["chunk_text"] == "still plaintext"


def test_the_catalog_block_decrypts_before_choosing_a_chunk():
    """`_get_catalog_chunk` prefers the entry with a `Prerequisites:` line and
    otherwise the longest. Both tests read the text, so against ciphertext the
    first would never match and the second would be comparing base64 lengths —
    i.e. it would still return *something*, which is how this would have shipped
    unnoticed."""
    from routes.learn import _get_catalog_chunk

    short_with_prereq = "CS 330. Prerequisites: CS 112."
    long_without = "CS 330. " + ("Algorithms and data structures. " * 20)
    rows = [{"chunk_text": encrypt(long_without)},
            {"chunk_text": encrypt(short_with_prereq)}]

    def _table(name):
        m = MagicMock()
        m.select.return_value = rows
        return m

    with patch("routes.learn.table", side_effect=_table):
        assert _get_catalog_chunk("CAS CS 330") == short_with_prereq


def test_the_quiz_drops_a_catalog_duplicate_after_encryption():
    """The quiz de-dups retrieved chunks against the catalog block by comparing
    TEXT. Encryption would break that silently — two ciphertexts of the same
    passage never compare equal — and the only symptom is the course description
    sent to the model twice."""
    from routes.quiz import BuCodeLookup, _course_material
    from services.rag_service import Retrieval

    catalog = "CS 330. Prerequisites: CS 112."
    with (
        patch("routes.quiz._resolve_bu_code",
              return_value=BuCodeLookup(code="CAS CS 330", failed=False)),
        patch("routes.quiz._get_catalog_chunk", return_value=catalog),
        patch("routes.quiz.retrieve_chunks_detailed", return_value=Retrieval(
            chunks=[{"id": "c1", "chunk_text": catalog, "similarity": 0.9}],
        )),
        patch("routes.quiz.table") as mock_table,
    ):
        mock_table.return_value.select_with_count.return_value = ([], 0)
        material = _course_material("course-uuid", "dp", user_id="u1")

    assert material.k_chunks == 0
    assert material.block.count("Prerequisites: CS 112.") == 1


# ── The one-time dedupe script ──────────────────────────────────────────────


def test_the_dedupe_script_groups_on_plaintext():
    """`plan_migration` re-derives ids from the STORED text. Against ciphertext
    every row would hash differently — including two rows holding the SAME
    passage — so the script would 'find' no duplicates and rewrite every row to
    a fresh id, destroying content-addressing rather than repairing it."""
    from scripts.dedupe_course_chunks import plan_migration
    from services.rag_service import chunk_id

    text = "Identical passage, uploaded twice."
    rows = [
        {"id": "legacy-a", "course_id": "CAS CS 330", "chunk_text": encrypt(text),
         "embedding": [0.1], "category": "lecture_notes", "visibility": "shared"},
        {"id": "legacy-b", "course_id": "CAS CS 330", "chunk_text": encrypt(text),
         "embedding": None, "category": "lecture_notes", "visibility": "shared"},
    ]
    upserts, deletes = plan_migration(rows)

    # ONE group, so one upsert under the plaintext-derived id — and both legacy
    # ids go, the winner included, because it is re-inserted under the new id.
    assert [u["id"] for u in upserts] == [chunk_id("CAS CS 330", text)]
    assert sorted(deletes) == ["legacy-a", "legacy-b"]
    # The row carries its stored ciphertext forward; only the hash input was
    # plaintext.
    assert upserts[0]["chunk_text"] == rows[0]["chunk_text"]


# ── The invariant the lane can fail on ──────────────────────────────────────


def test_the_ciphertext_oracle_covers_the_column():
    """Without a manifest entry, "chunk_text is always ciphertext" is a claim in
    an ADR rather than something a lane can fail on."""
    from e2e_oracles.gather import _CIPHERTEXT_MANIFEST

    assert ("course_chunks", "id", "chunk_text") in _CIPHERTEXT_MANIFEST


if __name__ == "__main__":
    pytest.main([__file__])


# ── the backfill's upsert must satisfy NOT NULL on the proposed INSERT row ───


def test_backfill_payload_carries_every_not_null_column():
    """Postgres checks NOT NULL on an upsert's proposed INSERT row before
    ON CONFLICT turns it into an update. The first --apply against prod 400'd
    because the payload lacked `chunk_hash` and `semester` (NOT NULL, no
    default). Each written row must carry them — with the row's OWN values,
    since merge-duplicates overwrites every column it is given."""
    import scripts.backfill_encrypt_chunk_text as bf

    row = {"id": "c1", "course_id": "CAS CS 330", "chunk_text": "plain passage",
           "chunk_hash": "h-1", "semester": "Fall 2026"}
    chunks = MagicMock()
    with patch.object(bf, "_assert_key_matches_database"), \
         patch.object(bf, "page_all", return_value=iter([row])) as paged, \
         patch.object(bf, "table", return_value=chunks), \
         patch("sys.argv", ["backfill", "--apply"]):
        bf.main()

    # It SELECTs every column it carries, or row[col] would KeyError.
    selected = set(paged.call_args[0][1].split(","))
    assert {"id", "chunk_text", "course_id", "chunk_hash", "semester"} <= selected

    written = chunks.upsert.call_args[0][0][0]
    assert written["id"] == "c1"
    assert written["course_id"] == "CAS CS 330"
    assert written["chunk_hash"] == "h-1"
    assert written["semester"] == "Fall 2026"
    assert decrypt(written["chunk_text"]) == "plain passage"



def test_backfill_failure_surfaces_postgrest_error_body():
    """A bare `raise_for_status` reported only "500 Internal Server Error" on
    prod; the Postgres code/message lives in the response body."""
    import httpx
    import scripts.backfill_encrypt_chunk_text as bf

    req = httpx.Request("POST", "https://x.supabase.co/rest/v1/course_chunks")
    resp = httpx.Response(
        500, request=req,
        text='{"code":"57014","message":"canceling statement due to statement timeout"}',
    )
    chunks = MagicMock()
    chunks.upsert.side_effect = httpx.HTTPStatusError("500", request=req, response=resp)
    with patch.object(bf, "table", return_value=chunks):
        with pytest.raises(SystemExit) as exc:
            bf._write([{"id": "c1", "chunk_text": "x"}])
    msg = str(exc.value)
    assert "57014" in msg and "statement timeout" in msg and "'c1'" in msg


def test_backfill_honours_batch_size():
    import scripts.backfill_encrypt_chunk_text as bf

    rows = [{"id": f"c{i}", "course_id": "C", "chunk_text": f"t{i}",
             "chunk_hash": f"h{i}", "semester": "S"} for i in range(7)]
    chunks = MagicMock()
    with patch.object(bf, "_assert_key_matches_database"), \
         patch.object(bf, "page_all", return_value=iter(rows)), \
         patch.object(bf, "table", return_value=chunks), \
         patch("sys.argv", ["backfill", "--apply", "--batch-size", "3"]):
        bf.main()
    assert [len(c[0][0]) for c in chunks.upsert.call_args_list] == [3, 3, 1]

# ── #484 review: the backfill's idempotence rests on the key matching ────────


class TestBackfillKeyGuard:
    """`_is_ciphertext` cannot tell "not yet encrypted" from "encrypted under a
    DIFFERENT key" — both simply fail to decrypt. So the wrong key turns the
    documented "a second run is a no-op" into a silent double-encrypt of the
    whole table, after which the live app can decrypt nothing. Staging is a
    separate Supabase project with a different ENCRYPTION_KEY and the script's
    own docstring tells you to point it there, so this is a live hazard, not a
    theoretical one."""

    @staticmethod
    def _tables(witness_values):
        def _table(name):
            m = MagicMock()
            if name == "users":
                m.select.return_value = [{"email": v} for v in witness_values]
            else:
                m.select.return_value = []
            return m
        return _table

    def test_a_key_that_cannot_decrypt_this_database_aborts(self):
        import scripts.backfill_encrypt_chunk_text as bf

        # Ciphertext from another key is indistinguishable from plaintext here.
        with patch.object(bf, "table", side_effect=self._tables(["not-our-ciphertext"])):
            with pytest.raises(SystemExit) as exc:
                bf._assert_key_matches_database()
        assert "does not match this database" in str(exc.value)

    def test_a_matching_key_proceeds(self):
        import scripts.backfill_encrypt_chunk_text as bf

        with patch.object(
            bf, "table", side_effect=self._tables([encrypt("someone@example.com")])
        ):
            bf._assert_key_matches_database()  # no SystemExit

    def test_no_witness_rows_warns_but_does_not_abort(self):
        """A brand-new database has nothing to verify against; refusing there
        would block the one case where running this is trivially safe."""
        import scripts.backfill_encrypt_chunk_text as bf

        with patch.object(bf, "table", side_effect=self._tables([])):
            bf._assert_key_matches_database()
