"""Stage sequencing for the promotion runner (#516).

Every port is injected, so the whole flow runs in-process with no database,
no network, no git and no gh.
"""
import json

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


class FakeGh:
    def __init__(self):
        self.merged = False
        self.calls = []

    def ensure_pr(self, base, head, title):
        self.calls.append("ensure_pr")
        return 999

    def state(self, number):
        return "MERGED" if self.merged else "OPEN"

    def merge(self, number):
        self.calls.append("merge")
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
        connect=lambda: FakeConn(),
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
            {"tables": {"users": 8}, "ledger": ["0001_a.sql"]},
            {"tables": {"users": 8, "events": 0}, "ledger": ["0001_a.sql", "0002_b.sql"]},
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


def test_declining_the_prompt_stops_without_merging():
    kwargs = make_ports(confirm=lambda prompt: False)
    gh = kwargs["gh"]
    assert run(*build(kwargs)) == 2
    # ensure_pr runs BEFORE the prompt on purpose — the prompt names the PR
    # number, and an already-merged PR is how a re-run resumes. Declining must
    # leave the PR open and unmerged, not uncreated.
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


def test_merge_retries_through_a_transient_failure():
    """The known `gh pr merge --merge` 502: error raised, but the PR does merge."""

    class FlakyGh(FakeGh):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def merge(self, number):
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
        def __init__(self):
            super().__init__()
            self.state_calls = 0

        def state(self, number):
            self.state_calls += 1
            if self.state_calls == 1:
                return "OPEN"  # the pre-confirm already_merged check
            raise RuntimeError("gh: pr view failed (rate limited)")

        def merge(self, number):
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
            # call 1 = the pre-confirm already_merged check; call 2 = the
            # FIRST retry-loop read. Both succeed and say OPEN. Every read
            # after that (covering merge attempts 2-5) fails.
            if self.state_calls <= 2:
                return "OPEN"
            raise RuntimeError("gh: pr view failed (rate limited)")

        def merge(self, number):
            self.calls.append("merge")
            self.merged = True  # any of attempts 2-5 may have landed...

    lines = []
    kwargs = make_ports(gh=StaleThenUnreadableGh(), out=lines.append)
    assert run(*build(kwargs)) == 1
    text = "\n".join(lines).lower()
    assert "unchanged" not in text
    assert "unknown" in text
    assert "gh pr view" in text


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


def test_unknown_live_commit_degrades_instead_of_hanging():
    """No Railway env var: don't wait forever, warn and smoke anyway."""
    def fetch(method, url):
        if url.endswith("/api/health"):
            return 200, json.dumps({"status": "ok", "commit": "unknown"}, separators=COMPACT)
        if url.endswith("/api/auth/test-login"):
            return 404, ""
        if "analytics" in url:
            return 401, ""
        return 200, "<html>"

    lines = []
    kwargs = make_ports(fetch=fetch, out=lines.append)
    assert run(*build(kwargs)) == 0
    assert "unknown" in "\n".join(lines).lower()
