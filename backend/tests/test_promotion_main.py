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
- `_confirm`'s EOFError handling: `input()` raises EOFError on non-interactive
  stdin, and `str(EOFError())` is empty, so letting it propagate used to make
  `main()` print a bare "ERROR: " right after the migration had already
  applied — the exact moment a clear message matters most.
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
