"""Tests for the optional Redis cache (#97): the wrapper's graceful no-op /
fake-client behavior, and the OCR content-addressed cache in extraction_service."""
from unittest.mock import MagicMock

from services import cache, extraction_service


class TestCacheDisabledByDefault:
    def test_no_redis_url_is_a_clean_noop(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        cache.reset()
        assert cache.enabled() is False
        assert cache.get_str("k") is None
        cache.set_str("k", "v", ttl_seconds=60)  # no-op, must not raise
        assert cache.get_str("k") is None


class TestCacheWithFakeRedis:
    def _install_fake(self, monkeypatch):
        store = {}
        fake = MagicMock()
        fake.get.side_effect = lambda k: store.get(k)
        def _set(k, v, ex=None):
            store[k] = v
        fake.set.side_effect = _set
        cache.reset()
        monkeypatch.setattr(cache, "_client", fake)
        monkeypatch.setattr(cache, "_initialized", True)
        return store

    def test_round_trips_str_as_bytes(self, monkeypatch):
        store = self._install_fake(monkeypatch)
        assert cache.enabled() is True
        cache.set_str("k", "hello", ttl_seconds=60)
        assert store["k"] == b"hello"          # encoded to bytes on write
        assert cache.get_str("k") == "hello"   # decoded on read
        assert cache.get_str("missing") is None

    def test_get_swallows_backend_errors(self, monkeypatch):
        self._install_fake(monkeypatch)
        cache._client.get.side_effect = RuntimeError("redis down")
        assert cache.get_str("k") is None  # error → clean miss, never raises


class TestOcrContentCache:
    def _patch_extract(self, monkeypatch, marker="FRESH"):
        calls = {"n": 0}
        def _fake(file_bytes, filename, content_type):
            calls["n"] += 1
            return marker
        monkeypatch.setattr(extraction_service, "_extract_text_from_file_uncached", _fake)
        return calls

    def test_disabled_skips_cache_and_extracts(self, monkeypatch):
        monkeypatch.setattr(extraction_service.cache, "enabled", lambda: False)
        calls = self._patch_extract(monkeypatch)
        out = extraction_service.extract_text_from_file(b"pdf", "f.pdf", "application/pdf")
        assert out == "FRESH"
        assert calls["n"] == 1

    def test_cache_hit_skips_extraction(self, monkeypatch):
        monkeypatch.setattr(extraction_service.cache, "enabled", lambda: True)
        monkeypatch.setattr(extraction_service.cache, "get_str", lambda k: "CACHED")
        calls = self._patch_extract(monkeypatch)
        out = extraction_service.extract_text_from_file(b"pdf", "f.pdf", "application/pdf")
        assert out == "CACHED"
        assert calls["n"] == 0  # the OCR pipeline never ran

    def test_cache_miss_extracts_then_stores(self, monkeypatch):
        stored = {}
        monkeypatch.setattr(extraction_service.cache, "enabled", lambda: True)
        monkeypatch.setattr(extraction_service.cache, "get_str", lambda k: None)
        monkeypatch.setattr(
            extraction_service.cache, "set_str",
            lambda k, v, ttl_seconds=None: stored.update({k: v}),
        )
        calls = self._patch_extract(monkeypatch, marker="FRESH")
        out = extraction_service.extract_text_from_file(b"pdf", "f.pdf", "application/pdf")
        assert out == "FRESH"
        assert calls["n"] == 1
        assert list(stored.values()) == ["FRESH"]  # result written back
        # key is content-addressed under the ocr: namespace
        assert next(iter(stored)).startswith("ocr:")

    def test_key_differs_by_content(self, monkeypatch):
        keys = []
        monkeypatch.setattr(extraction_service.cache, "enabled", lambda: True)
        monkeypatch.setattr(extraction_service.cache, "get_str", lambda k: keys.append(k) or None)
        monkeypatch.setattr(extraction_service.cache, "set_str", lambda k, v, ttl_seconds=None: None)
        self._patch_extract(monkeypatch)
        extraction_service.extract_text_from_file(b"AAA", "f.pdf", "application/pdf")
        extraction_service.extract_text_from_file(b"BBB", "f.pdf", "application/pdf")
        assert keys[0] != keys[1]  # different bytes → different cache key


class TestCacheInitState:
    """#771: a failed connect used to latch the cache off for the process,
    and concurrent first callers saw the half-initialized state as off."""

    def _fake_redis(self, monkeypatch, ping):
        import sys
        import types

        built = []

        class _Redis:
            @staticmethod
            def from_url(url, **_k):
                c = MagicMock()
                c.ping.side_effect = ping
                built.append(c)
                return c

        monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_Redis))
        monkeypatch.setenv("REDIS_URL", "redis://example:6379")
        cache.reset()
        return built

    def test_a_failed_connect_is_retried_after_backoff(self, monkeypatch):
        state = {"up": False}

        def ping():
            if not state["up"]:
                raise ConnectionError("down")

        built = self._fake_redis(monkeypatch, ping)
        clock = {"t": 1000.0}
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock["t"])
        assert cache.enabled() is False
        assert cache.enabled() is False  # inside the backoff: no reconnect
        assert len(built) == 1
        state["up"] = True
        clock["t"] += cache._RETRY_BASE_S + 1
        assert cache.enabled() is True
        assert len(built) == 2

    def test_backoff_doubles_and_is_capped(self, monkeypatch):
        def ping():
            raise ConnectionError("down")

        self._fake_redis(monkeypatch, ping)
        clock = {"t": 0.0}
        monkeypatch.setattr(cache.time, "monotonic", lambda: clock["t"])
        waits = []
        for _ in range(12):
            cache.enabled()
            waits.append(cache._retry_at - clock["t"])
            clock["t"] = cache._retry_at
        assert waits[:3] == [5.0, 10.0, 20.0]
        assert max(waits) == cache._RETRY_MAX_S

    def test_concurrent_first_callers_share_one_connect(self, monkeypatch):
        import threading

        gate = threading.Event()
        built = self._fake_redis(monkeypatch, lambda: gate.wait(5))
        results = []
        threads = [threading.Thread(target=lambda: results.append(cache.enabled()))
                   for _ in range(6)]
        for t in threads:
            t.start()
        gate.set()
        for t in threads:
            t.join(5)
        assert results == [True] * 6
        assert len(built) == 1
        cache.reset()
