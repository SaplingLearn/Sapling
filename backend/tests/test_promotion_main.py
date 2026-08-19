"""Direct coverage for promotion/__main__.py's real-IO glue (#516).

`__main__.py` wraps real IO (subprocess/psycopg), but every seam that
matters is reachable hermetically by monkeypatching the ONE library call at
the boundary (`subprocess.run`, `psycopg.connect`, `builtins.input`) rather
than shelling/reading out to the real world. No process is spawned and no
database is contacted by anything in this file.

- `Gh.ensure_pr`'s `--state open` filter is the exact line whose earlier
  regression (`--state all`) silently returned a PREVIOUS promotion's
  already-MERGED PR, which the runner then read as "resume here, skip the
  confirm" — bypassing the only human confirmation gate this tool has, with
  CI staying green the whole time.
- `Gh.ensure_pr`'s create-stdout parsing: `gh pr create` prints the new PR's
  URL, the one immediately-consistent source of the number. The `gh pr list`
  re-query is only a bounded fallback — the list endpoint can lag creation by
  seconds, and a single immediate miss used to fail the run AFTER production's
  migrations had already irreversibly applied.
- `_confirm`'s EOFError handling: `input()` raises EOFError on non-interactive
  stdin, and `str(EOFError())` is empty, so letting it propagate used to make
  `main()` print a bare "ERROR: " right after the migration had already
  applied — the exact moment a clear message matters most.
- `_confirm`'s KeyboardInterrupt handling: Ctrl-C at the prompt is a
  BaseException that `main()`'s `except Exception` never catches, so it used
  to escape as a raw traceback instead of the runner's ABORTED report.
- `_run`'s subprocess timeout: every caller (`git fetch`, `gh pr
  create`/`view`/`merge`) is a network call: a future edit that silently
  drops the `timeout` kwarg reintroduces a hang that can strand a promotion
  AFTER the migration has applied, with CI staying green throughout.
- `_staging_recorded`'s degrade-not-abort behavior: a stale URI, a paused
  staging project, or a transient network fault must produce the documented
  `staging-unknown` preflight finding, not abort the whole run before the
  operator ever sees a report.
"""
import subprocess

import psycopg
import pytest

import promotion.__main__ as promotion_main


def test_ensure_pr_only_ever_returns_an_open_pr_never_a_merged_one(monkeypatch):
    """Fixture shaped like this repo's real regression: PR #515 (base=
    production, head=main) is MERGED from a previous promotion. A correct
    `--state open` query for that pair finds nothing, so ensure_pr creates a
    new PR and the SECOND `--state open` re-query discovers it as #999.

    If ensure_pr regressed to `--state all` (or dropped the flag), the FIRST
    query would itself return 515 — the merged PR from last time — and
    ensure_pr would hand it straight back without ever calling `gh pr create`.
    """
    calls: list[list[str]] = []
    created: list[int] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            assert "--state" in cmd, f"ensure_pr must filter by --state: {cmd}"
            state = cmd[cmd.index("--state") + 1]
            assert state == "open", f"ensure_pr must use --state open, got {state!r}: {cmd}"
            if created:
                return "999"  # the PR just created below, now open
            return ""  # PR #515 is MERGED, not open — correctly invisible here
        if cmd[:3] == ["gh", "pr", "create"]:
            created.append(1)
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    number = promotion_main.Gh().ensure_pr("production", "main", "Promote staging to production")

    assert number == 999
    assert number != 515  # never the stale merged PR from a previous promotion
    assert created == [1]  # a new PR really was created, not silently skipped
    list_calls = [c for c in calls if c[:3] == ["gh", "pr", "list"]]
    assert len(list_calls) == 2  # one miss, one re-query after create — no recursion


