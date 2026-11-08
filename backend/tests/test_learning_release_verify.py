"""Release verifier safety and failure semantics; no services/DB/models/network."""

import ast
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
verify = importlib.import_module("learning_release_verify")
SHA = "a" * 40


@pytest.mark.parametrize(
    "origin",
    [
        "http://staging.example",
        "https://user:PRIVATE@staging.example",
        "https://staging.example/path",
        "https://staging.example/?key=PRIVATE",
        "https://staging.example/#PRIVATE",
        "https://staging.example:99999",
        "",
    ],
)
def test_unsafe_origins_fail_before_any_request(origin):
    with pytest.raises(verify.VerificationError):
        verify.validate_origin(origin)


def test_loopback_http_is_explicit_and_redirects_never_follow():
    with pytest.raises(verify.VerificationError):
        verify.validate_origin("http://127.0.0.1:3104")
    assert verify.validate_origin("http://127.0.0.1:3104/", True) == "http://127.0.0.1:3104"
    assert verify._NoRedirect().redirect_request(None) is None


@pytest.mark.parametrize(
    "change",
    [
        {"status": "bad"},
        {"service": "another"},
        {"model_mode": "function"},
        {"commit": "unknown"},
        {"commit": "b" * 7},
        {"commit": "a" * 6},
    ],
)
def test_health_does_not_accept_wrong_host_mode_unknown_or_inadequate_commit(change):
    body = {
        "status": "ok",
        "service": "sapling-backend",
        "model_mode": "real",
        "commit": "a" * 7,
    } | change
    with pytest.raises(verify.VerificationError):
        verify.probe_health(lambda url: (200, body), "https://stage.example", SHA, "real")


def test_health_labels_prefix_as_such_not_full_artifact_identity():
    result = verify.probe_health(
        lambda url: (
            200,
            {
                "status": "ok",
                "service": "sapling-backend",
                "model_mode": "real",
                "commit": "a" * 7,
            },
        ),
        "https://stage.example",
        SHA,
        "real",
    )
    assert result["status"] == "passed" and result["reported_commit"] == "a" * 7
    assert result["full_artifact_identity_verified"] is False


@pytest.mark.parametrize(
    "status,body", [(401, {}), (403, {}), (404, {"detail": "Not Found"}), (200, {"active": False})]
)
def test_unauthenticated_or_missing_route_is_not_kill_switch_proof(status, body):
    with pytest.raises(verify.VerificationError):
        verify.probe_loop(lambda url: (status, body), "https://stage.example", "qa", "disabled")


@pytest.mark.parametrize(
    "expectation,status,body",
    [
        ("disabled", 404, {"detail": "learning loop not enabled"}),
        ("enabled", 200, {"active": True}),
    ],
)
def test_authenticated_expected_loop_state_is_observed_without_creating_a_session(
    expectation, status, body
):
    urls = []

    def fetch(url):
        urls.append(url)
        return status, body

    result = verify.probe_loop(fetch, "https://stage.example", "qa&not-another-user", expectation)
    assert result["status"] == "passed" and result["expected_loop"] == expectation
    assert len(urls) == 1 and "user_id=qa%26not-another-user" in urls[0]
    assert "session_id=00000000-0000-4000-8000-000000000000" in urls[0]


def test_token_file_requires_owner_only_regular_format_and_rejects_symlinks(tmp_path):
    path = tmp_path / "token"
    path.write_text("PRIVATE.signature")
    path.chmod(0o600)
    assert verify.read_session_token(path) == "PRIVATE.signature"
    path.chmod(0o644)
    with pytest.raises(verify.VerificationError):
        verify.read_session_token(path)
    path.chmod(0o600)
    path.write_text("PRIVATE.signature\r\nInjected: header")
    with pytest.raises(verify.VerificationError):
        verify.read_session_token(path)
    link = tmp_path / "symlink"
    link.symlink_to(path)
    with pytest.raises(OSError):
        verify.read_session_token(link)


class Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, parameters=None):
        self.db.statements.append(sql)
        assert sql.startswith(("SHOW ", "SELECT "))
        if sql.startswith("SHOW "):
            self.rows = [(self.db.read_only,)]
        elif "to_regclass" in sql:
            self.rows = [(self.db.ledger,)]
        elif "SELECT filename" in sql:
            self.rows = [(name,) for name in self.db.recorded]
        elif "is_nullable, column_default" in sql:
            assert parameters == (
                sorted({table for table, _column in verify.REQUIRED_COLUMN_ATTRIBUTES}),
            )
            self.rows = self.db.attributes
        elif "information_schema.columns" in sql:
            assert parameters == (list(verify.REQUIRED_COLUMNS),)
            self.rows = self.db.columns
        elif "pg_proc" in sql:
            self.rows = self.db.rpcs
        elif "FROM pg_roles" in sql:
            assert parameters == (sorted(verify.REQUIRED_ROLE_SETTINGS),)
            self.rows = self.db.role_settings
        else:
            raise AssertionError("Unexpected metadata SQL")

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class Database:
    def __init__(self):
        self.read_only = "on"
        self.ledger = True
        self.recorded = {"20261019010000_learning_planning_observation.sql"}
        self.columns = [
            (table, column, kind)
            for table, columns in verify.REQUIRED_COLUMNS.items()
            for column, kind in columns.items()
        ]
        self.attributes = [
            (table, column, *expected)
            for (table, column), expected in verify.REQUIRED_COLUMN_ATTRIBUTES.items()
        ]
        self.rpcs = [("sample", "p_user_id text, p_day date")]
        # spec §13 A136: ALTER ROLE service_role SET extra_float_digits = 3
        self.role_settings = [("service_role", ["statement_timeout=8s", "extra_float_digits=3"])]
        self.statements = []

    def cursor(self):
        return Cursor(self)


def audit(db, reference=None):
    inventory = {"20261019010000_learning_planning_observation.sql": "a" * 64}
    return verify.audit_database(
        db, inventory, {"sample": ["p_user_id text, p_day date"]}, reference
    )


def test_db_audit_checks_read_only_first_and_never_runs_rpc_or_ddl():
    db = Database()
    result = audit(db)
    assert result["status"] == "passed"
    assert db.statements[0] == "SHOW transaction_read_only"
    assert all(sql.startswith(("SHOW ", "SELECT ")) for sql in db.statements)
    assert result["database_function_bodies_constraints_rls_backfill_verified"] is False
    assert result["ledger_content_checksums_available"] is False
    assert result["prior_reference_supplied"] is False


@pytest.mark.parametrize("field,value", [("read_only", "off"), ("ledger", False)])
def test_db_unsafe_or_absent_ledger_fails_before_schema_reads(field, value):
    db = Database()
    setattr(db, field, value)
    with pytest.raises(verify.VerificationError):
        audit(db)
    assert not any("information_schema" in sql for sql in db.statements)


@pytest.mark.parametrize(
    "fault,key",
    [
        ("pending", "pending"),
        ("orphan", "orphans"),
        ("column", "missing_or_wrong_type_columns"),
        ("rpc_type", "missing_rpc_signatures"),
        ("rpc_name", "missing_rpc_signatures"),
    ],
)
def test_schema_missing_column_wrong_rpc_named_argument_or_ledger_drift_fails(fault, key):
    db = Database()
    if fault == "pending":
        db.recorded.clear()
    elif fault == "orphan":
        db.recorded.add("9999_unreviewed.sql")
    elif fault == "column":
        db.columns = [
            row for row in db.columns if row[:2] != ("node_mastery_events", "planning_observation")
        ]
    elif fault == "rpc_type":
        db.rpcs = [("sample", "p_user_id text, p_day text")]
    else:
        db.rpcs = [("sample", "different_name text, p_day date")]
    result = audit(db)
    assert result["status"] == "failed" and result[key]


def test_applied_migration_reference_detects_changed_history_but_is_not_live_schema_checksum():
    db = Database()
    name = next(iter(db.recorded))
    result = audit(db, {name: "b" * 64})
    assert result["status"] == "failed" and result["changed_applied_reference_files"] == [name]
    assert result["ledger_content_checksums_available"] is False


