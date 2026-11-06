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
