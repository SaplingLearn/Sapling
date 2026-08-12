"""Stage sequencing for the promotion runner (#516).

Every port is injected, so the whole flow runs in-process with no database,
no network, no git and no gh.
"""
import json

import pytest

from promotion.runner import Options, Ports, run

# Compact separators on purpose: FastAPI emits `{"status":"ok",...}` with no
# spaces, and smoke's `api health` check looks for the literal `"status":"ok"`.
# json.dumps' default `", "`/`": "` separators would not contain that substring,
# so a faithful fake has to match the real wire format.
COMPACT = (",", ":")
HEALTH_OLD = json.dumps({"status": "ok", "commit": "old1111"}, separators=COMPACT)
# The deployed commit is production's merge-commit SHA, NOT main's tip — `gh pr
# merge --merge` creates a merge commit ON production, and Railway deploys
# production. HEALTH_NEW deliberately carries FakeGit's "origin/production" SHA
# ("prod222"), distinct from "origin/main"'s ("main111"), so a wait loop that
# (wrongly) compares against main instead can never match it — verified by
# hand: temporarily pointing runner.py's post-merge wait at origin/main makes
# test_happy_path_returns_zero_and_merges fail (times out, returns 1).
HEALTH_NEW = json.dumps({"status": "ok", "commit": "prod222"}, separators=COMPACT)
# What /api/health serves when the host injects no commit SHA (no Railway env
# var): reachable, healthy, but impossible to match against any deploy target.
HEALTH_UNKNOWN = json.dumps({"status": "ok", "commit": "unknown"}, separators=COMPACT)


class FakeGit:
    """Distinct SHAs per ref — a fake that returned the same SHA for every ref
    could never catch a wait loop comparing against the wrong one."""

    def __init__(self, main_sha="main111", production_sha="prod222", commits_ahead=3):
        self.shas = {"origin/main": main_sha, "origin/production": production_sha}
        self.commits_ahead = commits_ahead
        self.calls = []

    def fetch(self):
        self.calls.append("fetch")

    def head_sha(self, ref):
        self.calls.append(f"head:{ref}")
        return self.shas[ref]

    def commits_ahead_of(self, base, head):
        return self.commits_ahead

    def migrations_drift(self):
        """How the local db/migrations/ checkout differs from origin/main
        ("" = matches exactly). Clean by default; drift tests override."""
        return ""

    def is_ancestor(self, ancestor, descendant):
        """git merge-base --is-ancestor. True by default (production is an
        ancestor of main); divergence tests override."""
        return True


class FakeGh:
    def __init__(self):
        self.merged = False
        self.calls = []
        # Every SHA the runner pinned a merge to (gh --match-head-commit) —
        # the pin is how commits landing during the confirm pause are kept
        # from being promoted unscanned.
        self.match_head_commits = []

    def ensure_pr(self, base, head, title):
        self.calls.append("ensure_pr")
        return 999

    def state(self, number):
        return "MERGED" if self.merged else "OPEN"

    def merge(self, number, match_head_commit):
        self.calls.append("merge")
        self.match_head_commits.append(match_head_commit)
        self.merged = True

    def revert(self, number):
        """The runner must NEVER call this — see
        test_smoke_failure_does_not_revert_anything."""
        self.calls.append("revert")


def make_ports(**over):
    """Happy path by default; override one port per test."""
    fake_git, fake_gh = FakeGit(), FakeGh()
    healths = [HEALTH_OLD, HEALTH_NEW, HEALTH_NEW, HEALTH_NEW, HEALTH_NEW]

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, healths.pop(0) if healths else HEALTH_NEW
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    ports = dict(
        connect=FakeConn,
        migrate=lambda conn: ["0002_b.sql"],
        preflight_data=lambda conn: dict(
            ledger_exists=True,
            migration_files=["0001_a.sql", "0002_b.sql"],
            recorded={"0001_a.sql"},
            staging_recorded={"0001_a.sql", "0002_b.sql"},
            destructive=[],
            db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
            supabase_url="https://ref1.supabase.co",
        ),
        snapshots=[
            {"host": "aws-0-us-west-2.pooler.supabase.com", "tables": {"users": 8}, "ledger": ["0001_a.sql"]},
            {
                "host": "aws-0-us-west-2.pooler.supabase.com",
                "tables": {"users": 8, "events": 0},
                "ledger": ["0001_a.sql", "0002_b.sql"],
            },
        ],
        git=fake_git,
        gh=fake_gh,
        fetch=fetch,
        confirm=lambda prompt: True,
        out=lambda line: None,
        sleep=lambda seconds: None,
    )
    ports.update(over)
    return ports


class FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OperationalError(Exception):
    """Stand-in for psycopg.OperationalError (dead server, refused connection).
    The runner must catch broadly, not by driver type — asserted by tests that
    raise THIS class where the real code would see psycopg's."""


class TickingClock:
    """Deterministic stand-in for time.monotonic: advances 1s per read. The
    wait loop budgets on real elapsed time, so its termination depends on the
    clock moving — with the real clock and instant fakes, every timeout-path
    test would spin for wait_timeout REAL seconds."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def build(ports_kwargs, **option_over):
    """Assemble Ports/Options from the dict make_ports returns."""
    snapshots = list(ports_kwargs.pop("snapshots"))
    preflight_data = ports_kwargs.pop("preflight_data")
    migrate = ports_kwargs.pop("migrate")
    ports = Ports(
        connect=ports_kwargs["connect"],
        preflight_data=preflight_data,
        capture=lambda conn: snapshots.pop(0),
        migrate=migrate,
        git=ports_kwargs["git"],
        gh=ports_kwargs["gh"],
        fetch=ports_kwargs["fetch"],
        confirm=ports_kwargs["confirm"],
        out=ports_kwargs["out"],
        sleep=ports_kwargs["sleep"],
        monotonic=ports_kwargs.get("monotonic", TickingClock()),
    )
    options = Options(**{"wait_timeout": 5, "poll_interval": 0, **option_over})
    return ports, options


def test_happy_path_returns_zero_and_merges():
    kwargs = make_ports()
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 0
    assert "merge" in gh.calls


def test_preflight_failure_aborts_before_migrating():
    migrated = []
    kwargs = make_ports(migrate=lambda conn: migrated.append(1) or [])
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql"],
        recorded={"0001_a.sql", "0099_ghost.sql"},  # orphan
        staging_recorded={"0001_a.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    assert run(*build(kwargs)) == 1
    assert migrated == []
    assert kwargs["gh"].calls == []


def test_migrations_drift_blocks_before_any_ddl():
    """Preflight lists LOCAL migration files and the migrate port applies
    LOCAL files, but the thing being promoted is origin/main — a checkout that
    doesn't match makes the whole audit describe the wrong SQL. Any drift
    (tracked diff either direction, or untracked strays) must block before
    migrate and before the PR/merge stage, with no override flag.
    """

    class DriftedGit(FakeGit):
        def migrations_drift(self):
            return "M\tbackend/db/migrations/0002_b.sql\n?? backend/db/migrations/0099_stray.sql"

    migrated = []
    lines = []
    kwargs = make_ports(
        git=DriftedGit(), migrate=lambda conn: migrated.append(1) or [], out=lines.append
    )
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 1
    assert migrated == []  # blocked BEFORE any DDL could apply
    assert gh.calls == []  # and before the PR/merge stage
    text = "\n".join(lines)
    assert "0099_stray.sql" in text  # names the offending state
    assert "git checkout main" in text  # and the remediation
    assert "PREFLIGHT FAILED" in text


def test_production_divergence_blocks_before_any_ddl():
    """origin/production carrying a commit that is not on origin/main (an
    un-back-merged hotfix/revert) makes the eventual merge fail
    deterministically AFTER migrations applied. The ancestry guard must block
    at preflight, before any DDL.
    """

    class DivergedGit(FakeGit):
        def is_ancestor(self, ancestor, descendant):
            assert (ancestor, descendant) == ("origin/production", "origin/main")
            return False

    migrated = []
    lines = []
    kwargs = make_ports(
        git=DivergedGit(), migrate=lambda conn: migrated.append(1) or [], out=lines.append
    )
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 1
    assert migrated == []
    assert gh.calls == []
    text = "\n".join(lines).lower()
    assert "back-merge" in text
    assert "preflight failed" in text


def test_declining_the_prompt_stops_without_merging():
    kwargs = make_ports(confirm=lambda prompt: False)
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 2
    # ensure_pr runs BEFORE the prompt on purpose — the prompt names the PR
    # number. Declining must leave the PR open and unmerged, not uncreated.
    assert "merge" not in gh.calls
    assert gh.merged is False


def test_declining_warns_that_migrations_already_applied():
    lines = []
    kwargs = make_ports(confirm=lambda prompt: False, out=lines.append)
    run(*build(kwargs))
    text = "\n".join(lines).lower()
    assert "schema" in text and "ahead" in text


def test_wait_timeout_does_not_run_smoke():
    """A deploy that never lands must not be reported as a smoke failure."""
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_OLD  # never advances
        raise AssertionError("smoke must not run after a wait timeout")

    kwargs = make_ports(fetch=fetch)
    assert run(*build(kwargs)) == 1


def test_smoke_failure_returns_nonzero():
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    kwargs = make_ports(fetch=fetch)
    assert run(*build(kwargs)) == 1


def test_smoke_failure_prints_the_revert_command():
    lines = []

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    kwargs = make_ports(fetch=fetch, out=lines.append)
    run(*build(kwargs))
    assert "git revert" in "\n".join(lines)


def test_smoke_failure_does_not_revert_anything():
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    kwargs = make_ports(fetch=fetch)
    gh = kwargs["gh"]
    run(*build(kwargs))
    assert "revert" not in " ".join(gh.calls)


def test_merge_is_pinned_to_the_audited_main_sha():
    """`gh pr merge --merge` unpinned merges whatever origin/main's tip is AT
    MERGE TIME — commits landing while the operator sits at the confirm prompt
    would be promoted with their migrations never destructive-scanned nor
    applied. The merge port must receive the SHA stage-1 preflight audited
    (origin/main as of the preflight fetch) for gh's --match-head-commit.
    """
    kwargs = make_ports()
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 0
    assert gh.match_head_commits == ["main111"]  # FakeGit's origin/main at preflight


def test_moved_main_fails_fast_without_burning_the_retry_loop():
    """A --match-head-commit rejection is DETERMINISTIC — origin/main moved,
    and retrying can never make it match again. The retry loop exists for the
    transient gh 502 wedge; burning its 5 attempts here ends in the 'may
    still be landing' misdirection. The runner must detect the moved head
    (re-read origin/main), fail fast on the first attempt with both SHAs and
    a re-run pointer, warn that this run's migrations are already applied,
    and exit non-zero.
    """

    class MovedMainGit(FakeGit):
        """origin/main reads 'moved77' on every read after stage-1 preflight's."""

        def head_sha(self, ref):
            sha = super().head_sha(ref)
            if ref == "origin/main" and self.calls.count("head:origin/main") > 1:
                return "moved77"
            return sha

    class RejectingGh(FakeGh):
        def merge(self, number, match_head_commit):
            self.calls.append("merge")
            raise RuntimeError("Head branch was modified. Review and try the merge again. (HTTP 405)")

    lines = []
    kwargs = make_ports(git=MovedMainGit(), gh=RejectingGh(), out=lines.append)
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 1
    assert gh.calls.count("merge") == 1  # deterministic rejection: no retries burned
    text = "\n".join(lines)
    assert "main111" in text and "moved77" in text  # audited vs now
    assert "make promote" in text  # the remediation: re-run
    assert "ALREADY APPLIED" in text  # migrations landed this run — still warned
    assert "may still be landing" not in text  # not the transient-wedge misdirection


