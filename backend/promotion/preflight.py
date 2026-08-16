"""Read-only guards that must pass before production is touched (#516).

Every check here runs BEFORE any mutation. The functions are pure: callers hand
them already-fetched data (ledger rows, file lists, commit counts), which is
what keeps them testable offline and keeps the IO in one place — the runner.

Two deliberate exceptions to that purity: `ledger_exists` and
`recorded_filenames` take a live connection. They are the shared READ
primitives for the migrations ledger — scripts/migration_drift_report.py
(#317) consumes them too, alongside `ledger_diff` and `NO_LEDGER_REMEDIATION`,
because that script's own docstring records how re-implementing this diff
inline is exactly how it and a preflight drifted apart before. One
implementation, two consumers, no third copy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Matched against a whitespace-collapsed statement, not a single line — this
# repo writes wrapped multi-line ALTER TABLE/ALTER COLUMN clauses in house
# style (e.g. db/migrations/0012_gradebook.sql), so a line-oriented scan would
# miss a destructive clause split across lines. The finding still reports the
# statement's starting line and the runner prints the original source verbatim
# so the operator judges the actual statement rather than a filename.
DESTRUCTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("DROP TABLE", re.compile(r"\bDROP\s+TABLE\b", re.I)),
    ("DROP COLUMN", re.compile(r"\bDROP\s+COLUMN\b", re.I)),
    ("DROP VIEW", re.compile(r"\bDROP\s+VIEW\b", re.I)),
    ("TRUNCATE", re.compile(r"\bTRUNCATE\b", re.I)),
    # TYPE must be the operation right after the column name (optionally as
    # SET DATA TYPE) — a bare `.*TYPE` match flagged every benign ALTER COLUMN
    # touching a column literally named `type` (0001/0009/0026 define such).
    (
        "ALTER COLUMN ... TYPE",
        re.compile(r"\bALTER\s+COLUMN\s+\S+\s+(?:SET\s+DATA\s+)?TYPE\b", re.I),
    ),
    # Renames (table or column) break old prod code in the migrate→merge window
    # the same way a DROP does — 0020/0024 were exactly this shape. RENAME must
    # be the operation following the table name (not `.*`), else any identifier
    # named "rename" would match.
    (
        "ALTER TABLE ... RENAME",
        re.compile(r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?\S+\s+RENAME\b", re.I),
    ),
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


# The one no-ledger remediation, shared verbatim with
# scripts/migration_drift_report.py. The embedded newline is that script's
# exact output wrap — its CLI output can gate CI, so the constant carries the
# script's formatting and evaluate() flattens it for the one-line finding.
NO_LEDGER_REMEDIATION = (
    "Reconcile with `python -m db.migrate --baseline` against a schema you\n"
    "have verified is current, rather than applying."
)


def ledger_exists(conn) -> bool:
    """Has db.migrate ever touched this database? (One of the two sanctioned
    IO helpers here — see the module docstring.)"""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL")
        return bool(cur.fetchone()[0])


def recorded_filenames(conn) -> set[str]:
    """Every filename the ledger records. Callers must check `ledger_exists`
    first — this raises on a database that has no ledger at all."""
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


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

    A character scanner, not regexes: `--` or `/*` inside a single-quoted
    literal is data (`'a--b'` must not swallow the DDL after it on the same
    line), so literal state has to be tracked, including the `''` escape.
    Block comments nest, per Postgres. Dollar-quoted bodies ($$...$$) are
    deliberately NOT treated as literals: every one in this repo's migrations
    is an executable DO block or function body, where `--` really is a comment
    and DDL really runs — blanking them would hide statements from the scan.
    Comments are blanked to same-length runs of spaces so both line numbers
    and column offsets survive for the caller's line accounting.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    in_literal = False
    depth = 0  # block-comment nesting level
    while i < n:
        ch = sql[i]
        two = sql[i : i + 2]
        if depth:
            if two == "/*":
                depth += 1
                out.append("  ")
                i += 2
            elif two == "*/":
                depth -= 1
                out.append("  ")
                i += 2
            else:
                out.append(ch if ch == "\n" else " ")
                i += 1
        elif in_literal:
            if two == "''":  # escaped quote — the literal stays open
                out.append(two)
                i += 2
            else:
                if ch == "'":
                    in_literal = False
                out.append(ch)
                i += 1
        elif ch == "'":
            in_literal = True
            out.append(ch)
            i += 1
        elif two == "--":
            end = sql.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i))
            i = end
        elif two == "/*":
            depth = 1
            out.append("  ")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def scan_destructive(paths: list[Path]) -> list[Finding]:
    """Destructive DDL in the given migration files.

    This matters because the runner applies migrations BEFORE the code merges,
    so between those stages the OLD production code runs against the NEW schema.
    Additive DDL is harmless in that window; destructive DDL is not.

    Scans whole statements (split on `;`), not individual lines: this repo's
    house style wraps `ALTER TABLE ... ALTER COLUMN ... TYPE ...` across
    several lines, and a keyword split across lines would evade a line-by-line
    regex entirely. Each statement is whitespace-collapsed before matching so
    a wrapped statement matches identically to a single-line one; the finding
    still reports the line where the statement *begins* and the original
    (uncollapsed) source line, so the operator sees real SQL.
    """
    findings: list[Finding] = []
    for path in paths:
        raw_lines = path.read_text().splitlines()
        stripped = _strip_comments("\n".join(raw_lines))
        offset = 0
        for statement in stripped.split(";"):
            start = offset
            offset += len(statement) + 1  # +1 for the ';' the split consumed
            content_start = start + (len(statement) - len(statement.lstrip()))
            collapsed = " ".join(statement.split())
            if not collapsed:
                continue
            for label, pattern in DESTRUCTIVE_PATTERNS:
                if pattern.search(collapsed):
                    lineno = stripped.count("\n", 0, content_start) + 1
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
    staging_recorded: set[str] | None,
    destructive: list[Finding],
    commits_ahead: int,
    migrations_drift: str,
    production_is_ancestor: bool,
    allow_destructive: bool,
    skip_staging_check: bool,
) -> list[Finding]:
    """All blocking findings, in the order the operator should read them.

    An empty list means preflight passed and the runner may proceed.
    """
    findings: list[Finding] = []

    # The two git-side guards come first: they invalidate the rest of the
    # audit outright. `migration_files`, `recorded` and `destructive` all
    # describe the LOCAL checkout, and db.migrate applies LOCAL files — but
    # the thing being promoted is origin/main. Neither has an override flag,
    # deliberately: both states are cheap to fix and never safe to wave past.
    if migrations_drift:
        # Both failure directions are real: a stale main means origin/main
        # has a migration whose file is absent here — neither pending nor an
        # orphan, so preflight would pass, the merge would land, and prod
        # code 500s on the missing schema. A feature-branch checkout means an
        # unmerged local migration gets applied to production.
        offending = "; ".join(line.strip() for line in migrations_drift.splitlines())
        findings.append(
            Finding(
                "migrations-drift",
                f"the local db/migrations/ checkout does not match origin/main: "
                f"{offending}. The promotion audits and applies origin/main's "
                "migrations, so run it from an up-to-date main: "
                "`git checkout main && git pull`, and remove stray files from "
                "db/migrations/, then re-run.",
            )
        )
    if not production_is_ancestor:
        findings.append(
            Finding(
                "production-diverged",
                "origin/production has commit(s) that are not on origin/main "
                "(a hotfix or revert that was never back-merged). The merge "
                "would fail deterministically AFTER migrations applied. "
                "Back-merge production into main (or otherwise reconcile) "
                "before promoting.",
            )
        )
    if findings:
        # Everything below audits the local files/ledger the guards above
        # just discredited — stop before describing the wrong tree.
        return findings

    db_ref, api_ref = project_ref(db_url), project_ref(supabase_url)
    # An unreadable ref fails CLOSED: skipping the comparison when a var is
    # blank or unrecognised would let an .env.production with a staging
    # SUPABASE_DB_URL and a missing SUPABASE_URL sail through and migrate the
    # wrong database — the exact accident this guard exists to stop.
    unparsed = [
        name
        for name, ref in (("SUPABASE_DB_URL", db_ref), ("SUPABASE_URL", api_ref))
        if not ref
    ]
    if unparsed:
        findings.append(
            Finding(
                "target-unverified",
                f"No Supabase project ref could be parsed from {' or '.join(unparsed)}, "
                "so preflight cannot vouch that the DB and API point at the same "
                "project. Set SUPABASE_DB_URL to the SESSION-mode pooler URI "
                "(user postgres.<ref>) and SUPABASE_URL to https://<ref>.supabase.co.",
            )
        )
    elif db_ref != api_ref:
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
                "existing objects. " + NO_LEDGER_REMEDIATION.replace("\n", " "),
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
        if staging_recorded is None:
            # None means "couldn't read staging's ledger", which is NOT the same
            # claim as "staging has run nothing" (an empty set). Conflating the
            # two turned a missing STAGING_SUPABASE_DB_URL — the default
            # experience, since the var ships in no .env* example — into a false
            # per-migration accusation that pushed operators straight to
            # --skip-staging-check, disabling the guard entirely. Emit one
            # honest finding instead of guessing.
            if pending:
                findings.append(
                    Finding(
                        "staging-unknown",
                        f"Could not read staging's migration ledger, so it is unknown "
                        f"whether staging has run the {len(pending)} pending "
                        "migration(s). Set STAGING_SUPABASE_DB_URL to staging's "
                        "SESSION-mode pooler URI (staging is on the aws-1-us-west-2 "
                        "cluster), or pass --skip-staging-check to proceed "
                        "deliberately without this guard.",
                    )
                )
        else:
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