@pytest.mark.parametrize(
    "table,column,wrong_type",
    [
        ("checklist_budget_reservations", "receipt", "text"),
        ("checklist_budget_accounts", "daily_tokens", "integer"),
        ("learning_evidence_operations", "input_fingerprint", "jsonb"),
        ("learner_state", "evidence_version", "integer"),
        ("graph_nodes", "evidence_version", "integer"),
        ("learner_state", "evidence_touch_at", "timestamp without time zone"),
        # the learning-loop wave-2 schema (spec §13 A112, A113, A119)
        ("posttest_poses", "window_days", "bigint"),
        ("check_items", "lint_flags", "text"),
        ("check_item_reviews", "status", None),  # absent: no information_schema row
        ("check_items", "aligned_at", "timestamp without time zone"),
        ("check_items", "key_checked_at", "timestamp without time zone"),
        ("check_item_audits", "verdict", None),  # absent: no information_schema row
        ("learning_evidence_voids", "operation_id", "text"),
        ("check_item_reviews", "approved_at", None),
        ("documents", "check_items_status", None),  # A128, absent
        ("documents", "check_items_at", "timestamp without time zone"),  # A128
        # spec §13 A127: the student's stated confidence on the evidence journal
        ("node_mastery_events", "student_confidence", None),  # absent: not migrated
        ("node_mastery_events", "student_confidence", "real"),
    ],
)
def test_durable_budget_and_evidence_metadata_types_are_required(table, column, wrong_type):
    db = Database()
    db.columns = [
        (name, field, wrong_type if (name, field) == (table, column) else kind)
        for name, field, kind in db.columns
    ]
    result = audit(db)
    assert result["status"] == "failed"
    assert result["missing_or_wrong_type_columns"]


@pytest.mark.parametrize(
    "nullable,default", [("NO", None), ("YES", "now()"), ("YES", "clock_timestamp()")]
)
def test_evidence_touch_fence_is_nullable_and_has_no_synthetic_default(nullable, default):
    db = Database()
    db.attributes = [("learner_state", "evidence_touch_at", nullable, default)]
    result = audit(db)
    assert result["status"] == "failed"
    assert result["missing_or_wrong_column_attributes"]


#: the learning-loop wave-2 and wave-3 migrations that add tables or columns (spec
#: §13 A112, A113, A119, A123, A124, A126, A127, A128; A137). Extend this when a
#: learning migration adds one.
_LEARNING_SCHEMA_MIGRATIONS = (
    "20261108184825_learning_teach_prompts.sql",  # A138, A139
    "20261108163653_learning_llm_usage_course_id.sql",  # A137
    "20261108041639_learning_item_quality.sql",  # A113
    "20261108041742_learning_posttest_windows.sql",  # A112
    "20261108051912_learning_item_alignment.sql",  # A119
    "20261108072715_learning_evidence_void.sql",  # A123
    "20261108073631_learning_item_keys.sql",  # A124
    "20261108091912_learning_document_drafting.sql",  # A128
    "20261108092032_learning_student_confidence.sql",  # A127
    "20261108093359_learning_posttest_outcomes.sql",  # A126
)
#: SQL type -> information_schema.columns.data_type (an array column reads ARRAY)
_DATA_TYPE = {
    "text": "text",
    "timestamptz": "timestamp with time zone",
    "integer": "integer",
    "smallint": "smallint",
    "boolean": "boolean",
    "double precision": "double precision",
    "bigint": "bigint",
    "uuid": "uuid",
    "jsonb": "jsonb",
    "text[]": "ARRAY",
}
_TYPES = "double precision|timestamptz|smallint|integer|bigint|boolean|jsonb|uuid|text"


def _introduced_columns(sql: str) -> set[tuple[str, str, str]]:
    """(table, column, data_type) of every column a migration adds: its
    `ADD COLUMN IF NOT EXISTS` statements and its `CREATE TABLE` columns."""
    import re

    out = set()
    for table, column, kind, array in re.findall(
        rf"ALTER TABLE (?:public\.)?(\w+) ADD COLUMN IF NOT EXISTS (\w+) ({_TYPES})(\[\])?\s*;", sql
    ):
        out.add((table, column, _DATA_TYPE[kind + array]))
    for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS (?:public\.)?(\w+) \((.*?)\n\);", sql, re.S):
        for column, kind, array in re.findall(rf"^\s*(\w+)\s+({_TYPES})(\[\])?\b", body, re.M):
            out.add((table, column, _DATA_TYPE[kind + array]))
    return out