def test_moved_main_without_migrations_skips_the_already_applied_warning():
    """When nothing was pending, the fail-fast report must not claim
    migrations were applied this run — that would be its own false report.
    """

    class MovedMainGit(FakeGit):
        def head_sha(self, ref):
            sha = super().head_sha(ref)
            if ref == "origin/main" and self.calls.count("head:origin/main") > 1:
                return "moved77"
            return sha

    class RejectingGh(FakeGh):
        def merge(self, number, match_head_commit):
            self.calls.append("merge")
            raise RuntimeError("Head branch was modified. (HTTP 405)")

    lines = []
    kwargs = make_ports(git=MovedMainGit(), gh=RejectingGh(), out=lines.append)
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql"],
        recorded={"0001_a.sql"},  # nothing pending
        staging_recorded={"0001_a.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    kwargs["snapshots"] = [
        {"host": "aws-0-us-west-2.pooler.supabase.com", "tables": {"users": 8}, "ledger": ["0001_a.sql"]},
        {"host": "aws-0-us-west-2.pooler.supabase.com", "tables": {"users": 8}, "ledger": ["0001_a.sql"]},
    ]
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines)
    assert "moved77" in text
    assert "ALREADY APPLIED" not in text


def test_merge_retries_through_a_transient_failure():
    """The known `gh pr merge --merge` 502: error raised, but the PR does merge."""

    class FlakyGh(FakeGh):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def merge(self, number, match_head_commit):
            self.attempts += 1
            self.merged = True  # it landed despite the error
            if self.attempts == 1:
                raise RuntimeError("HTTP 502")

    kwargs = make_ports(gh=FlakyGh())
    assert run(*build(kwargs)) == 0


