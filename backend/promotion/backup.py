"""Full `pg_dump` backups of an environment's database (Trov #114).

Production and staging run on the Supabase Free plan: there are NO platform
backups and NO point-in-time recovery. A migration that goes wrong on
production is unrecoverable unless someone dumped the database first, so
`make promote` takes a dump here BEFORE it applies any migration, and refuses
to continue if the dump fails or does not look like a real archive. The same
code backs `make backup-db ENV=<staging|prod|local>` for a manual dump.

    venv/bin/python -m promotion.backup --env prod     # reads SUPABASE_DB_URL

The dump is schema AND data, custom format (`pg_dump -Fc`) so `pg_restore`
can restore selectively (one table, schema only, data only). See
promotion/README.md "Backups" for where dumps go and how to restore.

Tool selection — this host has no `pg_dump` (no client tools at all), so:

1. a host `pg_dump` whose major version is >= the server's (pg_dump refuses
   to dump a NEWER server, and dumps an older one fine), else
2. `pg_dump` run inside a container (podman, else docker) from the first
   image in CONTAINER_IMAGES whose major is >= the server's, preferring one
   already pulled locally and then the LOWEST eligible major: `pg_restore`
   must be at least as new as the `pg_dump` that wrote the archive, so the
   closest major keeps the dump restorable by the widest set of clients.

The container writes the archive to STDOUT, which this process streams into
the file — no bind mount, so no rootless-UID or SELinux-label issues, and the
same code path serves host and container.

Secrets: the URL's password never reaches a command line (`ps` shows argv).
It is stripped from the URI passed to `--dbname` and handed over as
`PGPASSWORD` in the child's environment (`-e PGPASSWORD`, name only, for the
container). Every message this module prints uses the masked URL, and any
tool stderr echoed back is scrubbed of the password first.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote, urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[2]
# Repo-root `backups/`, gitignored (`/backups/` in .gitignore). Dumps hold
# production data: never commit one.
BACKUP_DIR = REPO_ROOT / "backups"

ENVS = ("prod", "staging", "local")

# A custom-format archive always starts with this magic.
DUMP_MAGIC = b"PGDMP"
# Smaller than this is not a real database: even an empty PG15 database dumps
# to a few KB of TOC. Production's is megabytes.
MIN_DUMP_BYTES = 1024

DUMP_TIMEOUT_S = 30 * 60
LIST_TIMEOUT_S = 5 * 60
PROBE_TIMEOUT_S = 60

# (image, pg_dump major), ascending major. The Supabase images are the ones
# the local stack already pulls (scripts/e2e-up.sh, db reset); the official
# postgres images are the pull-on-demand fallback for a newer server.
CONTAINER_IMAGES: tuple[tuple[str, int], ...] = (
    ("public.ecr.aws/supabase/postgres:15.8.1.085", 15),
    ("public.ecr.aws/supabase/postgres:17.6.1.171", 17),
    ("docker.io/library/postgres:17", 17),
    ("docker.io/library/postgres:18", 18),
)
CONTAINER_RUNTIMES = ("podman", "docker")

_VERSION_RE = re.compile(r"\(PostgreSQL\)\s+(\d+)")

Runner = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], "str | None"]


class BackupError(RuntimeError):
    """The backup did not produce a trustworthy archive. Callers must stop."""


# ---------------------------------------------------------------- URL / secrets


@dataclass(frozen=True)
class Target:
    """A DB URL split so the password can travel out-of-band."""

    dsn: str  # the URI with the password removed — safe for argv
    password: str | None  # decoded; goes to PGPASSWORD, never argv
    display: str  # masked, safe to print

    def scrub(self, text: str) -> str:
        """Remove the password (raw and URL-encoded) from tool output."""
        if not self.password:
            return text
        for secret in {self.password, quote(self.password, safe="")}:
            if secret:
                text = text.replace(secret, "***")
        return text


def _netloc(user: str | None, password: str | None, host: str | None, port: int | None) -> str:
    auth = ""
    if user is not None:
        auth = user + (f":{password}" if password is not None else "") + "@"
    hostpart = host or ""
    if ":" in hostpart:  # IPv6 literal
        hostpart = f"[{hostpart}]"
    return auth + hostpart + (f":{port}" if port is not None else "")


def split_url(url: str) -> Target:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise BackupError(f"not a postgres:// URL: {mask_url(url)}")
    # urlparse leaves the userinfo percent-encoded; libpq decodes it inside a
    # URI, so the username stays encoded in `dsn` while PGPASSWORD (not a URI)
    # needs the decoded value.
    raw_user = parsed.username
    raw_password = parsed.password
    host, port = parsed.hostname, parsed.port
    no_secret = parsed._replace(netloc=_netloc(raw_user, None, host, port))
    masked = parsed._replace(
        netloc=_netloc(raw_user, "***" if raw_password is not None else None, host, port)
    )
    return Target(
        dsn=urlunparse(no_secret),
        password=unquote(raw_password) if raw_password is not None else None,
        display=urlunparse(masked),
    )


def mask_url(url: str) -> str:
    """`postgresql://user:***@host:port/db` — never the password. Falls back
    to a fixed placeholder for anything unparseable rather than echo it."""
    try:
        parsed = urlparse(url.strip())
        if not parsed.hostname:
            return "<unparseable database URL>"
        password = "***" if parsed.password is not None else None
        return urlunparse(
            parsed._replace(netloc=_netloc(parsed.username, password, parsed.hostname, parsed.port))
        )
    except ValueError:
        return "<unparseable database URL>"


def is_loopback(url: str) -> bool:
    host = (urlparse(url.strip()).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_env_matches(env: str, url: str) -> None:
    """Refuse a dump whose label would lie about its contents: `local` must be
    a loopback database and `prod`/`staging` must not be. A production dump
    filed as `local-*.dump` (or a laptop DB filed as `prod-*`) is exactly the
    mix-up that makes a restore go wrong."""
    if env not in ENVS:
        raise BackupError(f"unknown env {env!r}; expected one of {', '.join(ENVS)}")
    loopback = is_loopback(url)
    if env == "local" and not loopback:
        raise BackupError(f"--env local but the database is not on this machine ({mask_url(url)})")
    if env != "local" and loopback:
        raise BackupError(f"--env {env} but the database is a loopback address ({mask_url(url)})")


# ---------------------------------------------------------------- tool selection


def parse_major(version_output: str) -> int | None:
    """`pg_dump (PostgreSQL) 16.4` -> 16."""
    match = _VERSION_RE.search(version_output or "")
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class Tool:
    """Where pg_dump/pg_restore run: on the host, or inside `image`."""

    kind: str  # "host" | "container"
    major: int
    runtime: str | None = None  # podman | docker (container only)
    image: str | None = None  # (container only)
    pg_dump: str = "pg_dump"  # resolved host path (host only)
    pg_restore: str = "pg_restore"

    def describe(self) -> str:
        if self.kind == "host":
            return f"host pg_dump {self.major} ({self.pg_dump})"
        return f"{self.runtime} {self.image} (pg_dump {self.major})"

    def _container(self, entrypoint: str, *, stdin: bool) -> list[str]:
        # --network host: the target may be a loopback DB (local stack, the
        # proof container) as well as a remote pooler; host networking reaches
        # both. -e PGPASSWORD passes the NAME only — the value comes from this
        # process's child environment, so it is never on argv.
        cmd = [self.runtime or "podman", "run", "--rm"]
        if stdin:
            cmd.append("-i")
        cmd += [
            "--network",
            "host",
            "-e",
            "PGPASSWORD",
            "--entrypoint",
            entrypoint,
            self.image or "",
        ]
        return cmd

    def dump_cmd(self, dsn: str) -> list[str]:
        """Full database, schema + data, custom format, to stdout."""
        args = ["--format=custom", "--no-password", "--dbname", dsn]
        if self.kind == "host":
            return [self.pg_dump, *args]
        return [*self._container("pg_dump", stdin=False), *args]

    def list_cmd(self) -> list[str]:
        """`pg_restore --list` reading the archive from stdin."""
        if self.kind == "host":
            return [self.pg_restore, "--list"]
        return [*self._container("pg_restore", stdin=True), "--list"]


def _host_major(which: Which, run: Runner) -> tuple[str | None, str | None, int | None]:
    pg_dump, pg_restore = which("pg_dump"), which("pg_restore")
    if not pg_dump or not pg_restore:
        return pg_dump, pg_restore, None
    try:
        result = run(
            [pg_dump, "--version"], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return pg_dump, pg_restore, None
    return pg_dump, pg_restore, parse_major(result.stdout) if result.returncode == 0 else None


def _image_present(runtime: str, image: str, run: Runner) -> bool:
    try:
        result = run(
            [runtime, "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=PROBE_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def select_tool(
    server_major: int, *, which: Which = shutil.which, run: Runner = subprocess.run
) -> Tool:
    pg_dump, pg_restore, host_major = _host_major(which, run)
    if pg_dump and pg_restore and host_major is not None and host_major >= server_major:
        return Tool(kind="host", major=host_major, pg_dump=pg_dump, pg_restore=pg_restore)

    if not pg_dump:
        host_note = "no host pg_dump"
    elif not pg_restore:
        host_note = "host pg_dump but no pg_restore"
    elif host_major is None:
        host_note = f"host {pg_dump} reported no version"
    else:
        host_note = f"host pg_dump {host_major} is older than the server ({server_major})"

    runtime = next((name for name in CONTAINER_RUNTIMES if which(name)), None)
    if runtime is None:
        raise BackupError(
            f"no usable pg_dump: {host_note}, and neither podman nor docker is "
            f"installed for the container fallback. Install PostgreSQL {server_major}+ "
            "client tools or a container runtime."
        )
    eligible = [(image, major) for image, major in CONTAINER_IMAGES if major >= server_major]
    if not eligible:
        raise BackupError(
            f"no usable pg_dump: {host_note}, and no known container image ships "
            f"pg_dump >= {server_major} (CONTAINER_IMAGES in promotion/backup.py)."
        )
    image, major = next(
        ((img, mj) for img, mj in eligible if _image_present(runtime, img, run)),
        eligible[0],  # none pulled yet: the run pulls the closest major
    )
    return Tool(kind="container", major=major, runtime=runtime, image=image)


def server_major(url: str) -> int:
    """The server's major version, read over a real connection (psycopg is the
    driver db.migrate already uses)."""
    import psycopg  # lazy: the pure helpers above are importable without it

    try:
        with psycopg.connect(url, connect_timeout=20) as conn:
            return conn.info.server_version // 10000
    except psycopg.Error as exc:
        target = split_url(url)
        raise BackupError(
            f"could not connect to {target.display} to read its version: {target.scrub(str(exc))}"
        ) from exc


# ---------------------------------------------------------------- the backup


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size_bytes: int
    tool: str
    toc_entries: int

    def summary(self) -> str:
        return f"{self.path} ({human_size(self.size_bytes)}, {self.toc_entries} TOC entries) via {self.tool}"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    size, unit = n / 1024, "KiB"
    for bigger in ("MiB", "GiB"):
        if size < 1024:
            break
        size, unit = size / 1024, bigger
    return f"{size:.1f} {unit}"


def _stderr_tail(stderr: bytes | str | None, target: Target, limit: int = 2000) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    text = target.scrub((stderr or "").strip())
    return text[-limit:] if text else "(no stderr)"


def _child_env(target: Target) -> dict[str, str]:
    env = dict(os.environ)
    if target.password is not None:
        env["PGPASSWORD"] = target.password
    return env


def _validate(path: Path, tool: Tool, target: Target, run: Runner) -> int:
    """Fail unless `path` is a non-trivial, readable custom-format archive
    that actually contains table data. Returns the TOC entry count."""
    size = path.stat().st_size
    if size < MIN_DUMP_BYTES:
        raise BackupError(
            f"the dump is implausibly small ({size} bytes < {MIN_DUMP_BYTES}); refusing to trust it"
        )
    with path.open("rb") as fh:
        if fh.read(len(DUMP_MAGIC)) != DUMP_MAGIC:
            raise BackupError("the dump is not a pg_dump custom-format archive (bad magic)")
    try:
        with path.open("rb") as fh:
            listed = run(
                tool.list_cmd(),
                stdin=fh,
                capture_output=True,
                timeout=LIST_TIMEOUT_S,
                env=_child_env(target),
            )
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f"`pg_restore --list` timed out after {LIST_TIMEOUT_S}s") from exc
    except OSError as exc:
        raise BackupError(f"could not run pg_restore to verify the dump: {exc}") from exc
    if listed.returncode != 0:
        raise BackupError(
            f"`pg_restore --list` rejected the dump ({listed.returncode}): {_stderr_tail(listed.stderr, target)}"
        )
    toc = (
        listed.stdout.decode("utf-8", "replace")
        if isinstance(listed.stdout, bytes)
        else (listed.stdout or "")
    )
    entries = [line for line in toc.splitlines() if line and not line.startswith(";")]
    if not any(" TABLE DATA " in line for line in entries):
        raise BackupError(
            "the dump lists no TABLE DATA entries — it holds no table contents; refusing to trust it"
        )
    return len(entries)


def take_backup(
    url: str,
    env: str,
    *,
    out_dir: Path = BACKUP_DIR,
    server_major_of: Callable[[str], int] = server_major,
    which: Which = shutil.which,
    run: Runner = subprocess.run,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    out: Callable[[str], None] = print,
) -> BackupResult:
    """Dump `url` to `<out_dir>/<env>-<UTC stamp>.dump` and validate it.

    Raises BackupError on any failure; the partial file is removed so a
    failed run never leaves something that looks like a backup behind.
    """
    if env not in ENVS:
        raise BackupError(f"unknown env {env!r}; expected one of {', '.join(ENVS)}")
    target = split_url(url)
    major = server_major_of(url)
    tool = select_tool(major, which=which, run=run)
    out(f"Backing up {target.display} (PostgreSQL {major}) with {tool.describe()} ...")

    if not out_dir.exists():
        out_dir.mkdir(parents=True, mode=0o700)  # owner-only: dumps hold real data
    stamp = now().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = out_dir / f"{env}-{stamp}.dump"
    partial = out_dir / f"{env}-{stamp}.dump.partial"
    if final.exists():
        raise BackupError(f"{final} already exists; refusing to overwrite a backup")
    try:
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise BackupError(f"could not create {partial}: {exc}") from exc

    try:
        with os.fdopen(fd, "wb") as fh:
            try:
                result = run(
                    tool.dump_cmd(target.dsn),
                    stdout=fh,
                    stderr=subprocess.PIPE,
                    timeout=DUMP_TIMEOUT_S,
                    env=_child_env(target),
                )
            except subprocess.TimeoutExpired as exc:
                raise BackupError(f"pg_dump timed out after {DUMP_TIMEOUT_S}s") from exc
            except OSError as exc:
                raise BackupError(f"could not start pg_dump: {exc}") from exc
        if result.returncode != 0:
            raise BackupError(
                f"pg_dump failed ({result.returncode}): {_stderr_tail(result.stderr, target)}"
            )
        entries = _validate(partial, tool, target, run)
        partial.rename(final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return BackupResult(
        path=final, size_bytes=final.stat().st_size, tool=tool.describe(), toc_entries=entries
    )


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="promotion.backup",
        description="pg_dump (custom format, schema + data) of the database in SUPABASE_DB_URL.",
    )
    parser.add_argument(
        "--env", required=True, choices=ENVS, help="label for the dump file; must match the URL"
    )
    parser.add_argument("--out-dir", type=Path, default=BACKUP_DIR, help=f"default: {BACKUP_DIR}")
    args = parser.parse_args(argv)

    url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not url:
        print(
            "ERROR: SUPABASE_DB_URL is not set. Use `make backup-db ENV=<staging|prod|local>`, "
            "which loads the right env file.",
            file=sys.stderr,
        )
        return 1
    try:
        check_env_matches(args.env, url)
        result = take_backup(url, args.env, out_dir=args.out_dir)
    except BackupError as exc:
        print(f"BACKUP FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Backup written: {result.summary()}")
    print("  It holds this environment's data — keep it private and never commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
