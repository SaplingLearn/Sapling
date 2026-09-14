# E2E Chapter 2 — Exploratory Testing (epic #403) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Chapter 2 of the Sapling E2E program — a deterministic oracle CLI (#400), a local `make explore` harness that lets a Claude Code explorer drive the real app through Playwright MCP plus an interactive `/explore` skill (#399), and the runbook + promotion pipeline (#401).

**Architecture:** Three PRs, one per issue, in dependency order. PR A adds `backend/e2e_oracles/` — pure judge functions (hermetically tested) behind a `venv/bin/python -m e2e_oracles` CLI that gathers evidence via raw SQL (psycopg, local-only guarded), authed HTTP against the running backend, and a streaming scan of `.e2e/backend.log`. PR B adds `scripts/explore.sh` (lock → `e2e-up` in function mode → mint Playwright storageState via `POST /api/auth/test-login` → `claude -p` with a Playwright MCP config and turn budget → oracle final pass → teardown), the explorer mission prompt, and the `/explore` repo skill. PR C adds the runbook doc. The LLM explores; only oracles or a reproducible captured failure make something a finding. No CI component — local-only by design (#403 decision comment, 2026-07-28).

**Tech Stack:** Python 3 (psycopg, httpx, dotenv — all existing backend deps), bash, Claude Code CLI (`claude -p`), `@playwright/mcp`, pytest (hermetic lane), Make.

## Global Constraints

- **Stack is a machine singleton.** ANY use of the local e2e stack (`make e2e-up`, oracle live runs, `make explore`) must hold `flock` on `/tmp/claude-$(id -u)/sapling-e2e-stack.lock` (uid is 1000 → `/tmp/claude-1000/sapling-e2e-stack.lock`). Fail fast (`flock -n`) with a clear message when busy. Leave the machine as found (stack down, lock released).
- **Deterministic boot env, verbatim:** `SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e GEMINI_API_KEY=e2e-dummy-key-no-billing` — the dummy key is load-bearing (#439: a below-seam RAG path can bill otherwise). `backend/config.py:4` and `main.py:37` use `load_dotenv()` **without** `override`, so exported env beats `backend/.env`.
- **Seeded identity, verbatim:** user `rich-user-active`, display name `Rich Active`; session cookie name `sapling_session`; test-login endpoint `POST /api/auth/test-login` (404 unless `APP_ENV in {local, test}`).
- **Oracle exit codes:** `0` = clean, `1` = findings, `2` = oracle infrastructure error.
- **Local-only guards never skip — they raise.** DB URL and base URL hostnames must be exactly one of `127.0.0.1`, `localhost`, `::1` (mirror `backend/tests/integration/conftest.py:51-84` exact-hostname semantics, not substring).
- **Raw SQL is sanctioned only inside `backend/e2e_oracles/`** (test tooling, like `db/migrate.py` and the integration conftest). SELECT-only — oracles never mutate.
- **Bare `find`/`grep` are shadowed on this machine** — subagents must use Grep/Glob tools or `/usr/bin/grep`.
- **Backend venv lives only at `/home/andresl/Projects/sapling/backend/venv`.** Run pytest/ruff/oracles as `venv/bin/python …` from `backend/`.
- **npm engine-strict pins npm >=10.9 <11** — if system npm trips it, use `npx -y npm@10.9.2 ci`. (No npm installs are planned; frontend is untouched.)
- **Never touch `frontend/middleware.ts`** (Cloudflare edge-only). No frontend source changes in this plan at all.
- **`ruff check .` from `backend/` must stay green** (CI-gated) and the hermetic suite `venv/bin/python -m pytest tests/ -q` must stay green after every task.
- **Work in place on feature branches** (session is configured for in-place work; no worktrees): PR A on `e2e-chapter2-oracles`, PR B on `e2e-chapter2-explore`, PR C on `e2e-chapter2-runbook`, each cut from up-to-date `main` after the previous PR merges.
- **Every merge is gated by `/code-review` on the PR first** (controller runs it; merge only on green).
- **Commit trailer:** `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Known open bugs the oracles may re-confirm but tasks must NOT fix: #355 (dup subject root), #430, #435, #436, #439 (RAG noise — allowlisted in logscan), #441.

## Controller notes (not for implementers)

- PR bodies: PR A `Closes #400`, PR B `Closes #399`, PR C `Closes #401`, each ending with the 🤖 Generated-with line. After PR C merges, close epic #403 with a summary comment.
- Task 4 and Task 8 use the live stack: their implementers must take the flock and tear down afterward. Nothing else in this plan touches the stack.
- The reference map of Chapter 1 internals gathered on 2026-07-27 (storage-state shape, log formats, seed inventory) is folded into task briefs below — briefs are self-contained.

---

## PR A — `backend/e2e_oracles/` (#400), branch `e2e-chapter2-oracles`

### Task 1: Findings record + backend-log scanner (pure, hermetic)

**Files:**
- Create: `backend/e2e_oracles/__init__.py`
- Create: `backend/e2e_oracles/findings.py`
- Create: `backend/e2e_oracles/logscan.py`
- Test: `backend/tests/test_e2e_oracles_logscan.py`

**Interfaces:**
- Consumes: nothing (pure stdlib: `dataclasses`, `re`, `json`, `collections`).
- Produces: `Finding(oracle: str, summary: str, evidence: dict)` dataclass; `render_text(findings, suppressed=0) -> str`; `render_json(findings, suppressed=0) -> str`; `scan_lines(lines: Iterable[str]) -> tuple[list[Finding], int]` (findings, suppressed_count); `scan_file(path: str | Path) -> tuple[list[Finding], int]` (streams — the live log is 16 MB / 108k lines, never slurp).

`.e2e/backend.log` is uvicorn's combined stdout+stderr. Four interleaved line formats the scanner must handle (samples verbatim from a live log):

1. Uvicorn access log — the reliable status line:
   `INFO:     127.0.0.1:53354 - "POST /api/graph/rich-user-active/concept-description HTTP/1.1" 500 Internal Server Error`
2. Python logging: `2026-07-27 22:17:08,060 [INFO] httpx: HTTP Request: POST http://127.0.0.1:54321/storage/v1/bucket "HTTP/1.1 400 Bad Request"`
3. App request logger (ADR 0009): `2026-07-27 22:17:25,882 [INFO] sapling.request: [55bf1ed0-a791-4beb-ab1a-5e3c06cb78ef] GET /api/auth/me -> 200 (23.0ms)`
4. ANSI-colored pre-request lines: `\x1b[32m22:17:08.488\x1b[0m GET /api/health` — strip `\x1b\[[0-9;]*m` before matching.

Traceback shapes to recognize: bare `Traceback (most recent call last):` at column 0; uvicorn's `ERROR:    Exception in ASGI application`; ExceptionGroup/TaskGroup form with `+`/`|` gutters (`  + Exception Group Traceback (most recent call last):`, nested `    | Traceback …`). Allowlist (#439 by-design noise): any traceback whose block or preceding 5 lines match `\[RAG\] _index_document_chunks failed` is **suppressed** (counted in `suppressed`, not a finding).

- [ ] **Step 1: Write the failing tests**

```python
"""Hermetic tests for the #400 backend-log scanner. No stack, no DB."""

from e2e_oracles.findings import Finding, render_json, render_text
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/`: `venv/bin/python -m pytest tests/test_e2e_oracles_logscan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'e2e_oracles'`.

- [ ] **Step 3: Implement `findings.py` and `logscan.py`**

`findings.py`:

```python
"""Finding record + rendering shared by every #400 oracle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Finding:
    oracle: str  # "graph" | "counts" | "ciphertext" | "logscan" | "orphans" | "oracle-error"
    summary: str
    evidence: dict = field(default_factory=dict)


def render_text(findings: list[Finding], suppressed: int = 0) -> str:
    lines = [f"{len(findings)} finding(s), {suppressed} suppressed (allowlisted)."]
    for f in findings:
        lines.append(f"[{f.oracle}] {f.summary}")
        for k, v in f.evidence.items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def render_json(findings: list[Finding], suppressed: int = 0) -> str:
    return json.dumps(
        {"count": len(findings), "suppressed": suppressed, "findings": [asdict(f) for f in findings]},
        indent=2,
        default=str,
    )
```

`logscan.py` — implementation constraints:
- Regexes: `ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")`; access `r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[^"]*" (?P<status>5\d\d)'`; reqlog `r"\] (?P<method>[A-Z]+) (?P<path>\S+) -> (?P<status>5\d\d) "`.
- Traceback block start: stripped line matches `r"^[\s|+]*Traceback \(most recent call last\):"` or contains `Exception in ASGI application` or `Exception Group Traceback`. Once in a block, keep consuming lines until one matches a "new log line" pattern (`r"^(INFO|ERROR|WARNING|DEBUG|CRITICAL):"` or `r"^\d{4}-\d{2}-\d{2} "`) — that line is re-processed normally (it may itself start the next block, as in `GROUP_TRACEBACK` where the `[ERROR] main:` line precedes the block; handle by treating start-pattern detection before block-exit reprocessing).
- The block's key = the last line in the block matching `r"^[\s|+]*\w+(\.\w+)*(Error|Exception|Interrupt|Exit)\b.*"` (fallback: first line of the block). Aggregate by key with `count` and `first_line` (line number) in evidence; include up to the first 20 block lines as `excerpt`.
- Keep a `collections.deque(maxlen=5)` of preceding stripped lines; a block is suppressed when any allowlist regex (`ALLOWLIST = (re.compile(r"\[RAG\] _index_document_chunks failed"),)`) matches the block text or that context.
- 5xx aggregation: dict keyed `(method, path, status)` → count + first_line; one `Finding` each, summary `f"{status} on {method} {path} ({count}×)"` — the test only requires "500" and the path substring.
- `scan_file` opens with `errors="replace"` and iterates line-by-line.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_e2e_oracles_logscan.py -q` → all PASS. Then the whole hermetic suite: `venv/bin/python -m pytest tests/ -q` → green. Then `ruff check .` → clean.

- [ ] **Step 5: Commit**

```bash
git add backend/e2e_oracles/__init__.py backend/e2e_oracles/findings.py backend/e2e_oracles/logscan.py backend/tests/test_e2e_oracles_logscan.py
git commit -m "feat(e2e-oracles): findings record + backend-log 5xx/traceback scanner (#400)"
```

### Task 2: Pure judges — graph integrity, ciphertext-at-rest, counts, orphans

**Files:**
- Create: `backend/e2e_oracles/judges.py`
- Test: `backend/tests/test_e2e_oracles_judges.py`

**Interfaces:**
- Consumes: `Finding` from `e2e_oracles.findings` (Task 1).
- Produces (all pure — no IO, no service imports at module level):
  - `graph_findings(payload: dict, db_nodes: list[dict], db_edges: list[dict], enrolled_course_ids: set[str]) -> list[Finding]`
  - `ciphertext_findings(table: str, column: str, rows: list[tuple], decrypt_fn) -> list[Finding]` — `rows` are `(pk, value)`; `decrypt_fn` injected so the module stays hermetic.
  - `count_findings(name: str, api_count: int, db_count: int) -> list[Finding]`
  - `orphan_findings(check_name: str, orphan_ids: list) -> list[Finding]`

Domain facts the graph judge encodes (this is the #355 oracle; `frontend/e2e/graph.spec.ts:181-203`'s `test.fixme` is the prototype):
- The API payload (`GET /api/graph/{user_id}`, built at `backend/services/graph_service.py:144-275`) is `{"nodes": [...], "edges": [...], "stats": {...}}`. Synthesized subject roots have `id == f"subject_root__{course_id}"`; spokes have `id == f"subject_edge__subject_root__{course_id}__{node_id}"`.
- Correct expectations: `expected_node_count = len(db_nodes) + len(enrolled_course_ids)` (one subject root per **distinct** enrolled course — bug #355 makes the service emit one per *enrollment*); drawable edges = db edges whose `source_node_id` **and** `target_node_id` are both in the db node-id set; spokes = number of db_nodes whose `course_id` ∈ `enrolled_course_ids`; `expected_edge_count = drawable + spokes`.
- Findings to emit: duplicate payload node ids; duplicate payload edge ids; node-count mismatch; edge-count mismatch; and per enrolled course, `subject_root__{course_id}` appearing ≠ 1 time.
- Seeded arithmetic to use in tests: 13 nodes, 7 edges (all drawable), 4 distinct enrolled courses (CS101/MATH210/BIO110/ENG150; ENG150 has zero nodes but still gets a root) → 17 nodes / 20 edges correct; live bug #355 shows `nodes_total=18 dup_node_ids=["subject_root__rich-course-cs101"] edges_total=25`.

Ciphertext judge semantics (`backend/services/encryption.py`: AES-256-GCM, on-disk = `base64(nonce || ciphertext_with_tag)`, **no prefix/sentinel**, fresh nonce each write so ciphertext is non-deterministic): a value is "encrypted at rest" iff `decrypt_fn(value)` succeeds AND the plaintext differs from the raw value. Plaintext that happens to be base64 still fails GCM auth → correctly flagged. Non-`str` values (e.g. a jsonb object) are findings too. Evidence must truncate the raw value to 32 chars (never leak full possibly-plaintext content into reports).

- [ ] **Step 1: Write the failing tests**

```python
"""Hermetic tests for the #400 pure judges."""

from e2e_oracles.judges import (
    ciphertext_findings,
    count_findings,
    graph_findings,
    orphan_findings,
)

COURSES = {"c-cs", "c-math"}
DB_NODES = [
    {"id": "n1", "course_id": "c-cs"},
    {"id": "n2", "course_id": "c-cs"},
    {"id": "n3", "course_id": "c-math"},
]
DB_EDGES = [
    {"source_node_id": "n1", "target_node_id": "n2", "relationship_type": "prerequisite"},
    {"source_node_id": "n1", "target_node_id": "ghost", "relationship_type": "related"},
]


def _correct_payload():
    nodes = [{"id": n["id"]} for n in DB_NODES]
    nodes += [{"id": "subject_root__c-cs"}, {"id": "subject_root__c-math"}]
    edges = [{"id": "e1"}]  # the one drawable db edge (n1->n2)
    edges += [
        {"id": "subject_edge__subject_root__c-cs__n1"},
        {"id": "subject_edge__subject_root__c-cs__n2"},
        {"id": "subject_edge__subject_root__c-math__n3"},
    ]
    return {"nodes": nodes, "edges": edges, "stats": {}}


def test_correct_payload_yields_no_findings():
    assert graph_findings(_correct_payload(), DB_NODES, DB_EDGES, COURSES) == []


def test_355_shape_duplicate_root_and_spokes_all_reported():
    p = _correct_payload()
    p["nodes"].append({"id": "subject_root__c-cs"})  # dup hub
    p["edges"] += [
        {"id": "subject_edge__subject_root__c-cs__n1"},
        {"id": "subject_edge__subject_root__c-cs__n2"},
    ]
    fs = graph_findings(p, DB_NODES, DB_EDGES, COURSES)
    summaries = " | ".join(f.summary for f in fs)
    assert "subject_root__c-cs" in summaries          # dup id named
    assert any("node count" in f.summary.lower() for f in fs)
    assert any("edge count" in f.summary.lower() for f in fs)
    assert all(f.oracle == "graph" for f in fs)


def test_missing_subject_root_reported():
    p = _correct_payload()
    p["nodes"] = [n for n in p["nodes"] if n["id"] != "subject_root__c-math"]
    fs = graph_findings(p, DB_NODES, DB_EDGES, COURSES)
    assert any("subject_root__c-math" in f.summary for f in fs)


def test_ciphertext_judge_flags_plaintext_and_passes_real_ciphertext():
    from services.encryption import decrypt, encrypt

    rows = [("row1", encrypt("hello")), ("row2", "just plaintext"), ("row3", {"a": 1})]
    fs = ciphertext_findings("notes", "body", rows, decrypt)
    assert len(fs) == 2
    pks = {f.evidence["pk"] for f in fs}
    assert pks == {"row2", "row3"}
    # Raw value must be truncated in evidence, never full
    assert all(len(str(f.evidence.get("value_prefix", ""))) <= 32 for f in fs)


def test_count_judge():
    assert count_findings("documents", 3, 3) == []
    (f,) = count_findings("documents", 4, 3)
    assert "documents" in f.summary and f.evidence == {"api_count": 4, "db_count": 3}


def test_orphan_judge():
    assert orphan_findings("graph_edges→graph_nodes", []) == []
    (f,) = orphan_findings("graph_edges→graph_nodes", ["e-9"])
    assert "graph_edges" in f.summary and f.evidence["sample_ids"] == ["e-9"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_e2e_oracles_judges.py -q`
Expected: FAIL — `ImportError` (module `e2e_oracles.judges` missing). Note: the ciphertext test imports `services.encryption`, which requires `ENCRYPTION_KEY`; the hermetic conftest provides the test env — if the import fails on a missing key, check how existing hermetic tests (e.g. `tests/` encryption tests) obtain it and follow that pattern rather than inventing a new one.

- [ ] **Step 3: Implement `judges.py`**

Duplicate detection helper: `def _duplicates(ids: list[str]) -> dict[str, int]` via `collections.Counter`, keep entries with count > 1. `graph_findings` computes expectations exactly as specified above; each mismatch is one `Finding(oracle="graph", …)` with the numbers in `evidence` (e.g. `{"payload": 18, "expected": 17, "duplicates": {...}}`). `ciphertext_findings`: for each `(pk, value)` — non-str → finding `f"{table}.{column} non-string value at rest (pk={pk})"`; else `try: plain = decrypt_fn(value)` — exception → finding `f"{table}.{column} not encrypted at rest (pk={pk})"`; success but `plain == value` → same finding. Evidence: `{"pk": pk, "value_prefix": str(value)[:32]}`.

- [ ] **Step 4: Run tests to verify they pass**

`venv/bin/python -m pytest tests/test_e2e_oracles_judges.py tests/test_e2e_oracles_logscan.py -q` → PASS; full hermetic suite green; `ruff check .` clean.

- [ ] **Step 5: Commit**

```bash
git add backend/e2e_oracles/judges.py backend/tests/test_e2e_oracles_judges.py
git commit -m "feat(e2e-oracles): pure judges — graph/#355, ciphertext-at-rest, counts, orphans (#400)"
```

### Task 3: Gatherers + `python -m e2e_oracles` CLI

**Files:**
- Create: `backend/e2e_oracles/gather.py`
- Create: `backend/e2e_oracles/__main__.py`
- Test: `backend/tests/test_e2e_oracles_cli.py`

**Interfaces:**
- Consumes: Tasks 1–2 (`Finding`, `render_*`, `scan_file`, all judges).
- Produces: the CLI contract every later task and the explorer prompt rely on, verbatim:
  - Invocation (from `backend/`): `venv/bin/python -m e2e_oracles [--json] [--check NAME]... [--user ID] [--base-url URL] [--log PATH]`
  - Check names: `graph`, `counts`, `ciphertext`, `logscan`, `orphans` (default: all five).
  - Defaults: `--user rich-user-active`, `--base-url http://localhost:5000`, `--log <repo-root>/.e2e/backend.log` (derive repo root as `Path(__file__).resolve().parents[2]`).
  - Exit codes: 0 clean / 1 findings / 2 infra error (a check raising becomes a `Finding(oracle="oracle-error", …)` and forces exit 2).
  - `main(argv: list[str] | None = None) -> int` so tests call it in-process.

**Structure for testability:** `__main__.py` holds a registry `CHECKS: dict[str, Callable[[argparse.Namespace], tuple[list[Finding], int]]]` (finding-list, suppressed-count) mapping names to thin wrappers in `gather.py`; tests monkeypatch registry entries with fakes — no DB or HTTP in the hermetic tests.

`gather.py` implementation requirements:
- `load_dotenv(Path(__file__).resolve().parents[1] / ".env")` at the top of `main()` in `__main__.py` **before** importing `gather` (which imports `services.*` lazily inside functions — mirror `backend/tests/integration/conftest.py` which defers service imports until after env is loaded).
- Local-only guards, copied semantics from `tests/integration/conftest.py:48-84`: `_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})`; parse with `urllib.parse.urlparse`; exact hostname membership; on failure `raise RuntimeError` naming the offending URL. Guard **both** `SUPABASE_DB_URL` (before any psycopg connect) and `--base-url` (before any HTTP call).
- DB: `psycopg.connect(url, autocommit=True, row_factory=dict_row)` — one connection per CLI run, passed into check wrappers.
- HTTP auth: `from services.session_tokens import mint_session, SESSION_COOKIE_NAME` (function-local import); `httpx.get(f"{base_url}/api/graph/{user}", cookies={SESSION_COOKIE_NAME: mint_session(user)}, timeout=15.0)`; `raise_for_status()`.
- Check wrappers:
  - `graph`: fetch payload; SQL `SELECT id, course_id FROM graph_nodes WHERE user_id = %s`; `SELECT id, source_node_id, target_node_id, relationship_type FROM graph_edges WHERE user_id = %s`; enrolled distinct courses: `SELECT DISTINCT co.course_id FROM enrollments e JOIN course_offerings co ON co.id = e.offering_id WHERE e.user_id = %s` → `judges.graph_findings`. (Verify column names against `db/seed_local_rich.py` inserts — edges use `source_node_id`/`target_node_id` per lines 325-330; enrollments key `user_id`/`offering_id`; adjust the SQL if the seeder shows otherwise.)
  - `counts`: `GET /api/documents/user/{user}` → `len(body["documents"])` vs `SELECT count(*) FROM documents WHERE user_id = %s AND deleted_at IS NULL` (the route filters `deleted_at: is.null` — `routes/documents.py:370-385`); same pattern for `GET /api/notes?user_id=…` vs the `notes` table **only if** the notes list route exists with a comparable shape — check `backend/routes/notes.py:32`; if its list contract doesn't expose a plain per-user list, ship documents-only and say so in the module docstring.
  - `ciphertext`: manifest of `(table, pk_col, column)` — `users/id/email`; `user_profiles/user_id/name`, `first_name`, `last_name`; `messages/id/content`; `room_messages/id/text`; `sessions/id/summary_json`; `documents/id/summary`, `concept_notes`, `extracted_text`; `notes/id/title`, `body`, `last_summary`; `assignments/id/notes`, `points_possible`, `points_earned`. For each: `SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL LIMIT 50` → `judges.ciphertext_findings(table, column, rows, services.encryption.decrypt)`. (Table/column identifiers come only from this hardcoded manifest — no user input reaches SQL text; row params go through `%s`.)
  - `logscan`: `scan_file(args.log)`; a missing log file is an `oracle-error` finding (the stack probably isn't up).
  - `orphans`: LEFT-JOIN SELECTs returning orphan ids, `LIMIT 20` each, through `judges.orphan_findings`: `graph_edges` with either endpoint missing from `graph_nodes`; `node_mastery_events.node_id` missing from `graph_nodes`; `messages.session_id` missing from `sessions`; `enrollments.offering_id` missing from `course_offerings`; `documents.user_id` missing from `users`; `room_messages.room_id` missing from `rooms`. Verify each table/column name against `db/seed_local_rich.py` (its `_SUMMARY_ORDER` lists all 21 seeded tables) and `db/migrations/`; drop or rename a check only if the schema genuinely differs, noting it in the module docstring.

- [ ] **Step 1: Write the failing tests**

```python
"""Hermetic tests for the #400 CLI: registry wiring, guards, exit codes."""

import pytest

from e2e_oracles import __main__ as cli
from e2e_oracles.findings import Finding
from e2e_oracles.gather import require_local


def test_require_local_accepts_loopback_hosts():
    require_local("postgresql://postgres:postgres@127.0.0.1:54322/postgres", "db")
    require_local("http://localhost:5000", "base-url")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.abcdef.supabase.co:5432/postgres",
        "postgresql://u:p@127.0.0.1.evil.com/postgres",
        "http://sapling.example.com",
    ],
)
def test_require_local_rejects_non_loopback(url):
    with pytest.raises(RuntimeError):
        require_local(url, "db")


def _fake_check(findings, suppressed=0):
    def run(args):
        return findings, suppressed

    return run


def test_exit_zero_when_all_checks_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli, "CHECKS", {"logscan": _fake_check([])})
    assert cli.main(["--check", "logscan"]) == 0
    assert "0 finding" in capsys.readouterr().out


def test_exit_one_with_findings_and_json_output(monkeypatch, capsys):
    f = Finding(oracle="graph", summary="node count 18 != 17", evidence={"payload": 18})
    monkeypatch.setattr(cli, "CHECKS", {"graph": _fake_check([f])})
    assert cli.main(["--check", "graph", "--json"]) == 1
    import json

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["findings"][0]["summary"].startswith("node count")


def test_exit_two_when_a_check_raises(monkeypatch, capsys):
    def boom(args):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(cli, "CHECKS", {"orphans": boom})
    assert cli.main(["--check", "orphans"]) == 2
    assert "oracle-error" in capsys.readouterr().out


def test_unknown_check_name_rejected():
    with pytest.raises(SystemExit):
        cli.main(["--check", "nope"])
```

- [ ] **Step 2: Run tests to verify they fail**

`venv/bin/python -m pytest tests/test_e2e_oracles_cli.py -q` → FAIL (`gather`/`__main__` missing).

- [ ] **Step 3: Implement `gather.py` and `__main__.py`**

`main()` shape: parse args (`--check` uses `choices=sorted(CHECKS)` + `action="append"`); `load_dotenv` (no override); iterate selected checks inside `try/except Exception` — exceptions append `Finding(oracle="oracle-error", summary=f"{name} crashed: {exc}")` and set the infra-error flag; sum suppressed counts; print `render_json` when `--json` else `render_text`; return 2/1/0. `if __name__ == "__main__": raise SystemExit(main())`. Checks that need the DB open one shared psycopg connection lazily (first DB check opens it; closed in `finally`). Keep `CHECKS` values thin lambdas over `gather.run_<name>(args)` so monkeypatching the dict is enough for tests.

- [ ] **Step 4: Run tests, suite, lint**

`venv/bin/python -m pytest tests/test_e2e_oracles_cli.py -q` → PASS; `venv/bin/python -m pytest tests/ -q` green; `ruff check .` clean.

- [ ] **Step 5: Commit**

```bash
git add backend/e2e_oracles/gather.py backend/e2e_oracles/__main__.py backend/tests/test_e2e_oracles_cli.py
git commit -m "feat(e2e-oracles): gatherers + python -m e2e_oracles CLI (#400)"
```

### Task 4: Live verification of the oracle CLI against the real stack

**Files:**
- Modify (only if the live run exposes bugs): any `backend/e2e_oracles/*.py`
- No new tests required beyond keeping Tasks 1–3 green; this task's deliverable is **evidence**.

**Interfaces:**
- Consumes: the full CLI from Task 3; the running Chapter 1 stack.
- Produces: a verified CLI whose live behavior is recorded in the task report (exact commands + output).

This task uses the machine-singleton stack. Take the lock first; tear everything down and release it even on failure.

- [ ] **Step 1: Acquire the stack lock**

```bash
mkdir -p "/tmp/claude-$(id -u)"
exec 9>"/tmp/claude-$(id -u)/sapling-e2e-stack.lock"
flock -n 9 || { echo "stack busy — abort and report BLOCKED"; exit 1; }
```

(Keep fd 9 open in the shell session that runs the stack; if the harness forces separate Bash calls, run the whole stack window inside one `flock -n <lockfile> bash -c '…'` wrapper per step instead.)

- [ ] **Step 2: Boot the deterministic stack**

```bash
cd /home/andresl/Projects/sapling
SAPLING_MODEL_MODE=function \
SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e \
GEMINI_API_KEY=e2e-dummy-key-no-billing \
make e2e-up
```

Expected: 4 health checks pass (Postgres, PostgREST, backend :5000, frontend :3000). This can take several minutes (test-profile Next build) — use a background Bash call and poll, don't let a 2-minute default timeout kill it.

- [ ] **Step 3: Run the oracle CLI and validate live behavior**

```bash
cd backend
venv/bin/python -m e2e_oracles; echo "exit=$?"
venv/bin/python -m e2e_oracles --json > /tmp/oracle-live.json; echo "exit=$?"
venv/bin/python -m e2e_oracles --check ciphertext; echo "exit=$?"
venv/bin/python -m e2e_oracles --check orphans; echo "exit=$?"
venv/bin/python -m e2e_oracles --check logscan; echo "exit=$?"
```

Expected (freshly seeded stack):
- Full run exits **1** and the graph oracle reports exactly the #355 signature: duplicate node id `subject_root__rich-course-cs101`, node count 18 ≠ 17, edge count 25 ≠ 20 (5 duplicate spokes). If it does NOT, the judge or the SQL is wrong — debug against `frontend/e2e/graph.spec.ts`'s expectation math before touching expectations.
- `--json` output parses (`python3 -c "import json,sys; json.load(open('/tmp/oracle-live.json'))"`).
- `--check ciphertext` exits **0** (the rich seed encrypts everything it should).
- `--check orphans` exits **0**.
- `--check logscan` exits 0 or 1 depending on boot noise — whatever it reports must be real log content, not parser artifacts (spot-check any finding against the raw log; `/usr/bin/grep -n` the reported route in `.e2e/backend.log`).

- [ ] **Step 4: Fix anything the live run exposed, re-run hermetic tests**

Any fix follows red→green if it's behavior (extend the relevant hermetic test with the real-world line/shape that broke, then fix). `venv/bin/python -m pytest tests/ -q` and `ruff check .` green.

- [ ] **Step 5: Tear down, release, commit**

```bash
cd /home/andresl/Projects/sapling && make e2e-down
exec 9>&-   # release lock
git add -A backend/e2e_oracles backend/tests
git commit -m "test(e2e-oracles): live-verified against the seeded stack — #355 signature reproduced (#400)"
```

(If nothing needed fixing, commit only if there are changes; the report still records the evidence.)

**Controller then:** push `e2e-chapter2-oracles`, open PR A (`Closes #400`), run `/code-review`, merge on green.

---

## PR B — explore harness (#399), branch `e2e-chapter2-explore` (cut from post-A `main`)

### Task 5: `scripts/explore.sh` + `make explore` + `.gitignore`

**Files:**
- Create: `scripts/explore.sh` (executable, `chmod +x`)
- Modify: `Makefile` (root — currently only `e2e-up`/`e2e-down`)
- Modify: `.gitignore` (add `.explore/` beside the existing `.e2e/` block at lines 72-73)

**Interfaces:**
- Consumes: `scripts/e2e-up.sh` / `scripts/e2e-down.sh` (Chapter 1 boot), `POST /api/auth/test-login`, `venv/bin/python -m e2e_oracles` (Task 3 CLI, verbatim contract), `scripts/explore/explorer-prompt.md` (Task 6 — path is referenced here, file lands next task; full-pipeline testing waits for Task 8).
- Produces: `scripts/explore.sh [up|down]` (no arg = full pipeline) and env knobs `EXPLORE_MAX_TURNS` (default 40), `EXPLORE_MODEL` (default `sonnet`), `EXPLORE_HEADED` (default 0), `EXPLORE_USER` (default `rich-user-active`). Outputs land in `.explore/`: `storageState.json`, `mcp.json`, `session.log`, `findings.md`, `oracle-final.{txt,json}`, `traces/`.

Behavior spec:

1. **Lock (both modes).** The flock must survive the `up` process so `up`/`down` can be separate invocations (the interactive `/explore` flow). Use a detached lock-holder:

```bash
LOCK_FILE="/tmp/claude-$(id -u)/sapling-e2e-stack.lock"
start_lock_holder() {
  mkdir -p "$(dirname "$LOCK_FILE")" "$EXPLORE_DIR"
  rm -f "$EXPLORE_DIR/lock.ok"
  setsid bash -c "
    exec 9>\"$LOCK_FILE\"
    flock -n 9 || exit 42
    touch \"$EXPLORE_DIR/lock.ok\"
    exec sleep infinity
  " &
  echo $! > "$EXPLORE_DIR/lock.pid"
  for _ in $(seq 1 20); do
    [ -f "$EXPLORE_DIR/lock.ok" ] && return 0
    kill -0 "$(cat "$EXPLORE_DIR/lock.pid")" 2>/dev/null || break
    sleep 0.1
  done
  die "e2e stack lock busy ($LOCK_FILE) — another session is using the stack"
}
stop_lock_holder() {
  [ -f "$EXPLORE_DIR/lock.pid" ] && kill "$(cat "$EXPLORE_DIR/lock.pid")" 2>/dev/null || true
  rm -f "$EXPLORE_DIR/lock.pid" "$EXPLORE_DIR/lock.ok"
}
```

2. **`up`:** preflight (`command -v claude`, `command -v npx`, `command -v curl`); wipe and recreate `.explore/` (previous run's artifacts are the operator's to triage before re-running — the runbook documents this); `start_lock_holder`; export the deterministic boot env verbatim (Global Constraints) and run `scripts/e2e-up.sh`; mint the storage state; write `mcp.json`; print where things are and how to finish (`scripts/explore.sh down`).

3. **Storage-state mint** — POST through the frontend origin (also proves the `/api/:path*` proxy), then build the exact shape `frontend/e2e/global-setup.ts` builds (cookie `sapling_session`, `httpOnly: true`, `secure: true` — Chromium accepts Secure cookies on `http://localhost` — `sameSite: "Lax"`, plus the `sapling_user` localStorage half; **the cookie alone renders an infinite skeleton**, bug #430):

```bash
mint_storage_state() {
  local body
  body="$(curl -fsS -X POST "http://localhost:3000/api/auth/test-login" \
    -H 'Content-Type: application/json' \
    -d "{\"user_id\": \"$EXPLORE_USER\"}")"
  python3 - "$body" "$EXPLORE_USER" > "$EXPLORE_DIR/storageState.json" <<'PY'
import json, sys, time
body = json.loads(sys.argv[1]); user = sys.argv[2]
state = {
    "cookies": [{
        "name": "sapling_session", "value": body["token"],
        "domain": "localhost", "path": "/",
        "expires": time.time() + float(body.get("expires_in") or 3600),
        "httpOnly": True, "secure": True, "sameSite": "Lax",
    }],
    "origins": [{
        "origin": "http://localhost:3000",
        "localStorage": [{
            "name": "sapling_user",
            "value": json.dumps({"id": user, "name": "Rich Active", "avatar": ""}),
        }],
    }],
}
print(json.dumps(state, indent=2))
PY
}
```

4. **`mcp.json`:** pin `@playwright/mcp` to the current published version (check once with `npm view @playwright/mcp version` during implementation and hardcode the pin — determinism beats freshness):

```bash
write_mcp_config() {
  local headless_args='"--headless", '
  [ "${EXPLORE_HEADED:-0}" = "1" ] && headless_args=''
  cat > "$EXPLORE_DIR/mcp.json" <<EOF
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@<PINNED>", ${headless_args}"--browser", "chromium",
               "--storage-state", "$EXPLORE_DIR/storageState.json",
               "--output-dir", "$EXPLORE_DIR/traces", "--save-trace"]
    }
  }
}
EOF
}
```

If `npx -y @playwright/mcp@<PINNED> --help` shows different flag names for storage state / output dir / trace, adapt to what `--help` documents and note it in the script comment — the flags above are the expected ones.

5. **Explorer leg (full mode only):**

```bash
run_explorer() {
  cd "$REPO_ROOT"
  claude -p "$(cat "$REPO_ROOT/scripts/explore/explorer-prompt.md")" \
    --mcp-config "$EXPLORE_DIR/mcp.json" \
    --strict-mcp-config \
    --model "${EXPLORE_MODEL:-sonnet}" \
    --max-turns "${EXPLORE_MAX_TURNS:-40}" \
    --allowedTools "mcp__playwright__*,Read,Write,Edit,Bash(cd backend && venv/bin/python -m e2e_oracles:*)" \
    2>&1 | tee "$EXPLORE_DIR/session.log" || \
    echo "explorer exited nonzero (turn budget or error) — continuing to oracle pass" | tee -a "$EXPLORE_DIR/session.log"
}
```

Verify each flag against `claude --help` during implementation (`-p/--print`, `--mcp-config`, `--strict-mcp-config`, `--model`, `--max-turns`, `--allowedTools`); if the allowedTools wildcard form differs (e.g. server-level `mcp__playwright` vs `mcp__playwright__*`), use what `--help`/docs say and comment it. The explorer must not gain broader Bash than the oracle invocation.

6. **`down`:** oracle final pass → append to findings → tear down → release:

```bash
do_down() {
  (
    cd "$REPO_ROOT/backend"
    venv/bin/python -m e2e_oracles --json > "$EXPLORE_DIR/oracle-final.json" || true
    venv/bin/python -m e2e_oracles > "$EXPLORE_DIR/oracle-final.txt" 2>&1 || true
  )
  [ -f "$EXPLORE_DIR/findings.md" ] || printf '# Exploration findings\n' > "$EXPLORE_DIR/findings.md"
  {
    printf '\n## Oracle final pass (%s)\n\n```\n' "$(date -Iseconds)"
    cat "$EXPLORE_DIR/oracle-final.txt"
    printf '```\n'
  } >> "$EXPLORE_DIR/findings.md"
  "$REPO_ROOT/scripts/e2e-down.sh" || true
  stop_lock_holder
}
```

7. **Full mode:** `up` → `trap 'do_down' EXIT` → `run_explorer` → (trap fires `do_down`). `down` as a subcommand runs `do_down` alone (for the interactive flow or a crashed full run).

8. **Makefile:**

```make
.PHONY: e2e-up e2e-down explore explore-down

explore:
	scripts/explore.sh

explore-down:
	scripts/explore.sh down
```

(Keep the existing `e2e-up`/`e2e-down` lines untouched; extend the header comment with one line pointing at `docs/e2e-exploration.md`.)

9. **`.gitignore`:**

```
# ---- Chapter 2 exploratory runs (scripts/explore.sh, #399) ----
.explore/
```

- [ ] **Step 1: Write the script, Makefile target, gitignore entry** (as specified above — `set -euo pipefail`, `die()` helper printing to stderr and exiting 1, header comment naming #399 and the runbook)
- [ ] **Step 2: Static verification**

```bash
bash -n scripts/explore.sh
command -v shellcheck >/dev/null && shellcheck scripts/explore.sh || echo "shellcheck unavailable — skipped"
scripts/explore.sh bogus-arg 2>&1 | /usr/bin/grep -qi "usage" && echo ok   # unknown arg → usage + exit 1
```

Expected: syntax clean; unknown-arg prints usage. Do NOT run `up`/full here — the live pipeline is Task 8's job (stack singleton + cost).

- [ ] **Step 3: Verify `make explore` wires through**

`make -n explore` prints `scripts/explore.sh`; `git check-ignore .explore/` succeeds after creating the entry (`mkdir -p .explore && git check-ignore -v .explore/`).

- [ ] **Step 4: Commit**

```bash
git add scripts/explore.sh Makefile .gitignore
git commit -m "feat(explore): scripts/explore.sh harness + make explore + .explore gitignore (#399)"
```

### Task 6: Explorer mission prompt

**Files:**
- Create: `scripts/explore/explorer-prompt.md`

**Interfaces:**
- Consumes: the oracle CLI contract (Task 3) and the seeded world facts below.
- Produces: the file `scripts/explore.sh` reads verbatim as the `claude -p` prompt (Task 5 references this exact path), also reused as the mission briefing by the `/explore` skill (Task 7).

Write exactly this content (tuning wording is fine; every section and rule must survive):

````markdown
# Sapling explorer — mission briefing

You are an exploratory tester driving the real Sapling app in a browser at
http://localhost:3000. You are playing **Rich Active**, a junior CS major
(Math minor) at Rich Local University — curious, slightly impatient, the kind
of student who double-clicks buttons and hits Back mid-flow. You are already
signed in (storage state). Today's in-app date is frozen at 2026-03-11.

## Ground rules

- **Report, never fix.** You never edit application code, never run git, never
  touch files outside `.explore/`. Your only writes are `.explore/findings.md`.
- **Stay on http://localhost:3000.** Never navigate elsewhere.
- The app's own AI is deterministic and scripted (function-mode seam): tutor
  replies, quiz questions, and document summaries are fixed fixtures. Do NOT
  report their content as odd — judge the *plumbing* (does the reply render,
  persist, count correctly), not the prose.
- You have a hard turn budget. Spend it wide, not deep: many surfaces beat one
  perfect investigation. Write findings AS YOU GO — the budget may cut you off.

## What to do

1. Wander real student journeys: dashboard → library (upload a small text
   file) → tutor chat (resume "Understanding Recursion") → quiz on a concept →
   knowledge graph (/tree) → study rooms → notes → settings/profile.
2. Try to break things while you go: double-submit forms, rapid repeated
   clicks, browser Back mid-flow, reload during streaming replies, empty and
   enormous inputs, unicode/emoji/`<script>alert(1)</script>` in text fields,
   opening the same page twice.
3. **After each major flow**, run the oracles and read the output:

   ```
   cd backend && venv/bin/python -m e2e_oracles
   ```

   Exit 1 = findings (paste the relevant lines into your findings entry).
   Exit 2 = the oracle itself broke — record that verbatim too.
   Add `--json` when you want to quote structured evidence.
4. Append every finding to `.explore/findings.md` immediately, numbered, in
   the format below.

## What counts as a finding

- An oracle failure (always — paste its output).
- A reproducible UI failure with steps: console errors, stuck skeletons or
  spinners, wrong counts vs what you created, crashed pages, data that
  vanishes after reload, an action that silently does nothing.
- NOT findings: styling opinions, missing features, scripted-model prose,
  slowness on first load (the stack is a local dev build).

## Findings format (append to .explore/findings.md)

```
### F<N>: <one-line title>
- surface: <page or flow>
- steps: <numbered, minimal repro>
- expected: <what should happen>
- actual: <what happened>
- oracle evidence: <pasted lines, or "none — UI-observed">
- severity guess: crash | wrong-data | annoyance
```

## Known open bugs — do not re-report as new (re-confirming with NEW evidence is fine)

- #355 graph duplicates the CS subject-root hub (the oracle will flag this).
- #430 cookie-only session renders an infinite dashboard skeleton.
- #435, #436, #441 — open UI/infra bugs from Chapter 1.
- #439 RAG indexing errors in the backend log are allowlisted noise.

## End of session

Before your last turns, append a `## Session summary` section to
`.explore/findings.md`: surfaces covered, surfaces skipped, which findings
deserve promotion to scripted journeys, and the single best next focus.
````

- [ ] **Step 1: Write the file exactly as specified**
- [ ] **Step 2: Verify it reads cleanly** — `bash -c 'cat scripts/explore/explorer-prompt.md >/dev/null'` and confirm the oracle invocation line matches the Task 3 CLI contract verbatim (`cd backend && venv/bin/python -m e2e_oracles`).
- [ ] **Step 3: Commit**

```bash
git add scripts/explore/explorer-prompt.md
git commit -m "feat(explore): explorer mission prompt — persona, break-things mandate, oracle cadence (#399)"
```

### Task 7: `/explore` repo skill (interactive mode)

**Files:**
- Create: `.claude/skills/explore/SKILL.md` (`.claude/skills/` exists, tracked, currently only `.gitkeep`)

**Interfaces:**
- Consumes: `scripts/explore.sh up|down` (Task 5), `scripts/explore/explorer-prompt.md` (Task 6).
- Produces: the user-invocable `/explore` skill.

Write exactly:

````markdown
---
name: explore
description: Run an interactive Chapter 2 exploratory-testing session of the Sapling app (#399/#403) — boots the deterministic local E2E stack, signs in a real browser as the seeded student, explores the UI for bugs with the e2e oracles as judge, and writes .explore/findings.md. Local-only; needs the stack lock. Use when asked to "explore the app", "run an exploration", or "/explore".
---

# /explore — interactive exploratory testing

You are about to become the explorer yourself, watchably, in this session —
the headless twin of this flow is `make explore`. The operator can steer you
at any point; follow their steering over the default itinerary.

## Steps

1. **Boot.** Run `scripts/explore.sh up` (takes minutes: Supabase, migrations,
   seed, backend, test-profile Next build; it takes the machine-singleton
   stack lock and fails fast if another session holds it — if it does, stop
   and tell the operator). Everything lands in `.explore/`.

2. **Open a browser you can drive.** Use this session's browser tools
   (Playwright MCP if configured, else the Claude-in-Chrome tools) on a NEW
   tab at `http://localhost:3000`.

3. **Sign in as the seeded student.** The storage-state file works only for
   Playwright contexts; in a live browser, mint the session from the page
   itself — run this JavaScript on the localhost:3000 tab, then reload:

   ```js
   await fetch("/api/auth/test-login", {
     method: "POST",
     headers: { "Content-Type": "application/json" },
     credentials: "same-origin",
     body: JSON.stringify({ user_id: "rich-user-active" }),
   });
   localStorage.setItem(
     "sapling_user",
     JSON.stringify({ id: "rich-user-active", name: "Rich Active", avatar: "" })
   );
   location.reload();
   ```

   (Both halves are required — the cookie alone leaves the dashboard on an
   infinite skeleton, bug #430.)

4. **Explore.** Read `scripts/explore/explorer-prompt.md` and follow it as
   your mission briefing: the persona, the break-things mandate, the
   report-never-fix rule, the oracle cadence
   (`cd backend && venv/bin/python -m e2e_oracles` after each major flow),
   and the findings format. Append findings to `.explore/findings.md` as you
   go, and narrate what you're trying so the operator can steer.

5. **Finish.** Run `scripts/explore.sh down` — it runs the oracle final pass,
   appends it to `.explore/findings.md`, tears the stack down, and releases
   the lock. Then summarize the findings for the operator and point them at
   `docs/e2e-exploration.md` for triage/promotion.

## Hard rules

- Never skip step 5, even after errors — the stack and lock must not leak.
- Report, never fix: no app-code edits, no git, no writes outside `.explore/`.
- If the browser tools can't reach localhost:3000, check `.e2e/*.log`, report,
  and tear down — don't debug the stack mid-exploration.
````

- [ ] **Step 1: Write the file exactly as specified**
- [ ] **Step 2: Verify frontmatter parses** — first line `---`, `name: explore`, one-paragraph `description`, closing `---`; no tabs.
- [ ] **Step 3: Commit**

```bash
git add .claude/skills/explore/SKILL.md
git commit -m "feat(explore): /explore repo skill — interactive exploration mode (#399)"
```

### Task 8: Bounded acceptance run of `make explore`

**Files:**
- Modify (only as fixes): `scripts/explore.sh`, `scripts/explore/explorer-prompt.md`

The #399 acceptance criterion, verbatim: "one bounded local exploration completes with a readable transcript and a findings file, driven end-to-end through the real UI." This task runs it for real. Same stack-singleton discipline as Task 4 — but here the lock is taken by `explore.sh` itself; do NOT take it manually first (that would deadlock the harness).

- [ ] **Step 1: Confirm the lock is free, then kick off a bounded run**

```bash
cd /home/andresl/Projects/sapling
EXPLORE_MAX_TURNS=25 make explore
```

Run in a background Bash call with a generous window and poll `.explore/session.log` — the full pipeline (stack boot + explorer + oracle pass + teardown) takes well over any foreground timeout. First run also downloads `@playwright/mcp` via npx.

- [ ] **Step 2: Verify the acceptance artifacts**

```bash
ls -la .explore/
wc -l .explore/session.log .explore/findings.md
/usr/bin/grep -c "mcp__playwright" .explore/session.log   # explorer actually drove the browser
/usr/bin/grep -n "Oracle final pass" .explore/findings.md  # harness appended the final pass
/usr/bin/grep -n "Session summary" .explore/findings.md || echo "explorer ran out of turns before summary — acceptable if findings exist"
ls .explore/traces/ 2>/dev/null || echo "no traces — investigate --save-trace flag support"
```

Pass bar: `session.log` shows real Playwright MCP tool calls across at least 2 app surfaces; `findings.md` exists with the oracle final pass appended (the graph oracle re-confirming #355 counts as a finding — that IS the system working); stack is down afterward (`ss -ltn` shows 3000/5000 free, `podman ps`/`docker ps` shows no supabase containers) and the lock file is unheld (`flock -n /tmp/claude-1000/sapling-e2e-stack.lock true` succeeds).

- [ ] **Step 3: Fix what the real run exposed** (flag-name mismatches, allowedTools syntax, prompt ambiguities that made the explorer stall). Each fix is a normal commit; re-run the bounded pipeline only if the fix invalidates the acceptance evidence (e.g. the explorer never drove the browser). A second full run is acceptable; more than two, stop and report BLOCKED with the logs.
- [ ] **Step 4: Record evidence in the task report** — the exact command, total wall-clock, artifact listing, 10 representative `session.log` lines, the findings.md oracle section, and post-teardown port/lock checks.
- [ ] **Step 5: Commit any fixes**

```bash
git add scripts/explore.sh scripts/explore/explorer-prompt.md
git commit -m "fix(explore): adjustments from first live bounded exploration (#399)"
```

**Controller then:** push `e2e-chapter2-explore`, open PR B (`Closes #399`), `/code-review`, merge on green.

---

## PR C — runbook (#401), branch `e2e-chapter2-runbook` (cut from post-B `main`)

### Task 9: `docs/e2e-exploration.md` + pointer from `docs/local-supabase.md`

**Files:**
- Create: `docs/e2e-exploration.md`
- Modify: `docs/local-supabase.md` (one pointer line in the "One-command E2E stack" section, around line 236)

**Interfaces:**
- Consumes: everything PR A/B shipped (paths and knobs verbatim).
- Produces: the Chapter 2 runbook — the document an operator reads before their first `make explore`.

The runbook must contain these sections with this substance (prose quality is the implementer's; facts are fixed):

1. **What this is** — Chapter 2 vs Chapter 1 in one table: Ch1 = scripted deterministic journeys in `frontend/e2e/`, CI-gated on main; Ch2 = LLM-driven exploration, local-only, never gates. The core rule verbatim from #403: *"The LLM explores; only oracles (or a reproducible captured failure) make something a finding."*
2. **Prerequisites** — Chapter 1 stack prereqs (supabase CLI, rootless Podman or Docker, `backend/venv`, `frontend/node_modules`, `backend/.env` with `APP_ENV=local`) plus `claude` CLI and network for the first `npx @playwright/mcp` download.
3. **Kick-off: headless** — `make explore`; knob table: `EXPLORE_MAX_TURNS` (default 40), `EXPLORE_MODEL` (default sonnet), `EXPLORE_HEADED=1` (watch the browser), `EXPLORE_USER` (default rich-user-active). Note `.explore/` is wiped at `up` — triage before re-running. `make explore-down` recovers a crashed run.
4. **Kick-off: interactive** — `/explore` in a Claude Code session in this repo; what to expect (operator steering, same findings file, same oracles).
5. **Outputs** — `.explore/` inventory: `findings.md`, `session.log`, `oracle-final.{txt,json}`, `traces/`, `storageState.json`/`mcp.json` (plumbing). All gitignored.
6. **The oracles, standalone** — `cd backend && venv/bin/python -m e2e_oracles [--json] [--check graph|counts|ciphertext|logscan|orphans]`; exit codes 0/1/2; needs the stack up; the log scan allowlists #439 RAG noise.
7. **Triage protocol** — for each `findings.md` entry: (a) reproduce it by hand or via the oracle; not reproducible → drop with a note; (b) reproducible + real → `gh issue create` with the finding block, oracle JSON, and trace path attached; label it as coming from exploration; (c) already-known (#355 #430 #435 #436 #439 #441) → add evidence to the existing issue only if new; (d) noise the oracle wrongly flagged → fix the oracle (allowlist entry or judge bug) — that's a normal PR to `backend/e2e_oracles/`.
8. **Promotion pipeline** — the output that counts (epic bar: **≥3 findings promoted into Chapter 1 regressions in the first month**): issue → scripted journey in `frontend/e2e/*.spec.ts` following the existing specs' style (fixtures-based `test`, raw-SQL assertions via `support/db.ts`, testids per `docs/frontend-testids.md` "Adding a surface" — doc row + eslint `files` array; `npm run lint:baseline` only for legacy debt). A promoted journey that must stay red rides `test.fixme` with the bug number, like `graph.spec.ts` does for #355.
9. **Cadence + cost** — suggested: one bounded headless run weekly and after any risky merge; each run costs real Claude tokens (bounded by `EXPLORE_MAX_TURNS`) and ~10 minutes of stack boot.
10. **Lock protocol & hygiene** — the stack is a machine singleton; `explore.sh` holds `flock` on `/tmp/claude-<uid>/sapling-e2e-stack.lock` for the whole session; never run two explorations or an exploration beside the Playwright suite; always end via `down`.
11. **Troubleshooting** — lock busy (who else is using the stack?); test-login 404 (`APP_ENV` not local/test); explorer never drove the browser (check `mcp.json` flags vs `npx @playwright/mcp --help`); oracle exit 2 (stack down or DB URL not local); stale `.explore/` (wiped on next `up`).

`docs/local-supabase.md` pointer line to add inside the "One-command E2E stack" section:

```markdown
Chapter 2 exploratory testing (`make explore`, the `/explore` skill, and the e2e oracles) is documented in [e2e-exploration.md](e2e-exploration.md).
```

- [ ] **Step 1: Write both files as specified**
- [ ] **Step 2: Verify every command/path/knob named in the doc exists** — `scripts/explore.sh`, `make explore`, `make explore-down`, `.claude/skills/explore/SKILL.md`, `backend/e2e_oracles/`, each `--check` name, each `EXPLORE_*` knob (`/usr/bin/grep -o 'EXPLORE_[A-Z_]*' scripts/explore.sh | sort -u` must cover the doc's table).
- [ ] **Step 3: Commit**

```bash
git add docs/e2e-exploration.md docs/local-supabase.md
git commit -m "docs(e2e): Chapter 2 exploration runbook — kick-off, triage, promotion pipeline (#401)"
```

**Controller then:** push `e2e-chapter2-runbook`, open PR C (`Closes #401`), `/code-review`, merge on green; close epic #403 with a summary comment.