def test_merge_state_unreadable_does_not_claim_production_unchanged():
    """If every post-merge `gh pr view` fails, the merge may still have landed
    on one of the 5 attempts — this run just could never confirm it. Claiming
    "production code unchanged" here would be a real false report, the exact
    class of bug this tool exists to prevent. It must say UNKNOWN instead.
    """

    class UnreadableStateGh(FakeGh):
        def state(self, number):
            raise RuntimeError("gh: pr view failed (rate limited)")

        def merge(self, number, match_head_commit):
            self.calls.append("merge")
            self.merged = True  # it may well have landed...

    lines = []
    kwargs = make_ports(gh=UnreadableStateGh(), out=lines.append)
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines).lower()
    assert "unchanged" not in text
    assert "unknown" in text


def test_merge_state_stale_confirmation_does_not_claim_production_unchanged():
    """The all-reads-fail case above is only the narrowest instance. Here the
    FIRST post-merge read succeeds (genuinely not merged yet), but every read
    after that fails — so 4 more merge() attempts happen with no way to know
    whether one of them landed. A flag that only remembers "was any read ever
    successful" would print the accurate-sounding but false "Production code
    unchanged" here; only the MOST RECENT read's outcome is trustworthy.
    """

    class StaleThenUnreadableGh(FakeGh):
        def __init__(self):
            super().__init__()
            self.state_calls = 0

        def state(self, number):
            self.state_calls += 1
            # call 1 = the FIRST retry-loop read (after merge attempt 1),
            # which succeeds and says OPEN. Every read after that (covering
            # merge attempts 2-5) fails.
            if self.state_calls == 1:
                return "OPEN"
            raise RuntimeError("gh: pr view failed (rate limited)")

        def merge(self, number, match_head_commit):
            self.calls.append("merge")
            self.merged = True  # any of attempts 2-5 may have landed...

    lines = []
    kwargs = make_ports(gh=StaleThenUnreadableGh(), out=lines.append)
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines).lower()
    assert "unchanged" not in text
    assert "unknown" in text
    assert "gh pr view" in text


def test_merge_stays_open_after_retries_is_reported_as_observation_not_fact():
    """CRITICAL: rounds 2-3 fixed read FAILURE; this is read STALENESS. Even
    when every post-merge read succeeds and consistently says OPEN, gh's own
    documented squash/merge-502-while-it-lands wedge means a merge triggered
    by this run can land seconds AFTER the last read this run performed.
    "Error returned" does not mean "definitely nothing happened". The
    exhaustion message must report what was OBSERVED, not assert "production
    is unchanged" as a settled fact this run cannot actually know.
    """

    class NeverLandsGh(FakeGh):
        def merge(self, number, match_head_commit):
            self.calls.append("merge")
            # Deliberately never sets self.merged — every state() read below
            # (inherited from FakeGh, keyed on self.merged) genuinely, and
            # consistently, returns "OPEN".

    lines = []
    kwargs = make_ports(gh=NeverLandsGh(), out=lines.append)
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines).lower()
    assert "unchanged" not in text
    assert "gh pr view" in text
    assert "may still be landing" in text


def test_ensure_pr_failure_after_migrate_still_reports_schema_ahead():
    """By the time ensure_pr runs, the migrations are durably applied. A gh
    failure there (expired auth, network) must not surface as __main__'s bare
    one-line ERROR: the operator would get NONE of the partial-state report
    the decline/migrate-failed paths carefully emit. The runner must print
    the ALREADY-APPLIED / schema-AHEAD-of-code report first; re-raising after
    that is fine — the catch-all's ERROR line then supplements the report.
    """

    class DeadGh(FakeGh):
        def ensure_pr(self, base, head, title):
            raise RuntimeError("gh: HTTP 401 bad credentials")

    lines = []
    kwargs = make_ports(gh=DeadGh(), out=lines.append)
    with pytest.raises(RuntimeError, match="bad credentials"):
        run(*build(kwargs))
    text = "\n".join(lines)
    assert "ALREADY APPLIED" in text
    assert "AHEAD" in text
    assert "re-run" in text.lower()  # what to do next, same as the decline path


