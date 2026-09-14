"""Staging → production promotion runner (#516).

Sequences the promotion that used to be a hand-run list of commands: preflight,
snapshot, migrate, confirm, merge, wait for the deploy, smoke.

Each module splits pure logic from IO so the logic is testable without a
database or a network: `preflight` and `snapshot.diff` take plain data,
`smoke.run_checks` takes an injected fetcher, and `runner` takes injected
confirm/output callables.
"""
