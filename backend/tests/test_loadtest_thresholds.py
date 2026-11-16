"""loadtest/check_thresholds.py: the nightly load test's pass/fail (#117).

Hermetic: fixture CSVs in locust's `*_stats.csv` shape, no locust, no target.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "loadtest" / "check_thresholds.py"
_spec = importlib.util.spec_from_file_location("check_thresholds", _PATH)
ct = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("check_thresholds", ct)  # dataclasses look their module up
_spec.loader.exec_module(ct)

_HEADER = ('"Type","Name","Request Count","Failure Count","Median Response Time",'
           '"Average Response Time","Min Response Time","Max Response Time",'
           '"Average Content Size","Requests/s","Failures/s","50%","66%","75%","80%",'
           '"90%","95%","98%","99%","99.9%","99.99%","100%"')


def _line(type_, name, count, fails, p95):
    return (f'"{type_}","{name}",{count},{fails},10,12,1,900,100,5.0,0.0,'
            f'10,12,14,15,20,{p95},300,400,500,600,900')


def _csv(tmp_path, *lines):
    path = tmp_path / "run_stats.csv"
    path.write_text("\n".join([_HEADER, *lines]) + "\n")
    return str(path)


def _good(tmp_path, **over):
    rows = {
        "health": _line("GET", "GET /api/health", 400, 0, 40),
        "flags": _line("GET", "GET /api/flags", 800, 0, 120),
        "quiz": _line("GET", "GET /api/quiz/attempts", 800, 0, 250),
        "setup": _line("POST", "auth test-login", 20, 0, 900),
        "start": _line("POST", "learn start-session", 20, 0, 4000),
        "connect": _line("POST", "POST /api/learn/chat/stream (connect)", 200, 0, 2500),
        "ttft": _line("SSE", "chat_stream TTFT", 200, 0, 2200),
        "full": _line("SSE", "chat_stream full", 200, 0, 9000),
        "agg": _line("", "Aggregated", 2440, 0, 3000),
    }
    rows.update(over)
    return _csv(tmp_path, *[v for v in rows.values() if v])


def test_a_run_inside_every_target_passes(tmp_path, capsys):
    assert ct.main([_good(tmp_path), "--require-chat"]) == 0
    out = capsys.readouterr().out
    assert "all thresholds met" in out and "GET /api/quiz/attempts" in out


def test_the_llm_and_setup_rows_are_not_held_to_the_300ms_target(tmp_path):
    # start-session (4 s), the stream connect and the full turn are LLM-bound.
    failures, _ = ct.evaluate(ct.load_stats(_good(tmp_path)), require_chat=True)
    assert failures == []


def test_a_slow_non_llm_route_fails(tmp_path, capsys):
    path = _good(tmp_path, quiz=_line("GET", "GET /api/quiz/attempts", 800, 0, 300))
    assert ct.main([path]) == 1  # 300 is not UNDER 300
    assert "GET /api/quiz/attempts: p95 300.0 ms" in capsys.readouterr().err


def test_a_slow_ttft_fails(tmp_path):
    path = _good(tmp_path, ttft=_line("SSE", "chat_stream TTFT", 200, 0, 3100))
    failures, _ = ct.evaluate(ct.load_stats(path))
    assert any("chat_stream TTFT" in f for f in failures)


def test_missing_chat_samples_fail_only_when_chat_was_required(tmp_path):
    path = _good(tmp_path, ttft=None, full=None, connect=None, start=None)
    assert ct.main([path]) == 0
    assert ct.main([path, "--require-chat"]) == 1


def test_a_failing_route_fails_the_run_even_when_fast(tmp_path):
    path = _good(tmp_path, flags=_line("GET", "GET /api/flags", 800, 400, 5))
    failures, _ = ct.evaluate(ct.load_stats(path))
    assert any("400/800 requests failed" in f for f in failures)


def test_a_run_with_no_reads_fails(tmp_path):
    path = _csv(tmp_path, _line("", "Aggregated", 0, 0, 0))
    failures, _ = ct.evaluate(ct.load_stats(path))
    assert failures and "no non-LLM requests" in failures[0]


@pytest.mark.parametrize("value", ["N/A", ""])
def test_an_unreadable_p95_fails_rather_than_passing(tmp_path, value):
    path = _good(tmp_path, health=_line("GET", "GET /api/health", 10, 0, value))
    failures, _ = ct.evaluate(ct.load_stats(path))
    assert any("GET /api/health" in f for f in failures)


def test_thresholds_are_overridable(tmp_path):
    path = _good(tmp_path)
    assert ct.main([path, "--max-p95-ms", "100"]) == 1
    assert ct.main([path, "--max-ttft-p95-ms", "2000", "--require-chat"]) == 1


def test_an_unreadable_file_is_exit_2(tmp_path):
    assert ct.main([str(tmp_path / "missing.csv")]) == 2
