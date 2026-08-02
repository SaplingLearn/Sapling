"""Direct coverage for promotion/__main__.py's real-IO glue (#516).

Most of __main__.py is real-IO glue (subprocess/psycopg) that stays
deliberately untested per the coordinator's explicit deferral in
task-5-report.md. Two seams are the exception, both faked rather than
shelling/reading out to the real world:

- `Gh.ensure_pr`'s `--state open` filter is the exact line whose earlier
  regression (`--state all`) silently returned a PREVIOUS promotion's
  already-MERGED PR, which the runner then read as "resume here, skip the
  confirm" — bypassing the only human confirmation gate this tool has, with
  CI staying green the whole time.
- `_confirm`'s EOFError handling: `input()` raises EOFError on non-interactive
  stdin, and `str(EOFError())` is empty, so letting it propagate used to make
  `main()` print a bare "ERROR: " right after the migration had already
  applied — the exact moment a clear message matters most.
"""
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
