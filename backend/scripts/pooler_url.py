"""Build the SESSION-mode pooler connection string for an environment.

Why this exists: `db.<ref>.supabase.co` publishes only an AAAA record, so a
direct connection is unreachable from any host without global IPv6 — which
includes this laptop and GitHub-hosted runners. The Supavisor pooler hosts
publish A records, so they are the reachable path.

    python scripts/pooler_url.py .env.staging aws-1-us-west-2         # print (masked)
    python scripts/pooler_url.py .env.staging aws-1-us-west-2 --raw   # print usable URI

Pass the pooler host PREFIX, not a bare region: Supabase assigns projects to
numbered pooler clusters (`aws-0-…`, `aws-1-…`) and the number is not derivable
from the region — staging is `aws-1-us-west-2`. A bare region is still accepted
and assumes `aws-0-`, which is a guess; take the prefix from the dashboard's
Connect panel instead. A wrong prefix fails fast and harmlessly with
"Tenant or user not found", which is distinguishable from a bad password
("password authentication failed").

The URI is derived from the password already in the env file, so the secret
never has to be copied by hand. `--raw` is what you feed to db.migrate; without
it the password is masked so the value is safe to look at (and to paste into a
chat or an issue).

SESSION mode is port 5432 — NOT 6543. Transaction mode drops the session-level
behaviour psycopg and DDL rely on. db/migrate.py's "NOT the pooler" warning is
about transaction mode and predates the IPv6-only direct endpoint.

The pooler also requires the username to carry the project ref
(`postgres.<ref>`), which is the detail most easily missed when assembling this
by hand.
"""
from __future__ import annotations

import pathlib
import re
import sys
from urllib.parse import quote, unquote, urlparse

SESSION_PORT = 5432


def pooler_host(prefix: str) -> str:
    """`aws-1-us-west-2` -> full host. A bare region gets the `aws-0-` guess."""
    if prefix.endswith(".pooler.supabase.com"):
        return prefix
    if not prefix.startswith("aws-"):
        prefix = f"aws-0-{prefix}"
    return f"{prefix}.pooler.supabase.com"


def build(env_file: str, region: str) -> str:
    lines = pathlib.Path(env_file).read_text().splitlines()
    matches = [ln for ln in lines if ln.startswith("SUPABASE_DB_URL=")]
    if not matches:
        raise SystemExit(f"{env_file}: no SUPABASE_DB_URL")
    parsed = urlparse(matches[0].split("=", 1)[1].strip())
    if not parsed.password:
        raise SystemExit(f"{env_file}: SUPABASE_DB_URL carries no password")
    host = parsed.hostname or ""
    # db.<ref>.supabase.co -> <ref>
    ref = host.split(".")[1] if host.startswith("db.") else host.split(".")[0]
    # urlparse() hands back the password STILL percent-encoded, so quoting it
    # again double-escapes: a stored `p%40ss` would go out as `p%2540ss` and
    # authenticate as the literal text `p%40ss` rather than `p@ss`. Supabase
    # generates passwords containing reserved characters, so this is reached in
    # practice — and it fails as "password authentication failed", which reads
    # like a wrong secret rather than a broken builder. Decode then re-encode;
    # the round trip is a no-op on an already-correct value.
    pw = quote(unquote(parsed.password), safe="")
    return (
        f"postgresql://postgres.{ref}:{pw}"
        f"@{pooler_host(region)}:{SESSION_PORT}/postgres"
    )


def mask(uri: str) -> str:
    return re.sub(r"://([^:]+):[^@]+@", r"://\1:********@", uri)


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--raw"]
    if len(args) != 2:
        print(__doc__)
        return 2
    uri = build(args[0], args[1])
    print(uri if "--raw" in sys.argv[1:] else mask(uri))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
