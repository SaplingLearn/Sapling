"""Stage sequencing for the staging -> production promotion (#516).

Ordering is DB-first: migrations apply BEFORE the code merges, which is what the
destructive-DDL guard in preflight exists to protect. Between the migrate stage
and the merge, the OLD production code runs against the NEW schema.

Every side effect is an injected port, so the whole sequence is testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from promotion import preflight, smoke, snapshot

EXIT_OK, EXIT_FAIL, EXIT_ABORTED = 0, 1, 2


@dataclass
class Ports:
    connect: Callable[[], Any]
    preflight_data: Callable[[Any], dict]
    capture: Callable[[Any], dict]
    migrate: Callable[[Any], list[str]]
    git: Any
    gh: Any
    fetch: Callable[[str, str], tuple[int | None, str]]
    confirm: Callable[[str], bool]
    out: Callable[[str], None]
    sleep: Callable[[float], None]


@dataclass
class Options:
    allow_destructive: bool = False
    skip_staging_check: bool = False
    api_base: str = smoke.DEFAULT_API
    web_base: str = smoke.DEFAULT_WEB
    wait_timeout: int = 600
    poll_interval: int = 10
    # Skip preflight/snapshot/migrate/PR/merge entirely and just wait-then-smoke
    # against production's CURRENT tip. This is the real resume path: a re-run
    # after a merge cannot resume by re-running preflight, because by then
    # commits_ahead is 0 and nothing is pending, so preflight would report
    # nothing-to-promote and exit clean before ever reaching the wait.
    verify_only: bool = False


def _wait_for_deploy(ports: Ports, options: Options, target: str, out: Callable[[str], None]) -> bool:
    """Poll /api/health until it reports `target`. True on success (or a
    degraded-but-proceeding 'unknown'), False on timeout."""
    waited = 0
    # Advance by at least 1 per iteration. poll_interval is 0 in tests (so they
    # don't actually sleep), and incrementing by it directly would leave `waited`
    # pinned at 0 — an infinite loop on the very timeout path the tests exist to
    # cover.
    tick = max(options.poll_interval, 1)
    while waited < options.wait_timeout:
        live = smoke.live_commit(ports.fetch, options.api_base)
        if live == target[:7]:
            out(f"  deploy is live ({live}).")
            return True
        if live == "unknown":
            out(
                "  WARNING: /api/health reports commit 'unknown' — the host is not "
                "injecting a commit SHA, so the deploy cannot be confirmed. "
                "Proceeding to smoke anyway."
            )
            return True
        ports.sleep(options.poll_interval)
        waited += tick
    out(
        f"\nTIMEOUT: the deploy never reported {target[:7]} after "
        f"{options.wait_timeout}s. NOT running smoke — a deploy failure must "
        "not look like a smoke failure. Check the Railway build."
    )
    return False


def _run_smoke(
    ports: Ports, options: Options, out: Callable[[str], None], *, merged_this_run: bool = True
) -> int:
    """`merged_this_run=False` is the migrations-only path (run()'s
    `commits_ahead == 0` branch): no PR was merged, so production's git HEAD
    is a PREVIOUS promotion's merge commit, unrelated to this run. The default
    revert recipe below is only correct when THIS run merged something —
    telling an operator to `git revert -m 1 HEAD` on that path would revert
    an unrelated, previously-working deploy.
    """
    results = smoke.run_checks(ports.fetch, options.api_base, options.web_base)
    out("\nSmoke:")
    out(smoke.format_results(results))

    if any(not r.ok for r in results):
        if merged_this_run:
            out(
                "\nSMOKE FAILED. Production was NOT reverted — the applied migrations "
                "cannot be rolled back, so reverting the code would leave old code "
                "against a newer schema.\n"
                "  To revert deliberately:\n"
                "    git checkout production && git revert -m 1 HEAD && git push origin production"
            )
        else:
            out(
                "\nSMOKE FAILED. No code was merged this run — production's schema "
                "moved (the migration(s) applied above), but its code was NOT "
                "touched, so there is no code to revert. Production's current git "
                "HEAD is a PREVIOUS promotion's merge commit, unrelated to this "
                "run; undoing it would revert an earlier, previously-working "
                "deploy. Inspect the migration that just landed, not the code."
            )
        return EXIT_FAIL

    out("\nPROMOTION COMPLETE — all smoke checks passed.")
    return EXIT_OK


def _wait_then_smoke(ports: Ports, options: Options, target: str, out: Callable[[str], None]) -> int:
    if not _wait_for_deploy(ports, options, target, out):
        return EXIT_FAIL
    return _run_smoke(ports, options, out)


def run(ports: Ports, options: Options) -> int:
    out = ports.out

    if options.verify_only:
        # No preflight, no migrate, no PR, no merge — just confirm production's
        # CURRENT deploy is live and healthy. See Options.verify_only for why
        # this, not "re-run the whole thing", is the real resume path.
        ports.git.fetch()
        deploy_target = ports.git.head_sha("origin/production")
        out(f"--verify-only: waiting for the deploy to report {deploy_target[:7]}.")
        return _wait_then_smoke(ports, options, deploy_target, out)

    # ---- Stage 1: preflight (read-only) --------------------------------
    ports.git.fetch()
    head = ports.git.head_sha("origin/main")
    commits_ahead = ports.git.commits_ahead_of("origin/production", "origin/main")

    with ports.connect() as conn:
        data = ports.preflight_data(conn)
        findings = preflight.evaluate(
            commits_ahead=commits_ahead,
            allow_destructive=options.allow_destructive,
            skip_staging_check=options.skip_staging_check,
            **data,
        )

        if findings:
            blocking = [f for f in findings if f.kind != "nothing-to-promote"]
            for finding in findings:
                out(f"  [{finding.kind}] {finding.detail}")
            if not blocking:
                out("Nothing to promote — production already matches main.")
                return EXIT_OK
            out("\nPREFLIGHT FAILED — production was not touched.")
            return EXIT_FAIL

        pending, _ = preflight.ledger_diff(data["migration_files"], data["recorded"])
        out(
            f"Preflight OK. {commits_ahead} commit(s) to promote (main is at "
            f"{head[:7]}), {len(pending)} migration(s) pending."
        )

        # ---- Stage 2-4: snapshot, migrate, snapshot --------------------
        before = ports.capture(conn)
        out(f"Target: project {preflight.project_ref(data['db_url'])} ({before.get('host', 'unknown')})")

        migrate_error: Exception | None = None
        if pending:
            try:
                applied = ports.migrate(conn)
                out(f"Applied {len(applied)} migration(s).")
            except Exception as exc:  # noqa: BLE001 — reported as an honest partial-state report, never a traceback
                migrate_error = exc

        if migrate_error is None:
            after = ports.capture(conn)

    if migrate_error is not None:
        # apply_migration commits per file, so whatever landed before the
        # failure is durable. Reopen a FRESH connection rather than reuse
        # `conn`: it may be left with an aborted transaction by the failed
        # migration, which would raise again on the very query meant to
        # report what actually happened.
        with ports.connect() as conn2:
            after = ports.capture(conn2)
        changes = snapshot.diff(before, after)
        landed = changes["new_migrations"]
        # Ledger inserts are part of the same per-file transaction as the SQL,
        # so `landed` is exact, not a guess — and when something DID land,
        # apply order is `pending`'s order, so the first pending name NOT in
        # `landed` is provably the one that raised. But when NOTHING landed,
        # that is NOT necessarily pending[0]'s fault: db.migrate.run() has a
        # prologue (SET maintenance_work_mem, ensure_tracking_table) that runs
        # BEFORE any file, and a failure there is indistinguishable from here
        # from a failure on the first file's own SQL. Don't guess a filename
        # in that case.
        failed_name = next((name for name in pending if name not in landed), "unknown") if landed else None
        out(f"\nMIGRATION FAILED after {len(landed)} of {len(pending)} pending migration(s) landed.")
        if failed_name is not None:
            out(f"  Failed on: {failed_name}")
        else:
            out("  Failed before applying any migration (see Error below).")
        out(f"  Error: {migrate_error}")
        if landed:
            out("\nDatabase changes so far:")
            out(snapshot.format_diff(changes))
            out(
                "\n  WARNING: production's schema is now PARTIALLY migrated and "
                "AHEAD of production's code. Production's code was NOT touched. "
                f"Do NOT re-run blindly — inspect {failed_name} and the database "
                "by hand before continuing."
            )
        else:
            out(
                "\n  Production's schema is UNCHANGED — nothing landed — and its "
                "code was NOT touched. Do NOT re-run blindly — inspect the error "
                "above before continuing."
            )
        return EXIT_FAIL

    changes = snapshot.diff(before, after)
    out("\nDatabase changes:")
    out(snapshot.format_diff(changes))

    if commits_ahead == 0:
        # Migrations landed but there is no new code to promote — production's
        # DB can trail its own code (a real, recurring state; see #316/#510).
        # `gh pr create` would fail outright with "No commits between
        # production and main", so skip PR/merge/deploy-wait entirely. Still
        # smoke: a migration that broke the running app is exactly the
        # failure this stage exists to catch.
        out("\nMigrations applied; no code to promote (production and main are level).")
        return _run_smoke(ports, options, out, merged_this_run=False)

    # ---- The one pause ------------------------------------------------
    number = ports.gh.ensure_pr("production", "main", f"Promote staging to production — {commits_ahead} commits")

    prompt = (
        f"\nMerge PR #{number} ({commits_ahead} commits, "
        f"{len(changes['new_migrations'])} migrations applied) into production?"
    )
    if not ports.confirm(prompt):
        out(
            "\nABORTED before the merge.\n"
            "  NOTE: the migrations above are ALREADY APPLIED. Production's "
            "schema is now AHEAD of production's code.\n"
            "  Re-run to resume at the merge, or revert deliberately."
        )
        return EXIT_ABORTED

    # The gh merge 502 wedge: `gh pr merge --merge` is known to return an
    # error (observed: HTTP 502) while the merge actually lands — the merge
    # can land seconds AFTER a read that said OPEN, not just after a read
    # that failed outright. Never trust the first failure — re-read the PR
    # state, and don't trust that read blindly either: a transient failure
    # checking state right after a merge attempt is the worst possible
    # moment to crash the runner.
    #
    # `current_state` is reassigned every iteration (None on a failed read),
    # so by the time the loop exhausts it reflects only the LAST attempt's
    # outcome. But even a successful last read is a snapshot from BEFORE this
    # point, not a guarantee about right now — gh's own 502-while-it-lands
    # wedge means a merge triggered above can still land after every read
    # this run performed. So neither branch below may assert "production is
    # unchanged" as settled fact; both report what was OBSERVED and tell the
    # operator to verify by hand.
    current_state = None
    for attempt in range(5):
        try:
            ports.gh.merge(number)
        except Exception as exc:  # noqa: BLE001 — any gh failure gets re-checked
            out(f"  merge attempt {attempt + 1} errored ({exc}); re-checking PR state")
        try:
            current_state = ports.gh.state(number)
        except Exception as exc:  # noqa: BLE001 — state-read is not trusted blindly either
            out(f"  could not re-check PR state ({exc}); retrying")
            current_state = None
        if current_state == "MERGED":
            break
        ports.sleep(options.poll_interval)
    else:
        if current_state is not None:
            out(
                f"\nPR #{number} never reported MERGED after 5 attempts. As of "
                f"the last check, it was {current_state}. A merge triggered by "
                "this run may still be landing — gh is known to report an "
                "error while a merge lands seconds later. Check "
                f"`gh pr view {number}` before doing anything else, including "
                "re-running this tool. The migrations applied earlier in this "
                "run are ALREADY APPLIED regardless of the merge outcome."
            )
        else:
            # The last `gh pr view` read failed. `gh.merge` may have landed on
            # this or an earlier attempt — this run cannot tell. Saying
            # "production unchanged" here would be exactly the false report
            # this tool exists to prevent.
            out(
                f"\nPR #{number}'s merge outcome is UNKNOWN: the last `gh pr view` "
                "read failed, so this run cannot confirm whether the merge "
                "landed or not. Do not assume either way — check "
                f"`gh pr view {number}` by hand before doing anything else. "
                "The migrations applied earlier in this run are ALREADY "
                "APPLIED regardless of the merge outcome."
            )
        return EXIT_FAIL

    # `gh pr merge --merge` creates a merge commit ON production; Railway
    # deploys production, not main. So the deploy target has to be read from
    # origin/production AFTER a fresh fetch, never from main's tip — main's SHA
    # will never appear in production's history once a merge commit exists.
    ports.git.fetch()
    deploy_target = ports.git.head_sha("origin/production")
    out(f"Merged. Waiting for the deploy to report {deploy_target[:7]}.")

    return _wait_then_smoke(ports, options, deploy_target, out)