def test_nothing_to_promote_exits_clean():
    kwargs = make_ports()
    kwargs["git"].commits_ahead = 0
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql"],
        recorded={"0001_a.sql"},
        staging_recorded={"0001_a.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    assert run(*build(kwargs)) == 0


def test_post_merge_git_failure_reports_merge_landed_and_points_at_verify_only():
    """A transient git failure right AFTER the merge landed must not abort as
    a bare error: a subsequent plain re-run sees commits_ahead == 0 and exits
    0 "Nothing to promote", so the promoted deploy would never be verified or
    smoked. The runner must say the MERGE HAS LANDED, that verification could
    not run, and point at --verify-only — and still exit non-zero.
    """

    class DiesAfterMergeGit(FakeGit):
        def fetch(self):
            super().fetch()
            # Call 1 is stage-1 preflight; call 2 is the post-merge re-fetch.
            if self.calls.count("fetch") == 2:
                raise RuntimeError("could not resolve host: github.com")

    fetched_urls = []

    def fetch(method, url):
        fetched_urls.append(url)
        raise AssertionError("neither the deploy wait nor smoke may run after the git failure")

    lines = []
    kwargs = make_ports(git=DiesAfterMergeGit(), fetch=fetch, out=lines.append)
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 1
    assert gh.merged is True  # the merge really did land before git died
    assert fetched_urls == []
    text = "\n".join(lines)
    assert "MERGE HAS LANDED" in text
    assert "--verify-only" in text


def test_nothing_to_promote_mentions_verify_only():
    """A plain re-run after a partial post-merge failure lands exactly here —
    without a pointer at --verify-only, that re-run is a dead end that exits
    0 while the promoted deploy is still unverified and unsmoked.
    """
    lines = []
    kwargs = make_ports(out=lines.append)
    kwargs["git"].commits_ahead = 0
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql"],
        recorded={"0001_a.sql"},
        staging_recorded={"0001_a.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    assert run(*build(kwargs)) == 0
    assert "--verify-only" in "\n".join(lines)


def test_migration_failure_reports_partial_state_not_a_traceback():
    """apply_migration commits per file (db/migrate.py), so a failure partway
    through 3 pending migrations still leaves earlier ones durably applied
    and recorded. This is exactly the moment the tool's whole purpose is an
    honest state report: it must say how many landed and which file failed,
    warn that the schema is now ahead of the code, and return EXIT_FAIL —
    never let the exception propagate as a raw traceback.
    """

    def failing_migrate(conn):
        raise RuntimeError('syntax error at or near "FOO" in 0003_c.sql')

    lines = []
    kwargs = make_ports(migrate=failing_migrate, out=lines.append)
    kwargs["preflight_data"] = lambda conn: dict(
        ledger_exists=True,
        migration_files=["0001_a.sql", "0002_b.sql", "0003_c.sql"],
        recorded={"0001_a.sql"},
        staging_recorded={"0001_a.sql", "0002_b.sql", "0003_c.sql"},
        destructive=[],
        db_url="postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
        supabase_url="https://ref1.supabase.co",
    )
    # before: only 0001_a.sql recorded. after (re-captured on a FRESH
    # connection post-failure): 0002_b.sql landed and committed; 0003_c.sql
    # never did — that is what actually failed.
    kwargs["snapshots"] = [
        {"host": "aws-0-us-west-2.pooler.supabase.com", "tables": {"users": 8}, "ledger": ["0001_a.sql"]},
        {
            "host": "aws-0-us-west-2.pooler.supabase.com",
            "tables": {"users": 8},
            "ledger": ["0001_a.sql", "0002_b.sql"],
        },
    ]
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 1
    assert gh.calls == []  # a migration failure must never reach the PR/merge stage
    text = "\n".join(lines)
    assert "1 of 2" in text  # 1 of the 2 pending migrations landed
    assert "0003_c.sql" in text  # names the migration that actually failed
    assert "syntax error" in text  # surfaces the real driver error
    assert "ahead" in text.lower()  # schema-ahead-of-code warning, same as the decline path


def test_migration_failure_before_any_file_lands_does_not_blame_pending_zero():
    """db.migrate.run() has a prologue (SET maintenance_work_mem,
    ensure_tracking_table) that runs BEFORE any migration file — a failure
    there is indistinguishable, from the runner's side, from a failure on
    the first pending file's own SQL. Zero landed either way, so the runner
    must not confidently name pending[0] as "the" failed migration, and must
    not claim the schema is "PARTIALLY migrated" when nothing landed at all.
    """

    def failing_migrate(conn):
        raise RuntimeError("connection reset by peer")  # e.g. the SET fails, not any file

    lines = []
    kwargs = make_ports(migrate=failing_migrate, out=lines.append)
    # after (re-captured post-failure) matches before exactly: nothing landed.
    kwargs["snapshots"] = [
        {"host": "aws-0-us-west-2.pooler.supabase.com", "tables": {"users": 8}, "ledger": ["0001_a.sql"]},
        {"host": "aws-0-us-west-2.pooler.supabase.com", "tables": {"users": 8}, "ledger": ["0001_a.sql"]},
    ]
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines)
    assert "0 of 1" in text
    assert "0002_b.sql" not in text  # never blames the one pending migration by name
    assert "partially migrated" not in text.lower()  # nothing landed — it did not partially migrate
    assert "unchanged" in text.lower()  # the honest claim: the schema did not move at all
    assert "connection reset by peer" in text  # still surfaces the real error


def test_migration_failure_report_survives_dead_recovery_connection():
    """The likely cause of a migrate failure is a dead database — in which
    case the recovery reconnect fails too. That second failure must DEGRADE
    the MIGRATION FAILED report (no landed count, say the snapshot could not
    be captured and why), never crash the runner and discard the report
    entirely — the failed-migration error and do-not-re-run warning are the
    whole point of this path.
    """

    def failing_migrate(conn):
        raise RuntimeError("server closed the connection unexpectedly")

    connects = []

    def connect():
        connects.append(1)
        if len(connects) > 1:  # the post-failure recovery reconnect
            raise OperationalError("connection refused")
        return FakeConn()

    lines = []
    kwargs = make_ports(migrate=failing_migrate, out=lines.append, connect=connect)
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines)
    assert "MIGRATION FAILED" in text
    assert "server closed the connection unexpectedly" in text  # the migrate error itself
    assert "could not be captured" in text  # the degraded-snapshot note...
    assert "connection refused" in text  # ...and why
    assert "do not re-run blindly" in text.lower()
    assert "ahead" in text.lower()  # schema may now lead the code — still warned