def test_every_column_the_learning_wave2_migrations_add_is_required():
    """The release fence knows the wave-2 schema: every table and column those
    migrations add is a REQUIRED_COLUMNS entry of the type information_schema
    reports — so a release whose database lacks one fails the audit."""
    directory = verify.BACKEND / "db" / "migrations"
    introduced = set()
    for name in _LEARNING_SCHEMA_MIGRATIONS:
        introduced |= _introduced_columns((directory / name).read_text())
    # 7 post-test window/outcome columns (A112), 13 for A113, 1 for A119, 11 for A124,
    # 22 for A123 (learning_evidence_voids 11, misconception_attempts 6, five columns
    # on node_mastery_events, check_item_reviews and misconceptions), 2 for A128
    # (documents.check_items_status / check_items_at), 1 for A127
    # (node_mastery_events.student_confidence), 12 for A126 (6 pose columns and
    # the 6-column posttest_skips table), 1 for A137 (llm_usage.course_id), 26 for
    # A138/A139 (the 13-column learning_prequestions and learning_self_explanations)
    assert len(introduced) == 96
    assert ("llm_usage", "course_id", "text") in introduced
    assert ("learning_prequestions", "guess_json", "text") in introduced
    assert ("learning_self_explanations", "reply_chars", "integer") in introduced
    assert ("node_mastery_events", "student_confidence", "double precision") in introduced
    required = {
        (table, column, kind)
        for table, columns in verify.REQUIRED_COLUMNS.items()
        for column, kind in columns.items()
    }
    assert introduced <= required, sorted(introduced - required)


def test_real_repository_learning_rpc_signatures_are_readable_and_new_rpc_is_discovered(tmp_path):
    actual = verify.required_rpcs(verify.BACKEND / "db" / "migrations")
    assert actual["ai_budget_bump_tutor_calls"] == ["p_user_id text, p_day date"]
    assert "p_id text" in actual["misconception_record"][0]
    (tmp_path / "20261019000000_budget_new.sql").write_text(
        "CREATE FUNCTION public.reserve_example(p_user text, p_count int DEFAULT 1) RETURNS boolean AS $$ SELECT true $$ LANGUAGE sql;"
    )
    assert verify.required_rpcs(tmp_path) == {"reserve_example": ["p_user text, p_count integer"]}
    (tmp_path / "20261019000001_budget_drop.sql").write_text(
        "DROP FUNCTION reserve_example(text, integer);"
    )
    with pytest.raises(verify.VerificationError, match="DDL changed"):
        verify.required_rpcs(tmp_path)


def test_logs_export_only_category_counts_and_absence_is_not_delivery_proof(tmp_path):
    path = tmp_path / "runtime.log"
    path.write_text(
        "PRIVATE_ANSWER_OR_KEY events queue full (max=10); dropped 1\nstructured usage hook failed; usage row dropped\n"
    )
    result = verify.audit_log(path)
    assert result["status"] == "attention"
    assert result["matching_line_counts"]["event_or_usage_drop"] == 1
    assert result["matching_line_counts"]["usage_incomplete_or_hook_failed"] == 1
    assert "PRIVATE" not in json.dumps(result)
    path.write_text("")
    empty = verify.audit_log(path)
    assert (
        empty["status"] == "no_matching_lines"
        and empty["log_window_and_delivery_verified"] is False
    )


ACCOUNTING_HOOK_SOURCES = {
    "agents/usage.py": (
        "agent_usage_capture",
        "agent_retry_observability",
    ),
    "services/chat_stream.py": (
        "legacy_stream_usage",
        "structured_stream_usage",
    ),
    "routes/learn_loop.py": ("loop_continuation_usage",),
}
ACCOUNTING_HOOK_STAGES = tuple(
    stage for stages in ACCOUNTING_HOOK_SOURCES.values() for stage in stages
)


