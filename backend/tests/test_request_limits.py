"""Unit tests for the shared sliding-window limiter in services/request_limits.

The consumer-level behavior (OCR extraction, Gradescope routes) is covered in
test_extract_auth_bounds.py / test_gradescope.py; these pin the limiter's own
contract, especially the retry-hint bounds from #346.
"""
import services.request_limits as request_limits


class TestCheckRateLimit:
    def setup_method(self):
        request_limits._rate_state.clear()

    def test_allows_up_to_limit(self):
        for _ in range(3):
            assert request_limits.check_rate_limit("k", limit=3, window_sec=60) is None

    def test_over_limit_returns_retry(self):
        for _ in range(3):
            request_limits.check_rate_limit("k", limit=3, window_sec=60)
        retry = request_limits.check_rate_limit("k", limit=3, window_sec=60)
        assert retry is not None
        assert 0 < retry <= 60

    def test_keys_are_isolated(self):
        for _ in range(3):
            request_limits.check_rate_limit("k1", limit=3, window_sec=60)
        assert request_limits.check_rate_limit("k2", limit=3, window_sec=60) is None

    def test_resets_after_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(request_limits.time, "time", lambda: now[0])
        for _ in range(3):
            request_limits.check_rate_limit("k", limit=3, window_sec=60)
        now[0] = 1061.0
        assert request_limits.check_rate_limit("k", limit=3, window_sec=60) is None

    def test_retry_capped_at_window_on_coincident_timestamps(self, monkeypatch):
        # Windows' coarse timer (~15.6ms tick) reliably lands a tight loop of
        # calls on the identical time.time() value, so elapsed == 0.0 exactly
        # and the retry hint must still stay within (0, window] (#346).
        monkeypatch.setattr(request_limits.time, "time", lambda: 1000.0)
        for _ in range(3):
            request_limits.check_rate_limit("k", limit=3, window_sec=60)
        assert request_limits.check_rate_limit("k", limit=3, window_sec=60) == 60

    def test_retry_uses_ceiling_of_remaining_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(request_limits.time, "time", lambda: now[0])
        for _ in range(3):
            request_limits.check_rate_limit("k", limit=3, window_sec=60)
        now[0] = 1059.5  # 0.5s of the window left -> ceil to 1
        assert request_limits.check_rate_limit("k", limit=3, window_sec=60) == 1

    def test_retry_capped_when_clock_steps_backward(self, monkeypatch):
        # NTP can step time.time() BACKWARD between calls: now < bucket[0]
        # makes the remaining window exceed window_sec, and bare ceil() would
        # report an impossible retry hint (e.g. 61+s for a 60s window). The
        # min() cap is load-bearing exactly here (#346).
        now = [1000.0]
        monkeypatch.setattr(request_limits.time, "time", lambda: now[0])
        for _ in range(3):
            request_limits.check_rate_limit("k", limit=3, window_sec=60)
        now[0] = 998.5  # clock stepped back 1.5s
        assert request_limits.check_rate_limit("k", limit=3, window_sec=60) == 60


