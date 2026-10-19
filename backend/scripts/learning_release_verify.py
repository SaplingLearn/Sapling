"""Opt-in read-only learning release checks; never a release authorization.

Default: inspect local migration inventory only, with no env loading or I/O to
services. --probe uses bounded GETs; --db-audit uses the migration-operations
metadata seam in a read-only transaction. No models, migrations, RPC execution,
flag changes, token minting, learner writes or deployment actions are performed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from promotion.preflight import ledger_diff, ledger_exists, recorded_filenames  # noqa: E402

MAX_RESPONSE_BYTES = 128_000
MAX_LOG_BYTES = 10_000_000
REQUIRED_COLUMNS = {
    "sessions": {
        "loop_state": "jsonb",
        "loop_state_rev": "bigint",
        "close_json": "text",
        "close_phase": "text",
    },
    "node_mastery_events": {
        "planning_observation": "jsonb",
        "evidence_seq": "integer",
        "grader_backend": "text",
    },
    "learner_state": {
        "p_known": "double precision",
        "n_strong_unassisted": "integer",
        "evidence_version": "bigint",
        "evidence_touch_at": "timestamp with time zone",
    },
    "graph_nodes": {"evidence_version": "bigint"},
    "learning_evidence_operations": {
        "operation_id": "uuid",
        "user_id": "text",
        "course_id": "text",
        "input_fingerprint": "text",
        "plan": "jsonb",
        "changes": "jsonb",
        "committed_at": "timestamp with time zone",
    },
    "checklist_budget_accounts": {
        "user_id": "text",
        "policy": "text",
        "daily_usd": "numeric",
        "monthly_usd": "numeric",
        "daily_tokens": "bigint",
        "blocked": "boolean",
        "next_fence": "bigint",
    },
    "checklist_budget_reservations": {
        "operation_id": "uuid",
        "user_id": "text",
        "enrollment_id": "text",
        "input_hash": "text",
        "fence": "bigint",
        "state": "text",
        "held_usd": "numeric",
        "held_tokens": "bigint",
        "created_at": "timestamp with time zone",
        "dispatch_at": "timestamp with time zone",
        "expires_at": "timestamp with time zone",
        "receipt_id": "text",
        "receipt": "jsonb",
        "fingerprint": "text",
        "reason": "text",
        "cache_published": "boolean",
    },
    "check_items": {
        "concept_key": "text",
        "question_hash": "text",
        "final_answer": "text",
        "difficulty": "smallint",
    },
    "llm_usage": {"cached_tokens": "integer", "thinking_tokens": "integer", "session_id": "text"},
    "learning_reveals": {"rung": "smallint", "graded_at": "timestamp with time zone"},
    "posttest_poses": {
        "claim": "text",
        "claimed_at": "timestamp with time zone",
        "answered_at": "timestamp with time zone",
    },
}
# This fence must not manufacture historical activity during migration.
# Other column constraints/defaults remain outside this metadata-only contract.
REQUIRED_COLUMN_ATTRIBUTES = {("learner_state", "evidence_touch_at"): ("YES", None)}
LOG_PATTERNS = {
    "event_or_usage_drop": re.compile(
        r"events queue full|events flush dropped|log_llm_usage failed; row dropped|events row insert failed",
        re.I,
    ),
    "usage_incomplete_or_hook_failed": re.compile(
        r"(?:usage.*(?:incomplete|unavailable))|(?:usage (?:accounting )?hook failed)|(?:could not record.*usage)",
        re.I,
    ),
    "stream_failure": re.compile(
        r"(?:structured|chat) stream.*(?:failed|exhausted)|nonstream fallback also failed|UnexpectedModelBehavior",
        re.I,
    ),
    "platform_spend_alert": re.compile(r"ai_budget: platform spend today", re.I),
}
FUNCTION = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?([a-z_][a-z0-9_]*)\s*\((.*?)\)\s*RETURNS\b",
    re.I | re.S,
)


class VerificationError(ValueError):
    """Messages are fixed classifications, never provider/credential content."""


def migration_inventory(directory: Path) -> dict[str, str]:
    paths = sorted(directory.glob("*.sql"))
    if not paths:
        raise VerificationError("No migration files found")
    if any(not re.fullmatch(r"(?:\d{4}|\d{14})_.+\.sql", p.name) or p.is_symlink() for p in paths):
        raise VerificationError("Invalid or symlinked migration filename")
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _arguments(value: str) -> str:
    """Normalize the simple named IN argument types used by learning RPCs.

    Unsupported declarations fail closed rather than guessing a signature.
    This is a catalog signature check, not a SQL body/permission verifier.
    """
    if not value.strip():
        return ""
    args = []
    for part in value.split(","):
        part = re.split(r"\s+DEFAULT\s+|\s*=\s*", part.strip(), maxsplit=1, flags=re.I)[0]
        part = re.sub(r"^IN\s+", "", part, flags=re.I)
        found = re.fullmatch(r"([a-z_][a-z0-9_]*)\s+([a-z][a-z0-9_ .\[\]]*)", part, re.I)
        if not found or found[1].lower() in {"out", "inout", "variadic"}:
            raise VerificationError(
                "Unsupported learning RPC declaration; review signature explicitly"
            )
        kind = " ".join(found[2].lower().split())
        kind = {
            "int": "integer",
            "int4": "integer",
            "int8": "bigint",
            "bool": "boolean",
            "timestamptz": "timestamp with time zone",
            "float8": "double precision",
        }.get(kind, kind)
        args.append(f"{found[1].lower()} {kind}")
    return ", ".join(args)


def required_rpcs(directory: Path) -> dict[str, list[str]]:
    """Read declared signatures from learning/budget migrations, not a stale list."""
    found: dict[str, set[str]] = {}
    for path in sorted(directory.glob("*.sql")):
        if not any(key in path.name for key in ("learning_", "budget", "receipt", "reservation")):
            continue
        # Current series declarations are static, unquoted public functions.
        sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", path.read_text(), flags=re.S)
        matches = list(FUNCTION.finditer(sql))
        declared = re.findall(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b", sql, re.I)
        if len(matches) != len(declared) or re.search(r"\bDROP\s+FUNCTION\b", sql, re.I):
            raise VerificationError("Learning RPC DDL changed; signature inventory needs review")
        for match in matches:
            found.setdefault(match[1].lower(), set()).add(_arguments(match[2]))
    if not found:
        raise VerificationError("No learning RPC signatures found")
    return {name: sorted(signatures) for name, signatures in sorted(found.items())}


def validate_origin(value: str, allow_loopback_http: bool = False) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise VerificationError("Invalid endpoint origin") from None
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise VerificationError("Endpoint must be an origin without credentials, query or path")
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not (allow_loopback_http and local and parsed.scheme == "http"):
        raise VerificationError("Use HTTPS or explicitly allow loopback HTTP")
    return value.rstrip("/")


def read_session_token(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise VerificationError("Session token file must be owner-only and regular")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise VerificationError("Session token file too large")
        token = raw.decode("ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
            raise VerificationError("Session token file has invalid format")
        return token
    finally:
        os.close(fd)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def fetch_json(url: str, *, timeout: float, token: str | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Cookie"] = f"sapling_session={token}"
    request = Request(url, headers=headers, method="GET")
    try:
        response = build_opener(_NoRedirect()).open(request, timeout=timeout)
    except HTTPError as error:
        response = error  # Preserve 401/404; never follow a login redirect.
    with response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise VerificationError("Response exceeded metadata bound")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise VerificationError("Expected JSON object metadata")
        return response.status, value


def probe_health(fetch, base: str, expected_commit: str, expected_mode: str) -> dict:
    status, body = fetch(base + "/api/health")
    commit = body.get("commit")
    if (
        status != 200
        or body.get("status") != "ok"
        or body.get("service") != "sapling-backend"
        or body.get("model_mode") != expected_mode
        or not isinstance(commit, str)
        or not re.fullmatch(r"[0-9a-f]{7,40}", commit)
        or not expected_commit.startswith(commit)
    ):
        raise VerificationError("Health, model mode or reported commit prefix did not match")
    return {
        "status": "passed",
        "http_status": status,
        "reported_commit": commit,
        "model_mode": expected_mode,
        "full_artifact_identity_verified": False,
    }


def probe_loop(fetch, base: str, user_id: str, expectation: str) -> dict:
    query = urlencode({"user_id": user_id, "session_id": "00000000-0000-4000-8000-000000000000"})
    status, body = fetch(base + "/api/learn/loop/status?" + query)
    matched = (expectation == "enabled" and status == 200 and body.get("active") is True) or (
        expectation == "disabled"
        and status == 404
        and body.get("detail") == "learning loop not enabled"
    )
    if not matched:
        raise VerificationError(
            "Authenticated loop state did not match; 401 or generic 404 is not flag proof"
        )
    return {
        "status": "passed",
        "expected_loop": expectation,
        "http_status": status,
        "scope": "Authenticated read-only status; does not certify browser fallback, old sessions or zero model writes.",
    }


def audit_database(
    conn, inventory: dict[str, str], rpcs: dict[str, list[str]], reference: dict | None = None
) -> dict:
    """Established migration-ops metadata reads only; never invoke the RPCs."""
    with conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        if cur.fetchone()[0] != "on":
            raise VerificationError("Database metadata connection is not read-only")
    if not ledger_exists(conn):
        raise VerificationError(
            "Migration ledger missing; do not baseline or apply from this verifier"
        )
    recorded = recorded_filenames(conn)
    pending, orphans = ledger_diff(sorted(inventory), recorded)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (list(REQUIRED_COLUMNS),),
        )
        actual = {(table, column): kind for table, column, kind in cur.fetchall()}
        cur.execute(
            "SELECT table_name, column_name, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (sorted({table for table, _column in REQUIRED_COLUMN_ATTRIBUTES}),),
        )
        attributes = {
            (table, column): (nullable, default)
            for table, column, nullable, default in cur.fetchall()
        }
        cur.execute(
            "SELECT p.proname, pg_get_function_identity_arguments(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' AND p.proname = ANY(%s)",
            (list(rpcs),),
        )
        actual_rpcs = {(name, _arguments(args)) for name, args in cur.fetchall()}
    missing_columns = [
        f"{table}.{column}:{kind}"
        for table, columns in REQUIRED_COLUMNS.items()
        for column, kind in columns.items()
        if actual.get((table, column)) != kind
    ]
    missing_rpcs = [
        name + "(" + args + ")"
        for name, signatures in rpcs.items()
        for args in signatures
        if (name, args) not in actual_rpcs
    ]
    wrong_attributes = [
        f"{table}.{column}:nullable={expected[0]},default={expected[1]}"
        for (table, column), expected in REQUIRED_COLUMN_ATTRIBUTES.items()
        if attributes.get((table, column)) != expected
    ]
    changed = []
    if reference is not None:
        if (
            not isinstance(reference, dict)
            or not reference
            or any(
                not isinstance(name, str)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                for name, digest in reference.items()
            )
        ):
            raise VerificationError("Invalid prior migration hash reference")
        changed = sorted(
            name for name in recorded & reference.keys() if inventory.get(name) != reference[name]
        )
    return {
        "status": "passed"
        if not (
            pending or orphans or missing_columns or wrong_attributes or missing_rpcs or changed
        )
        else "failed",
        "read_only": True,
        "recorded_count": len(recorded),
        "pending": pending,
        "orphans": orphans,
        "missing_or_wrong_type_columns": missing_columns,
        "missing_or_wrong_column_attributes": wrong_attributes,
        "missing_rpc_signatures": missing_rpcs,
        "changed_applied_reference_files": changed,
        "prior_reference_supplied": reference is not None,
        "prior_reference_covers_all_recorded": reference is not None
        and recorded <= reference.keys(),
        "database_function_bodies_constraints_rls_backfill_verified": False,
        "ledger_content_checksums_available": False,
    }


def database_audit(args, inventory, rpcs):
    # Lazy import of the existing migration operations seam; no runtime app
    # config, .env loading, new REST client or default DB contact.
    from scripts import migration_drift_report as drift

    value = os.environ.get(args.db_url_env, "")
    target = urlsplit(value)
    if (
        target.scheme not in {"postgres", "postgresql"}
        or target.hostname != args.expected_db_host
        or target.port != args.expected_db_port
        or target.port == 6543
    ):
        raise VerificationError(
            "Explicit database host/port did not match the selected environment variable"
        )
    reference = (
        json.loads(args.migration_reference.read_text()) if args.migration_reference else None
    )
    with drift.psycopg.connect(
        value,
        connect_timeout=5,
        options="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000",
    ) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return audit_database(conn, inventory, rpcs, reference)


def audit_log(path: Path) -> dict:
    with path.open("rb") as stream:
        raw = stream.read(MAX_LOG_BYTES + 1)
    if len(raw) > MAX_LOG_BYTES:
        raise VerificationError("Log exceeds bound; provide a bounded deployment-window capture")
    text = raw.decode("utf-8", errors="replace")
    counts = {
        name: sum(bool(pattern.search(line)) for line in text.splitlines())
        for name, pattern in LOG_PATTERNS.items()
    }
    return {
        "status": "attention" if any(counts.values()) else "no_matching_lines",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "matching_line_counts": counts,
        "log_window_and_delivery_verified": False,
        "raw_lines_exported": False,
        "qualification": "No matches does not prove telemetry is enabled, delivered or complete. Operator must bind the capture to its deployment/time window.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="Perform bounded actual GET probes")
    parser.add_argument("--api-base")
    parser.add_argument("--web-base")
    parser.add_argument(
        "--expected-commit",
        help="Reviewed full 40-character commit; health only proves its reported prefix",
    )
    parser.add_argument("--expect-model-mode", choices=("real", "function"), default="real")
    parser.add_argument("--allow-loopback-http", action="store_true")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--session-token-file", type=Path)
    parser.add_argument("--user-id")
    parser.add_argument("--expect-loop", choices=("enabled", "disabled"))
    parser.add_argument(
        "--db-audit",
        action="store_true",
        help="Explicit read-only migration metadata audit; reads only the named URL env var",
    )
    parser.add_argument("--db-url-env", default="SUPABASE_DB_URL")
    parser.add_argument("--expected-db-host")
    parser.add_argument("--expected-db-port", type=int)
    parser.add_argument(
        "--migration-reference",
        type=Path,
        help="Previously approved filename->SHA256 JSON, not a self-certified live schema",
    )
    parser.add_argument("--log", type=Path, action="append", default=[])
    parser.add_argument(
        "--output", type=Path, help="New JSON proof file; an existing proof is never overwritten"
    )
    args = parser.parse_args(argv)
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "release_authorized": False,
        "checks": {},
        "unverified": [
            "Deployment configuration and full artifact provenance",
            "Migration SQL history, bodies, constraints, RLS and existing-data compatibility",
            "Authenticated browser kill-switch/re-enable and rollback rehearsal",
            "Telemetry delivery, incomplete-run reconciliation, alert routing and owner acknowledgement",
            "Independent learning validity and real-provider reliability",
        ],
    }
    try:
        directory = BACKEND / "db" / "migrations"
        inventory = migration_inventory(directory)
        report["migration_sha256"] = inventory
        report["checks"]["local_inventory"] = {"status": "passed", "files": len(inventory)}
        if args.probe:
            if (
                not args.expected_commit
                or not re.fullmatch(r"[0-9a-f]{40}", args.expected_commit)
                or not 0 < args.timeout <= 30
            ):
                raise VerificationError(
                    "Probe requires a reviewed full commit and a positive timeout at most 30 seconds"
                )
            api = validate_origin(args.api_base or "", args.allow_loopback_http)
            web = validate_origin(args.web_base or "", args.allow_loopback_http)
            report["expected_commit"] = args.expected_commit

            def fetch(url):
                return fetch_json(url, timeout=args.timeout)

            report["checks"]["api_health"] = probe_health(
                fetch, api, args.expected_commit, args.expect_model_mode
            )
            report["checks"]["web_proxy_health"] = probe_health(
                fetch, web, args.expected_commit, args.expect_model_mode
            )
            if bool(args.expect_loop) != bool(args.session_token_file) or bool(
                args.expect_loop
            ) != bool(args.user_id):
                raise VerificationError(
                    "Loop expectation, token file and QA user ID must be supplied together"
                )
            if args.expect_loop:
                if not args.session_token_file or not args.user_id:
                    raise VerificationError(
                        "Loop verification needs explicit owner-token file and matching QA user ID"
                    )
                token = read_session_token(args.session_token_file)

                def authenticated(url):
                    return fetch_json(url, timeout=args.timeout, token=token)

                report["checks"]["loop_status"] = probe_loop(
                    authenticated, api, args.user_id, args.expect_loop
                )
                token = ""
        elif args.expect_loop or args.session_token_file or args.user_id:
            raise VerificationError("Credentials and loop expectations require explicit --probe")
        if args.db_audit:
            if (
                not args.expected_db_host
                or not args.expected_db_port
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", args.db_url_env)
            ):
                raise VerificationError(
                    "Database audit needs explicit expected host/port and URL variable name"
                )
            report["checks"]["database_metadata"] = database_audit(
                args, inventory, required_rpcs(directory)
            )
        elif args.expected_db_host or args.expected_db_port or args.migration_reference:
            raise VerificationError(
                "Database target/reference arguments require explicit --db-audit"
            )
        for index, path in enumerate(args.log):
            report["checks"][f"log_{index + 1}"] = audit_log(path)
        if migration_inventory(directory) != inventory:
            raise VerificationError("Migration files changed during verification")
        report["status"] = (
            "attention"
            if any(
                value["status"] in {"failed", "attention"} for value in report["checks"].values()
            )
            else (
                "requested_checks_passed_not_release_approval"
                if args.probe or args.db_audit or args.log
                else "plan_only_no_live_checks"
            )
        )
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        report["error"] = (
            str(error)
            if isinstance(error, VerificationError)
            else "Details omitted; no credential or response content exported"
        )
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        # O_EXCL also rejects symlinks and preserves prior reports.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 1 if report["status"] in {"failed", "attention"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