@pytest.mark.parametrize("stage", ACCOUNTING_HOOK_STAGES)
def test_actual_private_accounting_warnings_need_attention_without_exporting_content(
    stage, tmp_path
):
    message = f"Usage accounting hook failed (stage={stage}, error_type=%s)"
    relative_path = next(
        path for path, stages in ACCOUNTING_HOOK_SOURCES.items() if stage in stages
    )
    # Inspect the emitted contract without importing routes, agents or their providers.
    emitter = ast.parse((Path(__file__).resolve().parents[1] / relative_path).read_text())
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "warning"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == message
        for node in ast.walk(emitter)
    )
    raw = (
        "PRIVATE_STUDENT_ANSWER WARNING "
        + message.replace("%s", "RuntimeError")
        + " PRIVATE_TOKEN_OR_EXCEPTION_MESSAGE\n"
    ).encode()
    path = tmp_path / "accounting.log"
    path.write_bytes(raw)
    result = verify.audit_log(path)
    assert result["status"] == "attention"
    assert result["matching_line_counts"]["usage_incomplete_or_hook_failed"] == 1
    assert sum(result["matching_line_counts"].values()) == 1
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["bytes"] == len(raw)
    assert result["raw_lines_exported"] is False
    assert result["log_window_and_delivery_verified"] is False
    serialized = json.dumps(result)
    assert "PRIVATE" not in serialized and "RuntimeError" not in serialized
    assert stage not in serialized


@pytest.mark.parametrize(
    "message",
    [
        "structured usage hook failed; usage row dropped",
        "could not record model usage",
        "Structured run ended without final output; usage is incomplete",
        "Loop continuation ended without final output; usage is unavailable",
    ],
)
def test_prior_usage_failure_messages_remain_visible(message, tmp_path):
    path = tmp_path / "legacy.log"
    path.write_text(message + "\n")
    result = verify.audit_log(path)
    assert result["status"] == "attention"
    assert result["matching_line_counts"]["usage_incomplete_or_hook_failed"] == 1


@pytest.mark.parametrize(
    "message",
    [
        "Usage accounting hook completed",
        "Usage accounting hook failures: 0",
        "Usage accounting hooks configured",
        "Usage capture succeeded",
        "Hook failed (stage=unrelated)",
    ],
)
def test_successful_accounting_or_unrelated_hooks_do_not_signal_failure(message, tmp_path):
    path = tmp_path / "normal.log"
    path.write_text(message + "\n")
    result = verify.audit_log(path)
    assert result["status"] == "no_matching_lines"
    assert not any(result["matching_line_counts"].values())
    assert result["log_window_and_delivery_verified"] is False