class TestClaimAndRefund:
    """#760: the refund must hand back the slot THIS request claimed. Popping
    the newest timestamp refunded whichever concurrent request claimed last —
    a different, still-running request's slot — and left the failed one's
    stamp charged."""

    def setup_method(self):
        request_limits._rate_state.clear()

    def test_claim_returns_the_recorded_slot(self):
        claim = request_limits.claim_rate_limit("k", limit=3, window_sec=60)
        assert claim.retry_after is None
        assert request_limits._rate_state["k"] == [claim.slot]

    def test_claim_over_limit_records_nothing(self):
        for _ in range(3):
            request_limits.claim_rate_limit("k", limit=3, window_sec=60)
        claim = request_limits.claim_rate_limit("k", limit=3, window_sec=60)
        assert claim.retry_after is not None
        assert claim.slot is None
        assert len(request_limits._rate_state["k"]) == 3

    def test_refund_removes_the_claimed_slot_not_the_newest(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(request_limits.time, "time", lambda: now[0])
        first = request_limits.claim_rate_limit("k", limit=3, window_sec=60)
        now[0] = 1001.0
        second = request_limits.claim_rate_limit("k", limit=3, window_sec=60)
        # The FIRST request fails while the second is still running.
        request_limits.refund_rate_limit("k", first.slot)
        assert request_limits._rate_state["k"] == [second.slot]

    def test_refund_of_an_expired_or_unknown_slot_is_a_noop(self):
        claim = request_limits.claim_rate_limit("k", limit=3, window_sec=60)
        request_limits.refund_rate_limit("k", claim.slot + 123.0)
        request_limits.refund_rate_limit("missing", claim.slot)
        request_limits.refund_rate_limit("k", None)
        assert request_limits._rate_state["k"] == [claim.slot]

    def test_check_rate_limit_is_unchanged(self):
        for _ in range(3):
            assert request_limits.check_rate_limit("k", limit=3, window_sec=60) is None
        assert request_limits.check_rate_limit("k", limit=3, window_sec=60) is not None


class TestReadWithinLimit:
    """The one capped upload reader (every upload route reads through it)."""

    @staticmethod
    def _upload(data: bytes):
        import io

        from fastapi import UploadFile

        return UploadFile(io.BytesIO(data), filename="f.bin")

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)

    def test_returns_the_bytes_within_the_cap(self):
        data = b"x" * 2048
        assert self._run(request_limits.read_within_limit(self._upload(data), 2048)) == data

    def test_default_refusal_is_413_with_the_size(self):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._run(request_limits.read_within_limit(self._upload(b"x" * (2 * 1024 * 1024 + 1)), 2 * 1024 * 1024))
        assert exc.value.status_code == 413
        assert exc.value.detail == "File too large. Maximum size is 2 MB."

    def test_caller_chooses_status_and_detail(self):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            self._run(request_limits.read_within_limit(
                self._upload(b"x" * 11), 10, status_code=400, detail="too big",
            ))
        assert (exc.value.status_code, exc.value.detail) == (400, "too big")

    def test_stops_reading_one_chunk_past_the_cap(self, monkeypatch):
        import pytest
        from fastapi import HTTPException, UploadFile

        reads = []
        real_read = UploadFile.read

        async def counting_read(self, size=-1):
            data = await real_read(self, size)
            reads.append(len(data))
            return data

        monkeypatch.setattr(UploadFile, "read", counting_read)
        with pytest.raises(HTTPException):
            self._run(request_limits.read_within_limit(self._upload(b"x" * (8 * 1024 * 1024)), 1024 * 1024))
        assert sum(reads) <= 2 * 1024 * 1024


class TestReadWithinLimitSync:
    """The twin for a sync (threadpool) handler: same cap, same refusal."""

    _upload = staticmethod(TestReadWithinLimit._upload)

    def test_returns_the_bytes_within_the_cap(self):
        data = b"x" * 2048
        assert request_limits.read_within_limit_sync(self._upload(data), 2048) == data

    def test_default_refusal_matches_the_async_reader(self):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            request_limits.read_within_limit_sync(self._upload(b"x" * (2 * 1024 * 1024 + 1)), 2 * 1024 * 1024)
        assert (exc.value.status_code, exc.value.detail) == (413, "File too large. Maximum size is 2 MB.")

    def test_caller_chooses_status_and_detail(self):
        import pytest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            request_limits.read_within_limit_sync(self._upload(b"x" * 11), 10, status_code=400, detail="too big")
        assert (exc.value.status_code, exc.value.detail) == (400, "too big")

    def test_stops_reading_one_chunk_past_the_cap(self):
        import io

        import pytest
        from fastapi import HTTPException, UploadFile

        reads = []

        class Counting(io.BytesIO):
            def read(self, size=-1):
                data = super().read(size)
                reads.append(len(data))
                return data

        with pytest.raises(HTTPException):
            request_limits.read_within_limit_sync(
                UploadFile(Counting(b"x" * (8 * 1024 * 1024)), filename="f.bin"), 1024 * 1024,
            )
        assert sum(reads) <= 2 * 1024 * 1024


def test_no_upload_route_keeps_a_capped_reader_of_its_own():
    """Every capped upload read goes through read_within_limit(_sync): no
    route reads `cap + 1` bytes by hand."""
    import pathlib
    import re

    routes = pathlib.Path(__file__).resolve().parents[1] / "routes"
    hand_rolled = re.compile(r"\.read\([^)]*\+\s*1\s*\)")
    offenders = sorted(p.name for p in routes.glob("*.py") if hand_rolled.search(p.read_text(encoding="utf-8")))
    assert offenders == []


def test_checked_upload_keeps_its_own_oversize_detail():
    """services/upload_validation reads through read_within_limit but keeps
    its route-facing wording and status (documents 400, calendar 413)."""
    import asyncio
    import io

    import pytest
    from fastapi import HTTPException, UploadFile

    from services import upload_validation as uv
    from tests.upload_fixtures import PDF_BYTES

    upload = UploadFile(io.BytesIO(PDF_BYTES + b"0" * (1024 * 1024)), filename="s.pdf")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(uv.read_checked_upload(
            upload, allowed=(uv.PDF,), max_bytes=1024 * 1024, unsupported_detail="no",
        ))
    assert exc.value.status_code == 413
    assert exc.value.detail == "File exceeds the 1 MB limit. Please upload a smaller file."