def test_migration_failure_report_prints_before_connection_exit_raises():
    """If the migrate stage's connection died, the outer with-block's __exit__
    commit can itself raise on the way out of run(). That second exception may
    propagate (the catch-all in __main__ still prints it), but only AFTER the
    MIGRATION FAILED report is already on the operator's screen — an __exit__
    raise must not be able to mask the report.
    """

    class DeadOnExitConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            raise OperationalError("SSL connection has been closed unexpectedly")

    connects = []

    def connect():
        connects.append(1)
        # First connection (preflight/snapshot/migrate) dies on exit; the
        # recovery reconnect works, so the FULL report is available.
        return DeadOnExitConn() if len(connects) == 1 else FakeConn()

    def failing_migrate(conn):
        raise RuntimeError('syntax error at or near "FOO"')

    lines = []
    kwargs = make_ports(migrate=failing_migrate, out=lines.append, connect=connect)
    with pytest.raises(OperationalError):
        run(*build(kwargs))
    text = "\n".join(lines)
    assert "MIGRATION FAILED" in text
    assert "syntax error" in text


def test_target_line_printed_before_migrate_runs():
    """Names the DB project about to receive DDL, before the DDL runs — the
    only way an operator can catch a .env file pointing at the wrong project
    (matching SUPABASE_DB_URL/SUPABASE_URL refs proves nothing if BOTH
    consistently hold the wrong project's credentials) before, not after,
    migrations actually apply.
    """
    order = []
    kwargs = make_ports()
    kwargs["out"] = lambda line: order.append(("out", line))
    kwargs["migrate"] = lambda conn: order.append(("migrate", None)) or ["0002_b.sql"]
    assert run(*build(kwargs)) == 0

    target_idx = next(
        i for i, (kind, line) in enumerate(order) if kind == "out" and line.startswith("Target:")
    )
    migrate_idx = next(i for i, (kind, _) in enumerate(order) if kind == "migrate")
    assert target_idx < migrate_idx
    _, target_line = order[target_idx]
    assert "ref1" in target_line  # the project ref parsed out of db_url


