"""Opt-in DBOS crash/resume proof (ADR 0011 / #154).

Skipped by default: needs the real `dbos` package (backend/requirements-
durable.txt, never requirements.txt/requirements.lock) AND a live Postgres
for DBOS's own system database. Run explicitly with:

    RUN_DBOS_RESUME=1 DBOS_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \
        venv/bin/python -m pytest tests/test_dbos_resume.py -q

(defaults to the local Supabase stack's Postgres -- see docs/local-supabase.md
-- but any reachable Postgres works; DBOS provisions its own `dbos` schema in
whatever database the URL points at, alongside Supabase's own schemas).

Both tests use a SUBPROCESS per phase rather than reloading services.durable
in-process. That is not just style: `agents.document` applies
`@durable_workflow` / `@durable_step` to `process_document` / `_step_*` at
IMPORT time (see agents/document.py's docstring), and a pytest session has
almost certainly already imported `agents.document` (transitively, via
`routes.documents` -> `main`, which `test_documents_routes.py` and others
import at collection time) BEFORE this file's tests run -- using whatever
`services.durable.workflow`/`step` looked like at THAT import (passthrough,
since the default test env has DBOS_ENABLED unset). Reloading
`services.durable` later would not retroactively change the ALREADY-BOUND
decorators on `agents.document.process_document`. A fresh subprocess, with
DBOS_ENABLED=true set before the interpreter even starts, is the only way to
get a REAL DBOS-backed `process_document` / minimal workflow to test against.

Helper scripts below are plain `#`-commented (not docstring'd) deliberately:
they are string constants embedded in THIS file, written out verbatim to a
tmp_path file and run by a fresh interpreter -- a triple-quoted docstring
inside a triple-quoted Python string constant is a real nesting headache
(first attempt at this file tripped over exactly that), and a `#` comment
sidesteps it entirely.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_DBOS_RESUME") != "1",
        reason="opt-in: needs dbos + local Postgres (RUN_DBOS_RESUME=1)",
    ),
    pytest.mark.skipif(
        importlib.util.find_spec("dbos") is None,
        reason="dbos not installed (see backend/requirements-durable.txt)",
    ),
]

_DEFAULT_DBOS_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"


def _dbos_database_url() -> str:
    return os.getenv("DBOS_DATABASE_URL") or _DEFAULT_DBOS_DATABASE_URL


def _subprocess_env(**extra: str) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    env["DBOS_ENABLED"] = "true"
    env["DBOS_DATABASE_URL"] = _dbos_database_url()
    env.update(extra)
    return env


def _run_helper(script_path: Path, *args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=str(_BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


# -- 1. Minimal 2-step workflow: crash mid-step-2, resume, assert no re-run --
#
# A 2-step DBOS workflow used to prove OUR shim wires real DBOS crash-resume,
# not just that dbos itself works. Run twice as two SEPARATE processes
# against the same DBOS_DATABASE_URL + workflow id:
#
#   phase crash  -- runs step1 (checkpointed), then step2 marks a marker
#                   file and os._exit(42) BEFORE returning (simulates a
#                   worker crash mid-workflow, leaving the row PENDING).
#   phase resume -- a fresh process; DBOS.launch()'s startup recovery
#                   re-runs ONLY step2 (step1 is already checkpointed
#                   SUCCESS) and waits for completion via
#                   DBOS.retrieve_workflow(...).get_result().

_MINIMAL_WORKFLOW_HELPER = r"""
import asyncio
import os
import sys

import services.durable as durable

phase = sys.argv[1]
workflow_id = sys.argv[2]
step1_counter = sys.argv[3]
step2_counter = sys.argv[4]
marker_path = sys.argv[5]

assert durable.is_durable(), "DBOS_ENABLED=true but the shim did not activate"


@durable.step
async def step1():
    with open(step1_counter, "a") as f:
        print("x", file=f)


@durable.step
async def step2():
    if not os.path.exists(marker_path):
        open(marker_path, "w").close()
        os._exit(42)  # simulate a hard crash mid-workflow, before checkpointing
    with open(step2_counter, "a") as f:
        print("x", file=f)
    return "done"


@durable.workflow
async def minimal_workflow():
    await step1()
    return await step2()


durable.init_dbos()

if phase == "crash":
    from dbos import SetWorkflowID

    with SetWorkflowID(workflow_id):
        asyncio.run(minimal_workflow())
    print("RESULT:unreachable")  # os._exit(42) fires before this
elif phase == "resume":
    from dbos import DBOS

    handle = DBOS.retrieve_workflow(workflow_id)
    result = handle.get_result(polling_interval_sec=0.2)
    print("RESULT:" + str(result))
else:
    raise SystemExit("unknown phase " + repr(phase))
