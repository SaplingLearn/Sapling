"""#629: who may retrieve a course chunk.

`user_settings.share_class_context` (0037) was enforced at exactly one write
chokepoint — the class-aggregate rollup — and nowhere in RAG. An opted-out
student's upload still landed in the shared `course_chunks` pool and still
surfaced in a classmate's tutor. These pin the three pieces that close it:
the stored-flag read, the contributor ledger that makes "flip my chunks to
private" answerable at all, and the resync that runs when the toggle moves.
"""
from unittest.mock import MagicMock, patch

import pytest


def _tables(**by_name):
    """Dispatch `table(name)` to a per-name MagicMock, defaulting to no rows."""
    def _table(name):
        if name in by_name:
            return by_name[name]
        m = MagicMock()
        m.select.return_value = []
        m.select_with_count.return_value = ([], 0)
        return m
    return _table


def _settings(rows):
    m = MagicMock()
    m.select.return_value = rows
    return m


def _contributors(rows):
    """A `course_chunk_contributors` handle whose paged read yields `rows`."""
    m = MagicMock()
    m.select.return_value = rows
    m.select_with_count.return_value = (rows, len(rows))
    return m


# ── The stored flag ─────────────────────────────────────────────────────────

class TestSharesClassContext:
    def test_missing_settings_row_counts_as_opted_in(self):
        """Matches 0037's column default and the class-aggregate filter: only
        an explicit `false` opts a student out."""
        from services.chunk_visibility import shares_class_context

        with patch("services.chunk_visibility.table", side_effect=_tables()):
            assert shares_class_context("u1") is True

    def test_explicit_false_opts_out(self):
        from services.chunk_visibility import shares_class_context

        tables = _tables(user_settings=_settings(
            [{"user_id": "u1", "share_class_context": False}]
        ))
        with patch("services.chunk_visibility.table", side_effect=tables):
            assert shares_class_context("u1") is False

    def test_explicit_true_opts_in(self):
        from services.chunk_visibility import shares_class_context

        tables = _tables(user_settings=_settings(
            [{"user_id": "u1", "share_class_context": True}]
        ))
        with patch("services.chunk_visibility.table", side_effect=tables):
            assert shares_class_context("u1") is True

    def test_a_failed_read_fails_CLOSED(self, caplog):
        """The default is opted IN, so a read failure that fell back to the
        default would publish an opted-out student's upload to the whole class
        on a transient blip. The only safe direction here is private."""
        from services.chunk_visibility import shares_class_context

        broken = MagicMock()
        broken.select.side_effect = Exception("PostgREST down")
        with patch("services.chunk_visibility.table",
                   side_effect=_tables(user_settings=broken)):
            with caplog.at_level("WARNING", logger="services.chunk_visibility"):
                assert shares_class_context("u1") is False
        assert any(r.levelname == "WARNING" for r in caplog.records)


class TestVisibilityFor:
    def test_opted_in_user_gets_shared(self):
        from services.chunk_visibility import SHARED, visibility_for

        with patch("services.chunk_visibility.table", side_effect=_tables()):
            assert visibility_for("u1") == SHARED

    def test_opted_out_user_gets_private(self):
        from services.chunk_visibility import PRIVATE, visibility_for

        tables = _tables(user_settings=_settings(
            [{"user_id": "u1", "share_class_context": False}]
        ))
        with patch("services.chunk_visibility.table", side_effect=tables):
            assert visibility_for("u1") == PRIVATE


# ── The contributor ledger ──────────────────────────────────────────────────

class TestRecordContributors:
    def test_records_one_row_per_chunk(self):
        from services.chunk_visibility import record_contributors

        contrib = MagicMock()
        with patch("services.chunk_visibility.table",
                   side_effect=_tables(course_chunk_contributors=contrib)):
            record_contributors(["c1", "c2"], "u1")

        payload = contrib.upsert.call_args[0][0]
        assert {(r["chunk_id"], r["user_id"]) for r in payload} == {
            ("c1", "u1"), ("c2", "u1"),
        }

    def test_upserts_on_the_composite_key(self):
        """Re-uploading the same file must not raise a duplicate-key error,
        and must not create a second contributor row for the same pair."""
        from services.chunk_visibility import record_contributors

        contrib = MagicMock()
        with patch("services.chunk_visibility.table",
                   side_effect=_tables(course_chunk_contributors=contrib)):
            record_contributors(["c1"], "u1")

        assert contrib.upsert.call_args.kwargs["on_conflict"] == "chunk_id,user_id"

    def test_no_chunks_writes_nothing(self):
        from services.chunk_visibility import record_contributors

        contrib = MagicMock()
        with patch("services.chunk_visibility.table",
                   side_effect=_tables(course_chunk_contributors=contrib)):
            record_contributors([], "u1")

        contrib.upsert.assert_not_called()

    def test_a_failed_write_does_not_raise(self, caplog):
        """Indexing is best-effort post-roll work; losing the ledger row must
        not lose the chunks that were already upserted."""
        from services.chunk_visibility import record_contributors

        contrib = MagicMock()
        contrib.upsert.side_effect = Exception("PostgREST down")
        with patch("services.chunk_visibility.table",
                   side_effect=_tables(course_chunk_contributors=contrib)):
            with caplog.at_level("WARNING", logger="services.chunk_visibility"):
                record_contributors(["c1"], "u1")
        assert any(r.levelname == "WARNING" for r in caplog.records)