def test_ensure_pr_takes_the_number_from_create_stdout(monkeypatch):
    """`gh pr create` prints the new PR's URL on stdout — the one
    immediately-consistent source of the number. `gh pr list` can lag
    creation by seconds, and a miss there used to exit 1 AFTER production's
    migrations had already irreversibly applied. When create's output parses,
    the laggy list endpoint must not be consulted again at all.
    """
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return ""
        if cmd[:3] == ["gh", "pr", "create"]:
            return "https://github.com/owner/sapling/pull/1234"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    number = promotion_main.Gh().ensure_pr("production", "main", "Promote staging to production")

    assert number == 1234
    assert len([c for c in calls if c[:3] == ["gh", "pr", "list"]]) == 1  # no re-query


def test_ensure_pr_parsing_tolerates_extra_lines_and_whitespace(monkeypatch):
    """gh mixes progress/warning lines into its output, and only the LAST
    /pull/<n>-shaped URL is the created PR — a compare URL or any other link
    earlier in the output must not be mistaken for it.
    """

    def fake_run(cmd: list[str]) -> str:
        if cmd[:3] == ["gh", "pr", "list"]:
            return ""
        if cmd[:3] == ["gh", "pr", "create"]:
            return (
                "Warning: 2 uncommitted changes\n"
                "Creating pull request for main into production in owner/sapling\n"
                "https://github.com/owner/sapling/compare/production...main\n"
                "\n"
                "https://github.com/owner/sapling/pull/1234 \n"
            )
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    number = promotion_main.Gh().ensure_pr("production", "main", "Promote staging to production")

    assert number == 1234


def test_ensure_pr_falls_back_to_bounded_list_retry_when_stdout_is_unparseable(monkeypatch):
    """If gh's output shape ever changes and no /pull/<n> URL parses, the
    list re-query remains — but bounded and retried through the injected
    sleep, because the list endpoint can lag creation by seconds and a single
    immediate miss used to fail the run AFTER the migration had applied.
    Never a second create: guessing again would just open PRs in a loop.
    """
    calls: list[list[str]] = []
    sleeps: list[float] = []
    list_results = iter(["", "", "", "999"])  # initial miss, then lag, lag, found

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return next(list_results)
        if cmd[:3] == ["gh", "pr", "create"]:
            return "pull request created"  # no URL anywhere
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    number = promotion_main.Gh(sleep=sleeps.append).ensure_pr(
        "production", "main", "Promote staging to production"
    )

    assert number == 999
    assert len(sleeps) == 2  # no sleep before the first fallback attempt
    assert len([c for c in calls if c[:3] == ["gh", "pr", "create"]]) == 1


def test_ensure_pr_raises_after_exhausting_the_bounded_fallback(monkeypatch):
    """The fallback retry is bounded: when every re-query misses, the run
    must still end in the clear "did not produce a discoverable open PR"
    error rather than polling forever or creating another PR.
    """
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[:3] == ["gh", "pr", "list"]:
            return ""
        if cmd[:3] == ["gh", "pr", "create"]:
            return "pull request created"  # no URL anywhere
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        promotion_main.Gh(sleep=lambda _s: None).ensure_pr(
            "production", "main", "Promote staging to production"
        )

    assert "discoverable" in str(exc_info.value)
    assert len([c for c in calls if c[:3] == ["gh", "pr", "create"]]) == 1
    assert len([c for c in calls if c[:3] == ["gh", "pr", "list"]]) == 4  # initial + 3 retries


