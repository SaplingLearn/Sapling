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


def run(ports: Ports, options: Options) -> int:
    out = ports.out

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
        out(f"Preflight OK. {commits_ahead} commit(s) to promote, {len(pending)} migration(s) pending.")

        # ---- Stage 2-4: snapshot, migrate, snapshot --------------------
        before = ports.capture(conn)
        if pending:
            applied = ports.migrate(conn)
            out(f"Applied {len(applied)} migration(s).")
        after = ports.capture(conn)

    changes = snapshot.diff(before, after)
    out("\nDatabase changes:")
    out(snapshot.format_diff(changes))

    # ---- The one pause ------------------------------------------------
    number = ports.gh.ensure_pr("production", "main", f"Promote staging to production — {commits_ahead} commits")
    already_merged = ports.gh.state(number) == "MERGED"

    if not already_merged:
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

        # The squash-merge 502 wedge: gh can error while the merge lands. Never
        # trust the first failure — re-read the PR state.
        for attempt in range(5):
            try:
                ports.gh.merge(number)
            except Exception as exc:  # noqa: BLE001 — any gh failure gets re-checked
                out(f"  merge attempt {attempt + 1} errored ({exc}); re-checking PR state")
            if ports.gh.state(number) == "MERGED":
                break
            ports.sleep(options.poll_interval)
        else:
            out(f"\nPR #{number} never reported MERGED. Production code unchanged.")
            return EXIT_FAIL
    else:
        out(f"PR #{number} is already merged — resuming at the deploy wait.")

    out(f"Merged. Waiting for the deploy to report {head[:7]}.")

    # ---- Stage 6: wait for the deploy ---------------------------------
    waited = 0
    # Advance by at least 1 per iteration. poll_interval is 0 in tests (so they
    # don't actually sleep), and incrementing by it directly would leave `waited`
    # pinned at 0 — an infinite loop on the very timeout path the tests exist to
    # cover.
    tick = max(options.poll_interval, 1)
    while waited < options.wait_timeout:
        live = smoke.live_commit(ports.fetch, options.api_base)
        if live == head[:7]:
            out(f"  deploy is live ({live}).")
            break
        if live == "unknown":
            out(
                "  WARNING: /api/health reports commit 'unknown' — the host is not "
                "injecting a commit SHA, so the deploy cannot be confirmed. "
                "Proceeding to smoke anyway."
            )
            break
        ports.sleep(options.poll_interval)
        waited += tick
    else:
        out(
            f"\nTIMEOUT: the deploy never reported {head[:7]} after "
            f"{options.wait_timeout}s. NOT running smoke — a deploy failure must "
            "not look like a smoke failure. Check the Railway build."
        )
        return EXIT_FAIL

    # ---- Stage 7: smoke ------------------------------------------------
    results = smoke.run_checks(ports.fetch, options.api_base, options.web_base)
    out("\nSmoke:")
    out(smoke.format_results(results))

    if any(not r.ok for r in results):
        out(
            "\nSMOKE FAILED. Production was NOT reverted — the applied migrations "
            "cannot be rolled back, so reverting the code would leave old code "
            "against a newer schema.\n"
            "  To revert deliberately:\n"
            "    git checkout production && git revert -m 1 HEAD && git push origin production"
        )
        return EXIT_FAIL

    out("\nPROMOTION COMPLETE — all smoke checks passed.")
    return EXIT_OK