"""


def test_shim_resume_minimal_workflow(tmp_path):
    """Crash mid-workflow, resume in a fresh process, and assert the
    resume-at-last-completed-step contract: step1 (already checkpointed
    before the crash) does NOT re-run, and step2 runs exactly once to
    completion on resume.
    """
    script = tmp_path / "minimal_workflow_helper.py"
    script.write_text(_MINIMAL_WORKFLOW_HELPER)

    workflow_id = "dbos-resume-test-" + str(uuid.uuid4())
    step1_counter = tmp_path / "step1_counter.txt"
    step2_counter = tmp_path / "step2_counter.txt"
    marker = tmp_path / "step2_marker.txt"

    env = _subprocess_env()
    args = (workflow_id, str(step1_counter), str(step2_counter), str(marker))

    crash = _run_helper(script, "crash", *args, env=env)
    assert crash.returncode == 42, (
        "expected the crash phase to os._exit(42); stdout=" + repr(crash.stdout)
        + " stderr=" + repr(crash.stderr)
    )

    resume = _run_helper(script, "resume", *args, env=env)
    assert resume.returncode == 0, (
        "expected the resume phase to complete cleanly; stdout=" + repr(resume.stdout)
        + " stderr=" + repr(resume.stderr)
    )
    assert "RESULT:done" in resume.stdout

    # The resume-at-last-completed-step contract: step1 ran exactly once
    # (during the crash phase) -- DBOS must NOT re-run an already-
    # checkpointed step. step2 also ran exactly once to completion (its
    # first, crashing invocation never returned, so it never appended to
    # the counter file -- only the resumed invocation did).
    assert step1_counter.read_text().splitlines() == ["x"]
    assert step2_counter.read_text().splitlines() == ["x"]


# -- 2. process_document under DBOS produces the same shape as DBOS-off -----
#
# What this proves: `agents.document.process_document`, decorated for REAL
# under DBOS (not passthrough), still returns the exact same deterministic
# function-mode output as the DBOS-off hermetic suite asserts elsewhere
# (tests/test_e2e_function_handlers.py) -- i.e. wrapping it in
# `@durable_workflow`/`@durable_step` changes durability, not behavior.
#
# What this does NOT prove: this stubs `apply_concepts_to_graph` (the one
# real-Supabase side effect inside process_document) rather than running
# against the live local stack + seeded course/user rows -- wiring that
# full stack through a subprocess was disproportionate to what this test is
# for (see the module docstring). The HTTP-route-level, real-DB behavior
# under DBOS-off is already covered by tests/test_documents_routes.py and
# the Chapter 1 Playwright upload journey; this test's job is narrower and
# DBOS-specific: prove the workflow is genuinely DBOS-backed
# (`durable.is_durable()` True in the subprocess) AND its output is
# unchanged.
#
# Env (DBOS_ENABLED, DBOS_DATABASE_URL, SAPLING_MODEL_MODE=function,
# SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e) is set before this
# helper's interpreter starts, so agents.document decorates
# process_document/_step_* as REAL DBOS workflow/steps at import time below.

_PROCESS_DOCUMENT_HELPER = r"""
import asyncio
import json
from unittest.mock import AsyncMock

import services.durable as durable

assert durable.is_durable(), "DBOS_ENABLED=true but the shim did not activate"

import agents.document as document_module
from agents.deps import SaplingDeps

# The only real-Supabase side effect inside process_document -- stubbed so
# this test needs nothing but DBOS's own Postgres (see module comment above).
document_module.apply_concepts_to_graph = AsyncMock(return_value=0)

durable.init_dbos()

deps = SaplingDeps(
    user_id="dbos-resume-test-user",
    course_id="dbos-resume-test-course",
    supabase=None,
    request_id="dbos-resume-test",
)
result = asyncio.run(document_module.process_document(
    "Deterministic fixture text for the DBOS pipeline-parity test.", deps,
))

print("RESULT_JSON:" + json.dumps({
    "category": result.classification.category,
    "abstract": result.summary.abstract,
    "concepts": sorted(c.name for c in result.concepts.concepts),
}))
"""


def test_pipeline_identical_with_dbos_on(tmp_path):
    """process_document, decorated for real under DBOS, returns the same
    classification/summary/concepts shape as the function-mode constants
    (agents/function_handlers_e2e.py) -- the same constants the DBOS-off
    hermetic suite pins. See the section comment above for exactly what
    this does and does not prove.
    """
    from agents.function_handlers_e2e import E2E_DOC_ABSTRACT, E2E_DOC_CATEGORY, E2E_DOC_CONCEPTS

    script = tmp_path / "process_document_helper.py"
    script.write_text(_PROCESS_DOCUMENT_HELPER)

    env = _subprocess_env(
        SAPLING_MODEL_MODE="function",
        SAPLING_FUNCTION_HANDLERS="agents.function_handlers_e2e",
    )
    proc = _run_helper(script, env=env)
    assert proc.returncode == 0, (
        "expected process_document to complete under DBOS; stdout=" + repr(proc.stdout)
        + " stderr=" + repr(proc.stderr)
    )

    [result_line] = [
        line for line in proc.stdout.splitlines() if line.startswith("RESULT_JSON:")
    ]
    payload = json.loads(result_line[len("RESULT_JSON:"):])

    assert payload["category"] == E2E_DOC_CATEGORY
    assert payload["abstract"] == E2E_DOC_ABSTRACT
    assert payload["concepts"] == sorted(name for name, _desc, _imp in E2E_DOC_CONCEPTS)
