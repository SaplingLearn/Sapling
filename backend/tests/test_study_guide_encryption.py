"""
Unit tests for the study_guides.content encryption boundary (#518 Task 10).

Pins:
  - _generate_and_insert writes ciphertext to study_guides.content, but the
    RESPONSE (GET /guide, uncached path) still carries the plaintext dict —
    the response is built from the local plaintext variable, not a re-read
    of the encrypted row, so this must be asserted explicitly (the flashcards
    task hit exactly this trap: fixing the row dict alone can still leave a
    stale plaintext reference feeding the response).
  - GET /guide (cached path) and GET /cached both decrypt content before
    building their response.
  - Both readers tolerate legacy plaintext dict rows (pre-encryption data)
    identically to encrypted rows.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from services.encryption import decrypt_json_column, encrypt_json

client = TestClient(app)

USER_ID = "user_test"
COURSE_ID = "course_1"
EXAM_ID = "exam_1"


def _agent_run_returning(content):
    """AsyncMock standing in for study_guide_agent.run; its .output.model_dump()
    yields the given legacy-dict content."""
    return AsyncMock(
        return_value=SimpleNamespace(
            output=SimpleNamespace(model_dump=lambda: content)
        )
    )


class TestGenerateInsertsEncryptedContent:
    def test_generate_inserts_encrypted_content(self):
        fresh_content = {"exam": "Final", "topics": [{"name": "Topic 1"}]}
        captured = {}

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = []  # nothing cached → generate

                def _insert(row):
                    captured["row"] = row
                    return [{}]
                m.insert.side_effect = _insert
            elif name == "assignments":
                m.select.return_value = [{"title": "Final", "due_date": "2026-05-01"}]
            elif name == "enrollments":
                m.select.return_value = [{"id": "enr1", "offering_id": "off1"}]
            elif name == "documents":
                m.select.return_value = []
            else:
                m.select.return_value = []
            return m

        agent_run = _agent_run_returning(fresh_content)
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.user_enrollment_ids", return_value=[{"id": "enr1", "offering_id": "off1"}]), \
             patch("routes.study_guide.resolve_offering", return_value="off1"), \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")

        assert r.status_code == 200
        # The persisted row must be ciphertext, not the raw dict.
        row = captured["row"]
        assert isinstance(row["content"], str)
        assert row["content"] != fresh_content
        assert decrypt_json_column(row["content"])["exam"] == "Final"

        # The trap: the response is built from the local plaintext `content`
        # variable in _generate_and_insert, not by re-reading/decrypting the
        # row — so it must still come back as a plaintext dict, unchanged.
        body = r.json()
        assert body["cached"] is False
        assert body["guide"] == fresh_content
        assert body["guide"]["exam"] == "Final"


class TestCachedReadDecryptsContent:
    def test_cached_read_decrypts_content(self):
        plaintext = {"exam": "Midterm", "topics": ["a", "b"]}
        cached_row = {
            "id": "g1", "user_id": USER_ID,
            "offering_id": "off1", "exam_id": EXAM_ID,
            "generated_at": "2026-04-01T00:00:00Z",
            "content": encrypt_json(plaintext),
        }
        agent_run = _agent_run_returning({"exam": "should not be used", "topics": []})
        with patch("routes.study_guide.table") as t, \
             patch("routes.study_guide.study_guide_agent.run", new=agent_run):
            t.return_value.select.return_value = [cached_row]
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")

        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is True
        # The response "guide" must be the plaintext dict, not ciphertext.
        assert body["guide"] == plaintext
        agent_run.assert_not_called()


class TestListDecryptsContentForTitles:
    def test_list_decrypts_content_for_titles(self):
        guides = [
            {"id": "g1", "offering_id": "off1", "exam_id": "e1",
             "generated_at": "2026-04-01T00:00:00Z",
             "content": encrypt_json({"exam": "Midterm", "overview": "Covers ch1-5"})},
            {"id": "g2", "offering_id": "off-untermed", "exam_id": "e2",
             "generated_at": "2026-03-01T00:00:00Z",
             "content": encrypt_json({"exam": "Final", "overview": ""})},
        ]

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = guides
            elif name == "courses":
                m.select.return_value = [{"id": "c1", "course_name": "Calc II"}]
            else:
                m.select.return_value = []
            return m

        terms = {"off1": {"id": "term-f25", "label": "Fall 2025"}}
        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.offering_course_id", return_value="c1"), \
             patch("routes.study_guide.term_for_offering",
                   side_effect=lambda o: terms.get(o)):
            r = client.get(f"/api/study-guide/{USER_ID}/cached")

        assert r.status_code == 200
        out = r.json()["guides"]
        assert out[0]["exam_title"] == "Midterm"
        assert out[0]["overview"] == "Covers ch1-5"
        assert out[1]["exam_title"] == "Final"
        assert out[1]["overview"] == ""


class TestReadsTolerateLegacyPlaintextDictRows:
    def test_guide_cached_read_tolerates_legacy_plaintext_dict(self):
        plaintext = {"exam": "Midterm", "topics": ["a", "b"]}
        cached_row = {
            "id": "g1", "user_id": USER_ID,
            "offering_id": "off1", "exam_id": EXAM_ID,
            "generated_at": "2026-04-01T00:00:00Z",
            "content": plaintext,  # legacy: raw dict, never encrypted
        }
        with patch("routes.study_guide.table") as t:
            t.return_value.select.return_value = [cached_row]
            r = client.get(f"/api/study-guide/{USER_ID}/guide?course_id={COURSE_ID}&exam_id={EXAM_ID}")

        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is True
        assert body["guide"] == plaintext

    def test_list_tolerates_legacy_plaintext_dict_rows(self):
        guides = [
            {"id": "g1", "offering_id": "off1", "exam_id": "e1",
             "generated_at": "2026-04-01T00:00:00Z",
             "content": {"exam": "Midterm", "overview": "Covers ch1-5"}},  # legacy dict
        ]

        def table_side_effect(name):
            m = MagicMock()
            if name == "study_guides":
                m.select.return_value = guides
            else:
                m.select.return_value = []
            return m

        with patch("routes.study_guide.table", side_effect=table_side_effect), \
             patch("routes.study_guide.offering_course_id", return_value="c1"), \
             patch("routes.study_guide.term_for_offering", return_value=None):
            r = client.get(f"/api/study-guide/{USER_ID}/cached")

        assert r.status_code == 200
        out = r.json()["guides"][0]
        assert out["exam_title"] == "Midterm"
        assert out["overview"] == "Covers ch1-5"

    def test_encrypted_and_legacy_rows_produce_identical_list_responses(self):
        """Same content, once ciphertext once a raw dict — the /cached response
        entries must be identical either way."""
        plaintext_content = {"exam": "Final", "overview": "Chapters 6-10"}

        def _run(content_value):
            guides = [{
                "id": "g1", "offering_id": "off1", "exam_id": "e1",
                "generated_at": "2026-04-01T00:00:00Z",
                "content": content_value,
            }]

            def table_side_effect(name):
                m = MagicMock()
                if name == "study_guides":
                    m.select.return_value = guides
                else:
                    m.select.return_value = []
                return m

            with patch("routes.study_guide.table", side_effect=table_side_effect), \
                 patch("routes.study_guide.offering_course_id", return_value=None), \
                 patch("routes.study_guide.term_for_offering", return_value=None):
                return client.get(f"/api/study-guide/{USER_ID}/cached").json()

        encrypted_response = _run(encrypt_json(plaintext_content))
        legacy_response = _run(dict(plaintext_content))

        assert encrypted_response == legacy_response