def test_migrations_only_promotion_skips_pr_and_still_smokes():
    """Production's DB can trail its own code (a real, recurring state — see
    #316/#510): commits_ahead can be 0 while a migration is still pending.
    `gh pr create` would fail outright ("No commits between production and
    main"), so this path must skip PR/merge/deploy-wait entirely — but still
    smoke, since a migration that broke the running app is exactly the
    failure that stage exists to catch.
    """
    lines = []
    kwargs = make_ports(out=lines.append)
    kwargs["git"].commits_ahead = 0
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 0
    assert gh.calls == []  # no ensure_pr, no merge — nothing to promote via PR
    text = "\n".join(lines).lower()
    assert "migrations applied" in text and "no code to promote" in text


def test_migrations_only_promotion_fails_if_smoke_fails():
    """The EXIT_FAIL branch of the migrations-only path must be wired to a
    real smoke result, not a stub that always reports success.

    IMPORTANT: this path must NOT hand the operator `_run_smoke`'s default
    `git revert -m 1 HEAD` recipe. No PR was merged this run, so
    production's git HEAD is a PREVIOUS promotion's merge commit, unrelated
    to this run — that instruction would revert an unrelated, previously
    working deploy. There is no code to revert here in the first place; the
    thing to inspect is the migration that just landed.
    """

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    kwargs["git"].commits_ahead = 0
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 1
    assert gh.calls == []
    text = "\n".join(lines)
    assert "git revert" not in text
    assert "No code was merged this run" in text


def test_verify_only_skips_promotion_and_just_waits_and_smokes():
    """--verify-only IS the resume path (the brief's "already-merged PR resumes
    the wait" story is unreachable: after a real merge, a fresh `run()` sees
    commits_ahead == 0 and nothing pending, so preflight reports
    nothing-to-promote and exits clean before ever reaching the wait).
    --verify-only skips preflight/snapshot/migrate/PR/merge entirely, but the
    wait-then-smoke tail must still genuinely run.

    /api/health alone does NOT prove the wait loop ran: it is ALSO one of
    smoke's own CHECKS (smoke.py), hit by run_checks independently of any
    wait — a run() that short-circuited straight to _run_smoke would still
    fetch /api/health once and pass a naive "was /api/health fetched?" check.
    So the health fake here reports a non-matching commit on the first poll
    and the matching one only on the second, forcing the wait loop to
    iterate (and therefore sleep) at least once — a signal ONLY the wait
    loop can produce — and `sleep` is spied on directly.
    """
    connect_calls = []
    migrated = []
    fetch_urls = []
    sleep_calls = []
    health_sequence = [HEALTH_OLD, HEALTH_NEW, HEALTH_NEW, HEALTH_NEW, HEALTH_NEW]

    def fetch(method, url):
        fetch_urls.append(url)
        if url.endswith("/api/health"):
            return 200, health_sequence.pop(0) if health_sequence else HEALTH_NEW
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    kwargs = make_ports()
    kwargs["fetch"] = fetch
    kwargs["sleep"] = lambda seconds: sleep_calls.append(seconds)
    kwargs["connect"] = lambda: connect_calls.append(1) or FakeConn()
    kwargs["migrate"] = lambda conn: migrated.append(1) or ["should-not-run"]
    gh = kwargs["gh"]
    assert run(*build(kwargs, verify_only=True)) == 0
    assert connect_calls == []  # no preflight/snapshot/migrate — no DB touched
    assert migrated == []
    assert gh.calls == []  # no ensure_pr, no merge
    assert len(sleep_calls) >= 1  # only the wait loop sleeps in --verify-only
    # /api/semesters is only ever requested by smoke.run_checks (CHECKS), never
    # by the wait loop (which only ever calls /api/health) — its presence is
    # proof smoke genuinely executed too, not just the wait.
    assert any(u.endswith("/api/semesters") for u in fetch_urls)