def test_ensure_pr_returns_an_already_open_pr_without_creating(monkeypatch):
    """The pre-create path is untouched by the stdout parsing: an already
    open PR for the pair is returned from the first list query alone.
    """

    def fake_run(cmd: list[str]) -> str:
        if cmd[:3] == ["gh", "pr", "list"]:
            return "42"
        raise AssertionError(f"only the initial list query may run: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    assert promotion_main.Gh().ensure_pr("production", "main", "t") == 42


def test_confirm_treats_eof_as_declined(monkeypatch):
    """Non-interactive stdin (no controlling terminal, a closed pipe, CI
    running this without a tty) raises EOFError from input(). Must degrade
    to a normal decline (False), not propagate and blank out the error
    message main() would otherwise print.
    """

    def raise_eof(prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert promotion_main._confirm("Merge?", auto_yes=False) is False


def test_confirm_treats_ctrl_c_as_declined(monkeypatch, capsys):
    """Ctrl-C at the prompt raises KeyboardInterrupt — a BaseException that
    main()'s `except Exception` never catches, so it used to escape as a raw
    traceback and skip the runner's ABORTED report (the one that says the
    migrations are ALREADY APPLIED). Must degrade to a decline like EOF, with
    a leading newline so the terminal's ^C echo doesn't mangle the report's
    first line.
    """

    def raise_interrupt(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", raise_interrupt)
    assert promotion_main._confirm("Merge?", auto_yes=False) is False
    assert capsys.readouterr().out == "\n"


def test_confirm_auto_yes_never_touches_input(monkeypatch):
    """--yes must short-circuit before input() is even called — including
    under EOF conditions, which is exactly the CI scenario --yes exists for.
    """

    def raise_if_called(prompt):
        raise AssertionError("input() must not be called when auto_yes is True")

    monkeypatch.setattr("builtins.input", raise_if_called)
    assert promotion_main._confirm("Merge?", auto_yes=True) is True


def test_run_passes_a_timeout_to_subprocess(monkeypatch):
    """A future edit that silently drops the `timeout` kwarg reintroduces the
    hang this fix closes: a stalled git/gh network call, or `gh` sitting on
    an interactive prompt, blocking forever — possibly AFTER the migration
    has already applied, with CI staying green the whole time.
    """
    recorded_kwargs: dict = {}

    def fake_subprocess_run(cmd, **kwargs):
        recorded_kwargs.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(promotion_main.subprocess, "run", fake_subprocess_run)

    promotion_main._run(["git", "fetch"])

    assert recorded_kwargs.get("timeout") is not None


def test_run_converts_timeout_expired_to_a_clean_runtime_error(monkeypatch):
    """A raw subprocess.TimeoutExpired must not propagate — every other
    _run failure surfaces as a RuntimeError naming the command, and a
    timeout is no exception to that discipline.
    """

    def fake_subprocess_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(promotion_main.subprocess, "run", fake_subprocess_run)

    with pytest.raises(RuntimeError) as exc_info:
        promotion_main._run(["git", "fetch"])
    text = str(exc_info.value).lower()
    assert "git fetch" in text
    assert "timed out" in text


def test_gh_merge_pins_to_the_given_head_commit(monkeypatch):
    """The merge must carry gh's --match-head-commit so GitHub itself rejects
    a moved main — without it, `gh pr merge --merge` merges whatever the tip
    is at merge time, promoting confirm-pause commits unscanned. (Flag
    verified against the gh CLI in PATH: `gh pr merge --help` documents
    `--match-head-commit SHA`.)
    """
    cmds: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        cmds.append(cmd)
        return ""

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    promotion_main.Gh().merge(999, "abc1234def")

    [cmd] = cmds
    assert cmd[:4] == ["gh", "pr", "merge", "999"]
    assert "--merge" in cmd
    assert cmd[cmd.index("--match-head-commit") + 1] == "abc1234def"


def test_git_migrations_drift_combines_tracked_diff_and_untracked_status(monkeypatch):
    """The guard needs BOTH reads: `git diff --name-status origin/main` sees
    tracked files differing in content or presence (either direction) but is
    blind to untracked strays; `git status --porcelain` sees the strays but
    reports nothing for a checkout that is merely on an old commit. Each must
    be scoped to the migrations dir, and both outputs must surface so the
    blocking finding can name the offending files.
    """
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        if cmd[:2] == ["git", "diff"]:
            assert "--name-status" in cmd and "origin/main" in cmd
            return "M\tbackend/db/migrations/0002_b.sql"
        if cmd[:2] == ["git", "status"]:
            assert "--porcelain" in cmd
            return "?? backend/db/migrations/0099_stray.sql"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(promotion_main, "_run", fake_run)

    drift = promotion_main.Git().migrations_drift()

    assert "0002_b.sql" in drift and "0099_stray.sql" in drift
    assert len(calls) == 2
    for cmd in calls:
        # pathspec-scoped to the migrations dir, behind the `--` separator
        sep = cmd.index("--")
        assert cmd[sep + 1].endswith("migrations")


def test_git_migrations_drift_is_empty_when_clean(monkeypatch):
    monkeypatch.setattr(promotion_main, "_run", lambda cmd: "")
    assert promotion_main.Git().migrations_drift() == ""


def test_git_is_ancestor_maps_exit_codes_and_fails_closed(monkeypatch):
    """`git merge-base --is-ancestor` speaks in exit codes: 0 = ancestor,
    1 = not an ancestor, anything else = a real error (bad ref, not a repo).
    _run would collapse exit 1 into a failure, so this port reads the code
    itself — and an unexpected code must RAISE (fail closed), never be read
    as either answer.
    """
    returncode = 0

    def fake_subprocess_run(cmd, **kwargs):
        assert cmd[:3] == ["git", "merge-base", "--is-ancestor"]
        assert kwargs.get("timeout") is not None  # same no-hang discipline as _run
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr="fatal: bad ref")

    monkeypatch.setattr(promotion_main.subprocess, "run", fake_subprocess_run)

    git = promotion_main.Git()
    assert git.is_ancestor("origin/production", "origin/main") is True
    returncode = 1
    assert git.is_ancestor("origin/production", "origin/main") is False
    returncode = 128
    with pytest.raises(RuntimeError, match="bad ref"):
        git.is_ancestor("origin/production", "origin/main")


def test_preflight_data_reads_the_ledger_through_the_shared_primitives(monkeypatch):
    """_preflight_data's ledger reads must behave exactly like the shared
    promotion.preflight primitives the drift report consumes (#317/#516) —
    the inline cursor code it used to carry is the re-implementation pattern
    that let the two drift apart before. Behavioral pin: existence flag and
    recorded set come through the shared reads, and a fully-recorded ledger
    yields no pending work (so no destructive scan fires).
    """
    from db import migrate as db_migrate

    all_files = {p.name for p in db_migrate.discover_migrations(db_migrate.MIGRATIONS_DIR)}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (True,)

        def fetchall(self):
            return [(name,) for name in sorted(all_files)]

    class Conn:
        def cursor(self):
            return Cursor()

    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres.ref1:p@aws-0-us-west-2.pooler.supabase.com:5432/postgres",
    )
    monkeypatch.setenv("SUPABASE_URL", "https://ref1.supabase.co")
    monkeypatch.delenv("STAGING_SUPABASE_DB_URL", raising=False)

    data = promotion_main._preflight_data(Conn())

    assert data["ledger_exists"] is True
    assert data["recorded"] == all_files
    assert data["destructive"] == []  # nothing pending -> nothing scanned


def test_staging_recorded_degrades_to_none_on_connection_failure(monkeypatch, capsys):
    """A stale STAGING_SUPABASE_DB_URL, a paused staging project, or a
    transient network fault must not abort the whole run before the operator
    ever sees a preflight report — it must degrade to the same "unknown"
    signal as the var being unset (None), not re-raise, and the reason must
    still be surfaced (not silently swallowed).
    """
    monkeypatch.setenv(
        "STAGING_SUPABASE_DB_URL",
        "postgresql://postgres.stg:pw@aws-1-us-west-2.pooler.supabase.com:5432/postgres",
    )

    def fake_connect(url):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(promotion_main.psycopg, "connect", fake_connect)

    result = promotion_main._staging_recorded()

    assert result is None
    captured = capsys.readouterr()
    assert "connection refused" in captured.err