def test_default_cli_is_offline_and_never_authorizes_release(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(verify, "fetch_json", lambda *_a, **_k: pytest.fail("no default HTTP"))
    monkeypatch.setattr(verify, "database_audit", lambda *_a: pytest.fail("no default DB"))
    output = tmp_path / "proof.json"
    assert verify.main(["--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "plan_only_no_live_checks" and result["release_authorized"] is False
    assert stat_mode(output) == 0o600
    assert json.loads(output.read_text()) == result
    with pytest.raises(FileExistsError):
        verify.main(["--output", str(output)])


def stat_mode(path):
    return os.stat(path).st_mode & 0o777


def test_http_and_db_errors_do_not_export_raw_credentials_or_response_contents(monkeypatch, capsys):
    def error(*_a, **_k):
        raise RuntimeError("PRIVATE_PASSWORD_AND_ANSWER")

    monkeypatch.setattr(verify, "fetch_json", error)
    assert (
        verify.main(
            [
                "--probe",
                "--api-base",
                "https://api.example",
                "--web-base",
                "https://web.example",
                "--expected-commit",
                SHA,
            ]
        )
        == 1
    )
    result = capsys.readouterr().out
    assert "PRIVATE" not in result
    assert json.loads(result)["status"] == "failed"


def test_metadata_connection_reuses_ops_connector_with_read_only_timeouts_and_no_business_rpc(
    monkeypatch,
):
    from scripts import migration_drift_report as drift

    db = Database()
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def execute(self, sql):
            assert sql == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"

        def cursor(self):
            return db.cursor()

    def connect(value, **kwargs):
        calls.append(kwargs)
        assert "PRIVATE" in value  # Never copied into the returned report.
        return Connection()

    monkeypatch.setenv(
        "RELEASE_QA_DB_URL", "postgresql://operator:PRIVATE@127.0.0.1:54322/postgres"
    )
    monkeypatch.setattr(drift.psycopg, "connect", connect)
    args = SimpleNamespace(
        db_url_env="RELEASE_QA_DB_URL",
        expected_db_host="127.0.0.1",
        expected_db_port=54322,
        migration_reference=None,
    )
    result = verify.database_audit(
        args, {next(iter(db.recorded)): "a" * 64}, {"sample": ["p_user_id text, p_day date"]}
    )
    assert result["status"] == "passed" and "PRIVATE" not in json.dumps(result)
    assert calls == [
        {
            "connect_timeout": 5,
            "options": "-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000",
        }
    ]
    args.expected_db_port = 55622
    with pytest.raises(verify.VerificationError, match="host/port"):
        verify.database_audit(args, {}, {})
    assert len(calls) == 1


@pytest.mark.parametrize("oversized", [False, True])
def test_fetch_is_get_only_bounded_and_never_returns_raw_response(oversized, monkeypatch):
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, limit):
            assert limit == verify.MAX_RESPONSE_BYTES + 1
            return b"x" * limit if oversized else b'{"status":"ok"}'

    class Opener:
        def open(self, request, timeout):
            assert timeout == 3 and request.get_method() == "GET" and request.data is None
            assert request.get_header("Cookie") == "sapling_session=PRIVATE.signature"
            requests.append(request)
            return Response()

    monkeypatch.setattr(verify, "build_opener", lambda *handlers: Opener())
    if oversized:
        with pytest.raises(verify.VerificationError, match="bound"):
            verify.fetch_json(
                "https://api.example/api/health", timeout=3, token="PRIVATE.signature"
            )
    else:
        assert verify.fetch_json(
            "https://api.example/api/health", timeout=3, token="PRIVATE.signature"
        ) == (200, {"status": "ok"})
    assert len(requests) == 1


def test_db_flags_without_explicit_action_do_not_create_a_misleading_default_success(capsys):
    assert verify.main(["--expected-db-host", "127.0.0.1"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed" and report["release_authorized"] is False


# ── spec §13 A136: exact floats through the backend's own path ───────────────

#: what PostgREST answers for learning_float_probe() with the role setting
#: applied (extra_float_digits = 3), and with the Supabase image's default (0):
#: 15 and 6 significant digits.
EXACT_PROBE = (
    b'[{"float8_value":0.30000000000000004,"float4_value":0.12345679,'
    b'"jsonb_value":0.30000000000000004,"digits":"3"}]'
)
ROUNDED_PROBE = b'[{"float8_value":0.3,"float4_value":0.123457,"jsonb_value":0.3,"digits":"0"}]'
SERVICE_KEY = "eyJhbGciOiJIUzI1NiJ9.PRIVATE-SERVICE-KEY.signature"


def test_db_audit_requires_the_service_role_float_setting():
    db = Database()
    assert audit(db)["missing_role_settings"] == []
    db.role_settings = [("service_role", ["statement_timeout=8s"])]
    result = audit(db)
    assert result["status"] == "failed"
    assert result["missing_role_settings"] == ["service_role.extra_float_digits=3"]
    db.role_settings = []  # no role row at all (a plain Postgres)
    assert audit(db)["missing_role_settings"] == ["service_role.extra_float_digits=3"]


def test_float_probe_passes_only_when_every_value_reads_back_exactly():
    passed = verify.float_probe_result(200, json.loads(EXACT_PROBE))
    assert passed["status"] == "passed" and all(passed["exact"].values())
    assert passed["extra_float_digits"] == "3"
    rounded = verify.float_probe_result(200, json.loads(ROUNDED_PROBE))
    assert rounded["status"] == "failed"
    assert rounded["exact"] == {"float8": False, "float4": False, "float8_in_jsonb": False}


@pytest.mark.parametrize(
    "field,value",
    [
        ("float8_value", 0.3),
        ("float4_value", 0.123457),
        ("jsonb_value", 0.3),
        ("float8_value", "0.30000000000000004"),  # a string is not a JSON number
        ("float4_value", None),
    ],
)
def test_one_rounded_or_missing_value_fails_the_probe(field, value):
    row = json.loads(EXACT_PROBE)[0] | {field: value}
    assert verify.float_probe_result(200, [row])["status"] == "failed"


@pytest.mark.parametrize(
    "status,body", [(404, {"message": "Could not find the function"}), (200, []), (200, {})]
)
def test_float_probe_without_the_function_is_an_error_naming_the_migration(status, body):
    with pytest.raises(verify.VerificationError, match="20261108162223"):
        verify.float_probe_result(status, body)


def _rest_args(**overrides):
    return SimpleNamespace(
        **{
            "rest_url_env": "RELEASE_QA_REST_URL",
            "rest_key_env": "RELEASE_QA_SERVICE_KEY",
            "expected_rest_host": "project.supabase.example",
            "allow_loopback_http": False,
            "timeout": 5,
            **overrides,
        }
    )


def test_float_probe_is_one_bounded_get_with_the_service_key_and_never_reports_it(monkeypatch):
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, limit):
            assert limit == verify.MAX_RESPONSE_BYTES + 1
            return EXACT_PROBE

    class Opener:
        def open(self, request, timeout):
            assert timeout == 5 and request.get_method() == "GET" and request.data is None
            assert request.full_url == (
                "https://project.supabase.example/rest/v1/rpc/learning_float_probe"
            )
            assert request.get_header("Apikey") == SERVICE_KEY
            assert request.get_header("Authorization") == f"Bearer {SERVICE_KEY}"
            requests.append(request)
            return Response()

    monkeypatch.setenv("RELEASE_QA_REST_URL", "https://project.supabase.example")
    monkeypatch.setenv("RELEASE_QA_SERVICE_KEY", SERVICE_KEY)
    monkeypatch.setattr(verify, "build_opener", lambda *handlers: Opener())
    result = verify.rest_float_audit(_rest_args())
    assert result["status"] == "passed" and len(requests) == 1
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize(
    "url,key,match",
    [
        ("https://other.supabase.example", SERVICE_KEY, "expected host"),
        ("http://project.supabase.example", SERVICE_KEY, "HTTPS"),
        ("https://project.supabase.example/rest/v1", SERVICE_KEY, "origin"),
        ("https://project.supabase.example", "", "unset or malformed"),
        ("https://project.supabase.example", "PRIVATE key\r\nInjected: header", "malformed"),
    ],
)
def test_float_probe_refuses_an_unexpected_target_or_key_before_any_request(
    monkeypatch, url, key, match
):
    monkeypatch.setenv("RELEASE_QA_REST_URL", url)
    monkeypatch.setenv("RELEASE_QA_SERVICE_KEY", key)
    monkeypatch.setattr(verify, "build_opener", lambda *h: pytest.fail("no request"))
    with pytest.raises(verify.VerificationError, match=match) as exc:
        verify.rest_float_audit(_rest_args())
    assert "PRIVATE" not in str(exc.value)


def test_float_probe_cli_reports_a_rounded_stack_as_attention(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", SERVICE_KEY)
    args = ["--rest-float-probe", "--expected-rest-host", "127.0.0.1", "--allow-loopback-http"]
    monkeypatch.setattr(
        verify, "fetch_rest", lambda url, timeout, key: (200, json.loads(ROUNDED_PROBE))
    )
    assert verify.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "attention"
    assert report["checks"]["rest_float_round_trip"]["status"] == "failed"
    assert "PRIVATE" not in json.dumps(report)
    monkeypatch.setattr(
        verify, "fetch_rest", lambda url, timeout, key: (200, json.loads(EXACT_PROBE))
    )
    assert verify.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "requested_checks_passed_not_release_approval"
    assert report["release_authorized"] is False


def test_rest_target_without_the_probe_flag_fails_rather_than_passing(capsys):
    assert verify.main(["--expected-rest-host", "127.0.0.1"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_the_probe_function_is_in_the_signature_inventory():
    """The DB audit requires the function the probe reads: its migration is a
    learning_ migration, so the signature inventory discovers it."""
    rpcs = verify.required_rpcs(verify.BACKEND / "db" / "migrations")
    assert rpcs[verify.FLOAT_PROBE_RPC] == [""]