def test_verify_only_smoke_failure_does_not_print_revert_recipe():
    """--verify-only never merges by design (see Options.verify_only), so a
    smoke failure under it must not get _run_smoke's default
    `git checkout production && git revert -m 1 HEAD` recipe either — that
    would tell the operator to revert a PREVIOUS promotion's merge commit
    that this invocation had nothing to do with. This is the second door
    onto the same false-report bug the migrations-only path already fixed:
    _wait_then_smoke must forward merged_this_run, not just _run_smoke's
    other direct callers.
    """

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_NEW
        return 500, "boom"

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    assert run(*build(kwargs, verify_only=True)) == 1
    text = "\n".join(lines)
    assert "git revert" not in text
    assert "No code was merged this run" in text


def test_unknown_live_commit_degrades_instead_of_hanging():
    """No Railway env var: /api/health says 'unknown' for the WHOLE window.
    Don't wait forever — but don't declare success off the first poll either
    (right after the merge, the OLD deploy is still serving; one 'unknown'
    proves nothing about the new one). Only after the entire window yields
    nothing but 'unknown' may the runner degrade to smoke, and then the final
    report must not claim the deploy was verified.
    """
    sleep_calls = []

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, HEALTH_UNKNOWN
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    kwargs["sleep"] = lambda seconds: sleep_calls.append(seconds)
    assert run(*build(kwargs)) == 0
    text = "\n".join(lines)
    assert len(sleep_calls) >= 2  # kept polling past the first 'unknown'
    assert "NEVER VERIFIED" in text  # the honest completion line...
    assert "PROMOTION COMPLETE — all smoke checks passed." not in text  # ...not the verified one


def test_unknown_on_first_poll_keeps_waiting_for_the_real_sha():
    """The first poll lands BEFORE the new deploy could possibly be serving —
    an 'unknown' there must be treated like any other non-matching answer and
    polled through, or smoke silently runs against the still-serving OLD
    deploy and the run prints a false PROMOTION COMPLETE.
    """
    healths = [HEALTH_UNKNOWN, HEALTH_UNKNOWN, HEALTH_NEW]

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, healths.pop(0) if healths else HEALTH_NEW
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    assert run(*build(kwargs)) == 0
    text = "\n".join(lines)
    assert "deploy is live" in text  # the wait genuinely confirmed prod222
    assert "PROMOTION COMPLETE — all smoke checks passed." in text


def test_wait_budget_is_wall_clock_not_nominal_ticks():
    """Each health fetch can itself take up to 25s (httpx_fetch's timeout).
    A budget accounted as `waited += poll_interval` ignores that entirely, so
    a 600s wait_timeout can run ~35 minutes of wall clock during an incident
    — exactly when an operator is watching it. The budget must be real
    elapsed time read off the monotonic port.
    """

    class Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()
    polls = []

    def fetch(method, url):
        if not url.endswith("/api/health"):
            raise AssertionError("smoke must not run after a wait timeout")
        polls.append(url)
        clock.now += 25.0  # a hung health endpoint eating the full httpx timeout
        return 200, HEALTH_OLD  # never advances to the target

    def sleep(seconds):
        clock.now += seconds

    kwargs = make_ports(fetch=fetch, sleep=sleep)
    kwargs["monotonic"] = clock
    ports, options = build(kwargs, wait_timeout=100, poll_interval=10)
    assert run(ports, options) == 1
    # 100s of wall clock at 35s per fetch+sleep round = 3 polls — not the 10
    # that nominal-tick accounting (wait_timeout / poll_interval) would allow.
    assert len(polls) == 3


def test_unknown_mixed_with_real_sha_is_a_timeout_not_a_degrade():
    """A window that ever produced a REAL (non-matching) SHA proves the host
    DOES inject commits — the target simply never showed up. That is the
    plain deploy-timeout case: no smoke, EXIT_FAIL, not the degraded
    'verification impossible' path.
    """
    healths = [HEALTH_UNKNOWN, HEALTH_OLD]

    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, healths.pop(0) if healths else HEALTH_OLD
        raise AssertionError("smoke must not run after a wait timeout")

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    assert run(*build(kwargs)) == 1
    assert "TIMEOUT" in "\n".join(lines)