# ── The toggle resync ───────────────────────────────────────────────────────

class TestResyncUserChunkVisibility:
    @staticmethod
    def _setup(contributor_rows, settings_rows, chunk_rows):
        chunks = MagicMock()
        chunks.select.return_value = chunk_rows
        chunks.select_with_count.return_value = (chunk_rows, len(chunk_rows))
        return _tables(
            course_chunk_contributors=_contributors(contributor_rows),
            user_settings=_settings(settings_rows),
            course_chunks=chunks,
        ), chunks

    def test_sole_contributor_opting_out_flips_the_chunk_private(self):
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[{"chunk_id": "c1", "user_id": "u1"}],
            settings_rows=[{"user_id": "u1", "share_class_context": False}],
            chunk_rows=[{"id": "c1", "visibility": "shared"}],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            result = resync_user_chunk_visibility("u1")

        chunks.update.assert_called_once()
        assert chunks.update.call_args[0][0] == {"visibility": "private"}
        assert "c1" in chunks.update.call_args.kwargs["filters"]["id"]
        assert result["to_private"] == 1

    def test_a_remaining_opted_in_contributor_keeps_the_chunk_shared(self):
        """The chunk is one row shared by two uploaders; the content is not
        exclusively the opting-out student's, so it stays in the pool."""
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[
                {"chunk_id": "c1", "user_id": "u1"},
                {"chunk_id": "c1", "user_id": "u2"},
            ],
            settings_rows=[
                {"user_id": "u1", "share_class_context": False},
                {"user_id": "u2", "share_class_context": True},
            ],
            chunk_rows=[{"id": "c1", "visibility": "shared"}],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            result = resync_user_chunk_visibility("u1")

        chunks.update.assert_not_called()
        assert result == {"to_private": 0, "to_shared": 0, "considered": 1}

    def test_opting_back_in_reshares_a_chunk_that_was_flipped(self):
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[{"chunk_id": "c1", "user_id": "u1"}],
            settings_rows=[{"user_id": "u1", "share_class_context": True}],
            chunk_rows=[{"id": "c1", "visibility": "private"}],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            result = resync_user_chunk_visibility("u1")

        assert chunks.update.call_args[0][0] == {"visibility": "shared"}
        assert result["to_shared"] == 1

    def test_a_chunk_already_in_the_right_state_is_not_rewritten(self):
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[{"chunk_id": "c1", "user_id": "u1"}],
            settings_rows=[{"user_id": "u1", "share_class_context": True}],
            chunk_rows=[{"id": "c1", "visibility": "shared"}],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            resync_user_chunk_visibility("u1")

        chunks.update.assert_not_called()

    def test_a_user_with_no_contributed_chunks_writes_nothing(self):
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[], settings_rows=[], chunk_rows=[],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            assert resync_user_chunk_visibility("u1") == {
                "to_private": 0, "to_shared": 0, "considered": 0,
            }
        chunks.update.assert_not_called()

    def test_a_contributor_with_no_settings_row_counts_as_opted_in(self):
        """Same default as everywhere else: the absence of a row is consent,
        so a chunk whose only other contributor has never opened settings
        must not be dragged private."""
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[
                {"chunk_id": "c1", "user_id": "u1"},
                {"chunk_id": "c1", "user_id": "u2"},
            ],
            settings_rows=[{"user_id": "u1", "share_class_context": False}],
            chunk_rows=[{"id": "c1", "visibility": "shared"}],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            resync_user_chunk_visibility("u1")

        chunks.update.assert_not_called()

    def test_updates_are_batched_under_the_url_length_cap(self):
        """One `in.(…)` per 200 ids rather than one filter holding thousands."""
        from services.chunk_visibility import _ID_BATCH, resync_user_chunk_visibility

        n = _ID_BATCH + 5
        ids = [f"c{i}" for i in range(n)]
        tables, chunks = self._setup(
            contributor_rows=[{"chunk_id": i, "user_id": "u1"} for i in ids],
            settings_rows=[{"user_id": "u1", "share_class_context": False}],
            chunk_rows=[{"id": i, "visibility": "shared"} for i in ids],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            result = resync_user_chunk_visibility("u1")

        assert chunks.update.call_count == 2
        assert result["to_private"] == n

    def test_the_contributor_read_is_paged(self):
        """A popular chunk has one ledger row per uploader, so a batch of ids
        can sit behind thousands of rows. PostgREST caps the read at `max_rows`
        and answers 206 — a 2xx that `raise_for_status()` lets through — so an
        unpaged read returns a TRUNCATED contributor set, and the chunks whose
        rows fell off the end look uncontributed. Privatising those withdraws
        material every other uploader legitimately shared."""
        from db.connection import MAX_ROWS
        from services.chunk_visibility import resync_user_chunk_visibility

        # One chunk, contributed by more uploaders than a single page holds.
        page1 = [{"chunk_id": "c1", "user_id": f"u{i}"} for i in range(MAX_ROWS)]
        page2 = [{"chunk_id": "c1", "user_id": "u-last"}]
        contrib = MagicMock()
        contrib.select.return_value = [{"chunk_id": "c1", "user_id": "u1"}]
        contrib.select_with_count.side_effect = [
            # page_all over this user's own rows (short page -> done)
            ([{"chunk_id": "c1", "user_id": "u1"}], 1),
            # page_all over every contributor of c1: full page, then the rest
            (page1, 0),
            (page2, 0),
        ]
        chunks = MagicMock()
        chunks.select.return_value = [{"id": "c1", "visibility": "shared"}]
        tables = _tables(
            course_chunk_contributors=contrib,
            # u1 opts out; u-last — visible only on the SECOND page — is still in.
            user_settings=_settings([{"user_id": "u1", "share_class_context": False}]),
            course_chunks=chunks,
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            result = resync_user_chunk_visibility("u1")

        # The second page is what saves the chunk. Without it, u1 reads as the
        # only contributor of a row 1000 other students also fed.
        chunks.update.assert_not_called()
        assert result["to_private"] == 0

    def test_a_chunk_whose_ledger_rows_vanished_is_left_alone(self):
        """Absence after a COMPLETE read means this user's own row was deleted
        mid-run, so the chunk is no longer theirs to withdraw. Inferring sole
        ownership from an empty set is how a truncated read turns into
        class-wide data loss — c2 below is legitimately withdrawn, c1 is not
        touched, and the old fallback would have privatised both."""
        from services.chunk_visibility import resync_user_chunk_visibility

        contrib = MagicMock()
        contrib.select_with_count.side_effect = [
            # This user's own ledger rows name both chunks…
            ([{"chunk_id": "c1", "user_id": "u1"},
              {"chunk_id": "c2", "user_id": "u1"}], 2),
            # …but the per-chunk read comes back with rows for c2 only.
            ([{"chunk_id": "c2", "user_id": "u1"}], 1),
        ]
        chunks = MagicMock()
        chunks.select.return_value = [
            {"id": "c1", "visibility": "shared"},
            {"id": "c2", "visibility": "shared"},
        ]
        tables = _tables(
            course_chunk_contributors=contrib,
            user_settings=_settings([{"user_id": "u1", "share_class_context": False}]),
            course_chunks=chunks,
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            result = resync_user_chunk_visibility("u1")

        assert result["to_private"] == 1
        assert "c2" in chunks.update.call_args.kwargs["filters"]["id"]
        assert "c1" not in chunks.update.call_args.kwargs["filters"]["id"]

    def test_a_private_namespace_chunk_is_never_resurfaced(self):
        """A chunk uploaded while opted out lives under a private id namespace
        (`rag_service.chunk_id`) and has no contributor row, so opting back in
        must not flip it shared — its id could never merge with the shared row
        for the same text, and two rows holding one passage would both rank."""
        from services.chunk_visibility import resync_user_chunk_visibility

        tables, chunks = self._setup(
            contributor_rows=[],
            settings_rows=[{"user_id": "u1", "share_class_context": True}],
            chunk_rows=[{"id": "private-c1", "visibility": "private"}],
        )
        with patch("services.chunk_visibility.table", side_effect=tables):
            resync_user_chunk_visibility("u1")

        chunks.update.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__])


class TestResyncFailureIsVisible:
    """#629 review: the resync runs as a post-response BackgroundTask, where an
    exception vanishes. The student sees the toggle succeed while their uploads
    stay in classmates' retrieval — the exact failure a privacy control cannot
    have silently."""

    def test_a_failed_resync_does_not_raise_and_is_counted(self, caplog):
        from services.chunk_visibility import resync_user_chunk_visibility

        broken = MagicMock()
        broken.select_with_count.side_effect = Exception("PostgREST 503")
        with (
            patch("services.chunk_visibility.table",
                  side_effect=_tables(course_chunk_contributors=broken)),
            patch("services.chunk_visibility.log_event") as mock_log_event,
        ):
            with caplog.at_level("ERROR", logger="services.chunk_visibility"):
                result = resync_user_chunk_visibility("u1")

        assert result["failed"] is True
        assert any(r.levelname == "ERROR" for r in caplog.records)
        assert mock_log_event.call_args.args[0] == "rag.visibility_resync_failed"

    def test_a_successful_resync_emits_no_failure_event(self):
        from services.chunk_visibility import resync_user_chunk_visibility

        with (
            patch("services.chunk_visibility.table", side_effect=_tables()),
            patch("services.chunk_visibility.log_event") as mock_log_event,
        ):
            assert resync_user_chunk_visibility("u1") == {
                "to_private": 0, "to_shared": 0, "considered": 0,
            }
        mock_log_event.assert_not_called()
