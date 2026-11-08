"""scripts/latency_check.py (#116): the local-only chat-TTFT probe.

Never run against a server here: these pin the localhost guard, the TTFT
parse of the SSE stream (over httpx.MockTransport) and the flag restore.
"""
import httpx
import pytest

from scripts import latency_check as lc


@pytest.mark.parametrize("url,local", [
    ("http://localhost:5000", True),
    ("http://127.0.0.1:5001/", True),
    ("http://[::1]:5000", True),
    ("https://api.saplinglearn.com", False),
    ("https://sapling-staging.up.railway.app", False),
    ("http://localhost.evil.example", False),
])
def test_only_localhost_is_allowed(url, local):
    assert lc.is_local_url(url) is local


def test_a_remote_url_is_refused_without_i_know(tmp_path, capsys):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert lc.main(["--url", "https://api.saplinglearn.com", "--pdf", str(pdf)]) == lc.EXIT_USAGE
    assert "refusing" in capsys.readouterr().err


def test_a_missing_pdf_is_a_usage_error(tmp_path):
    assert lc.main(["--pdf", str(tmp_path / "nope.pdf")]) == lc.EXIT_USAGE


def test_percentile_is_nearest_rank():
    vals = [float(v) for v in range(1, 21)]
    assert lc.percentile(vals, 50) == 10
    assert lc.percentile(vals, 95) == 19
    assert lc.percentile([3.0], 95) == 3.0


def _sse(*events):
    return "".join(f"event: {e}\ndata: {{\"type\": \"{e}\"}}\n\n" for e in events)


def test_ttft_is_the_first_token_event_and_the_stream_is_drained():
    sent = {}

    def handler(request):
        sent["body"] = request.content
        return httpx.Response(200, text=_sse("status", "token", "token", "done"),
                              headers={"content-type": "text/event-stream"})

    c = httpx.Client(base_url="http://localhost:5000", transport=httpx.MockTransport(handler))
    assert lc.chat_ttft(c, "u1", "s1") >= 0
    assert b'"session_id":"s1"' in sent["body"].replace(b" ", b"")


def test_a_stream_without_a_token_is_an_error():
    def handler(request):
        return httpx.Response(200, text=_sse("status", "error"))

    c = httpx.Client(base_url="http://localhost:5000", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        lc.chat_ttft(c, "u1", "s1")


def test_the_flag_is_restored_exactly(monkeypatch, tmp_path):
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    patches = []
    original = {"default_variant": "off", "rollout_percent": 25, "rollout_variant": "on"}

    class FakeAdmin:
        def get(self, path):
            return httpx.Response(200, json={"flags": [{"key": "jobs_queue", **original}]},
                                  request=httpx.Request("GET", "http://x"))

        def patch(self, path, json):
            patches.append(json)
            return httpx.Response(200, json={}, request=httpx.Request("PATCH", "http://x"))

    monkeypatch.setattr(lc.Client, "session", lambda self, user: FakeAdmin())

    def boom(*a, **k):
        raise RuntimeError("stack fell over mid-run")

    monkeypatch.setattr(lc, "run_pair", boom)
    with pytest.raises(RuntimeError):
        lc.main(["--pdf", str(pdf), "--flag", "both"])
    assert patches[0] == lc.only("off")
    assert patches[-1] == original
