"""Backend-log scanner for the #400 E2E Chapter 2 oracle module.

Scans `.e2e/backend.log` (uvicorn's combined stdout+stderr) for two signal
shapes: 5xx responses (uvicorn access log or the app's ADR-0009 request
logger) and tracebacks (plain, uvicorn ASGI, or ExceptionGroup/TaskGroup
form). Identical signals are aggregated by key so a flaky retry loop
produces one Finding, not a thousand. Pure stdlib, streaming — never
slurps the whole file.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from pathlib import Path

from e2e_oracles.findings import Finding

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Uvicorn access log: 'INFO:     1.2.3.4:5 - "POST /path HTTP/1.1" 500 ...'
ACCESS_RE = re.compile(r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[^"]*" (?P<status>5\d\d)')

# App request logger (ADR 0009): '... [ERROR] sapling.request: [<id>] GET /path -> 500 (23.0ms)'
REQLOG_RE = re.compile(r"\] (?P<method>[A-Z]+) (?P<path>\S+) -> (?P<status>5\d\d) ")

# Traceback block start.
_PLAIN_TRACEBACK_START_RE = re.compile(r"^[\s|+]*Traceback \(most recent call last\):")
_BLOCK_START_SUBSTRINGS = ("Exception in ASGI application", "Exception Group Traceback")

# A line that unambiguously starts a *new* log record — closes an open block.
NEW_LOG_LINE_RE = re.compile(r"^(INFO|ERROR|WARNING|DEBUG|CRITICAL):|^\d{4}-\d{2}-\d{2} ")

# The line within a traceback block that names the exception, e.g. "ValueError: boom"
# or "    | KeyError: 'z'" (ExceptionGroup gutter prefix).
KEY_RE = re.compile(r"^[\s|+]*\w+(\.\w+)*(Error|Exception|Interrupt|Exit)\b.*")

# #439 by-design noise: RAG indexing failures are retried and logged loudly but
# don't represent a user-facing bug. Suppressed (counted, not reported).
ALLOWLIST = (re.compile(r"\[RAG\] _index_document_chunks failed"),)

_MAX_EXCERPT_LINES = 20
_CONTEXT_LINES = 5


def _clean(raw_line: str) -> str:
    return ANSI_RE.sub("", raw_line).rstrip("\n")


def _is_block_start(line: str) -> bool:
    if _PLAIN_TRACEBACK_START_RE.match(line):
        return True
    return any(sub in line for sub in _BLOCK_START_SUBSTRINGS)


def _block_key(block_lines: list[str]) -> str:
    key = None
    for line in block_lines:
        if KEY_RE.match(line):
            key = line
    if key is None:
        key = block_lines[0] if block_lines else ""
    return key


def _block_summary(key: str, count: int) -> str:
    clean_key = re.sub(r"^[\s|+]*", "", key).strip()
    return f"Traceback: {clean_key} ({count}×)"


def scan_lines(lines: Iterable[str]) -> tuple[list[Finding], int]:
    """Scan an iterable of raw log lines for 5xx responses and tracebacks.

    Returns (findings, suppressed_count). Aggregates repeated identical
    signals (same route+status, or same exception key) into a single
    Finding with a `count` in evidence.
    """
    fivexx: dict[tuple[str, str, str], dict] = {}
    blocks: dict[str, dict] = {}
    suppressed_count = 0
    context: deque[str] = deque(maxlen=_CONTEXT_LINES)

    in_block = False
    block_lines: list[str] = []
    block_start_line_no = 0

    def close_block() -> None:
        nonlocal in_block, block_lines, block_start_line_no, suppressed_count
        if not in_block:
            return
        block_text = "\n".join(block_lines)
        allowlisted = any(rx.search(block_text) for rx in ALLOWLIST) or any(
            rx.search(ctx_line) for ctx_line in context for rx in ALLOWLIST
        )
        if allowlisted:
            suppressed_count += 1
        else:
            key = _block_key(block_lines)
            agg = blocks.setdefault(
                key,
                {"count": 0, "first_line": block_start_line_no, "lines": list(block_lines)},
            )
            agg["count"] += 1
        in_block = False
        block_lines = []

    for line_no, raw_line in enumerate(lines, start=1):
        stripped = _clean(raw_line)

        if in_block:
            if NEW_LOG_LINE_RE.match(stripped):
                close_block()
                # fall through: this line is re-processed normally below —
                # it may itself start the next block.
            else:
                block_lines.append(stripped)
                continue

        if _is_block_start(stripped):
            in_block = True
            block_lines = [stripped]
            block_start_line_no = line_no
            continue

        match = ACCESS_RE.search(stripped) or REQLOG_RE.search(stripped)
        if match:
            key = (match.group("method"), match.group("path"), match.group("status"))
            agg = fivexx.setdefault(key, {"count": 0, "first_line": line_no})
            agg["count"] += 1

        context.append(stripped)

    close_block()

    findings: list[Finding] = []

    for (method, path, status), agg in fivexx.items():
        findings.append(
            Finding(
                oracle="logscan",
                summary=f"{status} on {method} {path} ({agg['count']}×)",
                evidence={"count": agg["count"], "first_line": agg["first_line"]},
            )
        )

    for key, agg in blocks.items():
        findings.append(
            Finding(
                oracle="logscan",
                summary=_block_summary(key, agg["count"]),
                evidence={
                    "count": agg["count"],
                    "first_line": agg["first_line"],
                    "excerpt": agg["lines"][:_MAX_EXCERPT_LINES],
                },
            )
        )

    return findings, suppressed_count


def scan_file(path: str | Path) -> tuple[list[Finding], int]:
    """Stream `path` line-by-line through `scan_lines`. Never slurps the file."""
    with Path(path).open("r", errors="replace") as f:
        return scan_lines(f)
