"""Read-only guards that must pass before production is touched (#516).

Every check here runs BEFORE any mutation. The functions are pure: callers hand
them already-fetched data (ledger rows, file lists, commit counts), which is
what keeps them testable offline and keeps the IO in one place — the runner.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Line-oriented, deliberately. A migration that is destructive on one line and
# harmless on the next should name the line, and the runner prints it verbatim
# so the operator judges the actual statement rather than a filename.
DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.I)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.I)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.I)),
    ("ALTER COLUMN ... TYPE", re.compile(r"\bALTER\s+COLUMN\b.*\bTYPE\b", re.I)),
]


@dataclass(frozen=True)
class Finding:
    """One blocking reason. `kind` is machine-readable, `detail` is for humans."""

    kind: str
    detail: str


def project_ref(value: str) -> str:
    """Supabase project ref from a DB URI or an API URL; "" if unrecognised.

    Three shapes are in play. The session-mode pooler carries the ref in the
    USERNAME (`postgres.<ref>@aws-0-...`) because the host is shared across
    projects; the direct endpoint carries it in the host (`db.<ref>.supabase.co`);
    the REST URL carries it as the leftmost label (`<ref>.supabase.co`).
    """
    parsed = urlparse(value)
    user = parsed.username or ""
    if user.startswith("postgres."):
        return user.split(".", 1)[1]
    host = parsed.hostname or ""
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return host.split(".")[1]
    if host.endswith(".supabase.co"):
        return host.split(".")[0]
    return ""


def ledger_diff(files: list[str], recorded: set[str]) -> tuple[list[str], list[str]]:
    """(pending, orphans) — pending keeps `files` order, orphans are sorted.

    An orphan is a filename the ledger records that the repo does not have: that
    environment ran SQL this repo has never seen. Applying more on top compounds
    it, which is why the runner treats it as blocking.
    """
    pending = [f for f in files if f not in recorded]
    orphans = sorted(recorded - set(files))
    return pending, orphans


def staging_gap(pending: list[str], staging_recorded: set[str]) -> list[str]:
    """Pending-on-prod migrations staging has never executed.

    Production must never be the first environment to run a piece of DDL.
    """
    return [f for f in pending if f not in staging_recorded]


def _strip_comments(sql: str) -> str:
    """Blank out `--` line comments and `/* */` blocks, preserving line numbers.

    The migrations in this repo carry long explanatory headers that frequently
    NAME destructive statements while doing nothing of the kind. Scanning raw
    text would flag most of them.
    """
    without_blocks = re.sub(
        r"/\*.*?\*/",
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        sql,
        flags=re.S,
    )
    return "\n".join(line.split("--", 1)[0] for line in without_blocks.splitlines())


def scan_destructive(paths: list[Path]) -> list[Finding]:
    """Destructive DDL in the given migration files.

    This matters because the runner applies migrations BEFORE the code merges,
    so between those stages the OLD production code runs against the NEW schema.
    Additive DDL is harmless in that window; destructive DDL is not.
    """
    findings: list[Finding] = []
    for path in paths:
        raw_lines = path.read_text().splitlines()
        scan_lines = _strip_comments("\n".join(raw_lines)).splitlines()
        for lineno, line in enumerate(scan_lines, 1):
            for label, pattern in DESTRUCTIVE_PATTERNS:
                if pattern.search(line):
                    original = raw_lines[lineno - 1].strip()
                    findings.append(Finding(label, f"{path.name}:{lineno}: {original}"))
    return findings


def evaluate(
    *,
    db_url: str,
    supabase_url: str,
    ledger_exists: bool,
    migration_files: list[str],
    recorded: set[str],
    staging_recorded: set[str],
    destructive: list[Finding],
    commits_ahead: int,
    allow_destructive: bool,
    skip_staging_check: bool,
) -> list[Finding]:
    """All blocking findings, in the order the operator should read them.

    An empty list means preflight passed and the runner may proceed.
    """
    findings: list[Finding] = []

    db_ref, api_ref = project_ref(db_url), project_ref(supabase_url)
    if db_ref and api_ref and db_ref != api_ref:
        findings.append(
            Finding(
                "target-mismatch",
                f"SUPABASE_DB_URL points at project {db_ref} but SUPABASE_URL "
                f"points at {api_ref}. The env file is mixed up — refusing to migrate.",
            )
        )

    if not ledger_exists:
        findings.append(
            Finding(
                "no-ledger",
                "schema_migrations does not exist on this database. Applying now "
                "would treat every migration as pending and fail recreating "
                "existing objects. Reconcile with `python -m db.migrate --baseline` "
                "against a verified-current schema first.",
            )
        )
        # Everything downstream reads the ledger, so stop describing it.
        return findings

    pending, orphans = ledger_diff(migration_files, recorded)
    for orphan in orphans:
        findings.append(
            Finding("orphan", f"recorded in the ledger but absent from the repo: {orphan}")
        )

    if not skip_staging_check:
        for name in staging_gap(pending, staging_recorded):
            findings.append(
                Finding(
                    "staging-gap",
                    f"{name} is pending on production but staging has never run it. "
                    "Production must not be the first environment to execute DDL. "
                    "Let migrate-staging.yml apply it first, or pass --skip-staging-check.",
                )
            )

    if destructive and not allow_destructive:
        for finding in destructive:
            findings.append(
                Finding(
                    "destructive",
                    f"{finding.kind} in a pending migration — {finding.detail}. "
                    "Migrations apply before the code merges, so the old production "
                    "code would run against this schema. Pass --allow-destructive "
                    "if that is genuinely safe here.",
                )
            )

    if commits_ahead == 0 and not pending:
        findings.append(
            Finding("nothing-to-promote", "origin/main and origin/production are identical.")
        )

    return findings
