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
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        lc.main(["--pdf", str(pdf), "--flag", "both"])
    assert patches[0] == lc.only("off")
    assert patches[-1] == original


def test_each_pass_uploads_different_bytes_that_still_start_with_the_pdf():
    raw = b"%PDF-1.4\n...\n%%EOF"
    a, b = lc.unique_pdf(raw, "r1-off"), lc.unique_pdf(raw, "r1-on")
    assert a != b and a.startswith(raw) and b.startswith(raw)
    assert a.endswith(b"\n%sapling-latency-check r1-off\n")
    assert lc.unique_pdf(raw + b"\n", "x") == raw + b"\n%sapling-latency-check x\n"


def test_the_settle_wait_is_the_flag_snapshot_ttl():
    from services import feature_flags as ff

    assert lc.flag_settle_seconds() >= ff.DEFAULT_SNAPSHOT_TTL_S
    assert lc.flag_settle_seconds(5) == 5


def test_flag_both_waits_out_the_snapshot_ttl_and_uploads_distinct_bytes(monkeypatch, tmp_path):
    from services import feature_flags as ff

    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    timeline: list = []

    class FakeAdmin:
        def get(self, path):
            return httpx.Response(200, json={"flags": [{"key": "jobs_queue",
                                                        "default_variant": "off"}]},
                                  request=httpx.Request("GET", "http://x"))

        def patch(self, path, json):
            timeline.append(("flag", json["default_variant"]))
            return httpx.Response(200, json={}, request=httpx.Request("PATCH", "http://x"))

    monkeypatch.setattr(lc.Client, "session", lambda self, user: FakeAdmin())
    monkeypatch.setattr(lc.time, "sleep", lambda s: timeline.append(("sleep", s)))

    def run_pair(cl, args, label, body):
        timeline.append(("pass", label, body))
        return [lc.Scenario(label)]

    monkeypatch.setattr(lc, "run_pair", run_pair)
    assert lc.main(["--pdf", str(pdf), "--flag", "both"]) == 0

    kinds = [t[0] for t in timeline]
    assert kinds == ["flag", "sleep", "pass", "flag", "sleep", "pass", "flag"]
    assert all(t[1] >= ff.DEFAULT_SNAPSHOT_TTL_S for t in timeline if t[0] == "sleep")
    bodies = [t[2] for t in timeline if t[0] == "pass"]
    assert len(set(bodies)) == 2
    assert all(b.startswith(pdf.read_bytes()) for b in bodies)
