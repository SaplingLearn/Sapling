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
