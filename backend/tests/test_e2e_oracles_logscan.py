"""Hermetic tests for the #400 backend-log scanner. No stack, no DB."""

from e2e_oracles.findings import Finding, render_json, render_text  # noqa: F401 — Finding is part of the public interface under test
from e2e_oracles.logscan import scan_lines

ACCESS_500 = (
    'INFO:     127.0.0.1:53354 - "POST /api/graph/rich-user-active/'
    'concept-description HTTP/1.1" 500 Internal Server Error'
)
ACCESS_200 = 'INFO:     127.0.0.1:45290 - "GET /api/health HTTP/1.1" 200 OK'
REQLOG_500 = (
    "2026-07-27 22:17:25,882 [ERROR] sapling.request: "
    "[55bf1ed0-a791-4beb-ab1a-5e3c06cb78ef] GET /api/quiz/start -> 500 (23.0ms)"
)
ANSI_LINE = "\x1b[32m22:17:08.488\x1b[0m GET /api/health"

PLAIN_TRACEBACK = [
    "Traceback (most recent call last):",
    '  File "/app/routes/quiz.py", line 12, in start',
    "    raise ValueError(\"boom\")",
    "ValueError: boom",
]
GROUP_TRACEBACK = [
    "2026-07-27 22:17:47,900 [ERROR] main: Unhandled exception",
    "  + Exception Group Traceback (most recent call last):",
    '  |   File "/app/main.py", line 1, in x',
    "    | Traceback (most recent call last):",
    '    |   File "/app/services/y.py", line 2, in y',
    "    | KeyError: 'z'",
]
RAG_TRACEBACK = [
    "2026-07-27 22:17:51,318 [ERROR] routes.documents: [RAG] "
    "_index_document_chunks failed for doc 0b65",
    "Traceback (most recent call last):",
    '  File "/app/routes/documents.py", line 9, in _index_document_chunks',
    "    raise RuntimeError(\"embed failed\")",
    "RuntimeError: embed failed",
]


def _scan(lines):
    return scan_lines(iter(lines))


def test_clean_log_yields_no_findings():
    findings, suppressed = _scan([ACCESS_200, ANSI_LINE, "INFO:     Application startup complete."])
    assert findings == []
    assert suppressed == 0


def test_access_log_5xx_is_a_finding_aggregated_by_route():
    findings, _ = _scan([ACCESS_500, ACCESS_200, ACCESS_500])
    assert len(findings) == 1
    (f,) = findings
    assert f.oracle == "logscan"
    assert "500" in f.summary and "/api/graph/rich-user-active/concept-description" in f.summary
    assert f.evidence["count"] == 2


def test_request_logger_5xx_is_a_finding():
    findings, _ = _scan([REQLOG_500])
    assert len(findings) == 1
    assert "/api/quiz/start" in findings[0].summary


def test_ansi_wrapped_5xx_still_detected():
    findings, _ = _scan(["\x1b[31m" + ACCESS_500 + "\x1b[0m"])
    assert len(findings) == 1


def test_plain_traceback_is_a_finding_keyed_by_exception_line():
    findings, _ = _scan(PLAIN_TRACEBACK)
    assert len(findings) == 1
    assert "ValueError: boom" in findings[0].summary


def test_exception_group_traceback_is_a_finding():
    findings, _ = _scan(GROUP_TRACEBACK)
    assert len(findings) == 1
    assert "KeyError" in findings[0].summary


def test_repeated_identical_tracebacks_aggregate():
    findings, _ = _scan(PLAIN_TRACEBACK + [ACCESS_200] + PLAIN_TRACEBACK)
    assert len(findings) == 1
    assert findings[0].evidence["count"] == 2


def test_rag_index_traceback_is_suppressed_not_reported():
    findings, suppressed = _scan(RAG_TRACEBACK)
    assert findings == []
    assert suppressed == 1


def test_4xx_and_startup_noise_are_not_findings():
    findings, _ = _scan(
        [
            'INFO:     127.0.0.1:1 - "GET /api/nope HTTP/1.1" 404 Not Found',
            "2026-07-27 22:17:08,060 [INFO] httpx: HTTP Request: POST "
            'http://127.0.0.1:54321/storage/v1/bucket "HTTP/1.1 400 Bad Request"',
        ]
    )
    assert findings == []


def test_render_text_and_json_roundtrip():
    findings, suppressed = _scan([ACCESS_500])
    text = render_text(findings, suppressed)
    assert "1 finding" in text
    import json

    payload = json.loads(render_json(findings, suppressed))
    assert payload["count"] == 1
    assert payload["findings"][0]["oracle"] == "logscan"
