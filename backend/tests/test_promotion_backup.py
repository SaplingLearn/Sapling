"""The pre-migrate pg_dump backup (Trov #114) — hermetic.

No process is spawned and no database is contacted: `take_backup` and
`select_tool` take injected `which`/`run`/`server_major_of`, and the fakes
here play pg_dump (writing an archive to the stdout file handle it is given)
and pg_restore --list (reading it back from stdin). The real tools were
exercised once against a throwaway PG15 container (see the PR body).
"""

from __future__ import annotations

import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import promotion.__main__ as promotion_main
from promotion import backup
from promotion.backup import BackupError, Tool, select_tool, split_url, take_backup

SECRET = "s3cr:et@p/w"  # characters that must be percent-encoded in a URI
SECRET_ENC = "s3cr%3Aet%40p%2Fw"
PROD_URL = (
    f"postgresql://postgres.ref1:{SECRET_ENC}@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
)
LOCAL_URL = "postgresql://postgres:postgres@localhost:55439/postgres"

GOOD_ARCHIVE = backup.DUMP_MAGIC + b"\x01" * 4096
TOC = (
    ";\n; Archive created at 2026-11-08\n;\n"
    "3; 2615 2200 SCHEMA - public pg_database_owner\n"
    "220; 1259 16390 TABLE public users postgres\n"
    "3400; 0 16390 TABLE DATA public users postgres\n"
)
FIXED_NOW = datetime(2026, 11, 8, 3, 4, 5, tzinfo=timezone.utc)


class FakeWorld:
    """`which` + `run` for a host with the given tools/images."""

    def __init__(
        self,
        *,
        binaries=("podman",),
        host_version="pg_dump (PostgreSQL) 16.4",
        present_images=(),
        archive=GOOD_ARCHIVE,
        dump_rc=0,
        dump_stderr=b"",
        list_rc=0,
        toc=TOC,
    ):
        self.binaries = set(binaries)
        self.host_version = host_version
        self.present_images = set(present_images)
        self.archive = archive
        self.dump_rc, self.dump_stderr = dump_rc, dump_stderr
        self.list_rc, self.toc = list_rc, toc
        self.calls: list[tuple[list[str], dict]] = []

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.binaries else None

    def run(self, cmd, **kw):
        self.calls.append((list(cmd), kw))
        if cmd[-1] == "--version":
            return subprocess.CompletedProcess(cmd, 0, stdout=self.host_version, stderr="")
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0 if cmd[3] in self.present_images else 125)
        if "pg_dump" in cmd[0] or (len(cmd) > 1 and "pg_dump" in cmd):
            kw["stdout"].write(self.archive)
            return subprocess.CompletedProcess(cmd, self.dump_rc, stderr=self.dump_stderr)
        if cmd[-1] == "--list":
            data = kw["stdin"].read()
            assert data.startswith(backup.DUMP_MAGIC)
            return subprocess.CompletedProcess(
                cmd, self.list_rc, stdout=self.toc.encode(), stderr=b"bad archive"
            )
        raise AssertionError(f"unexpected command {cmd}")

    def commands(self, needle):
        return [cmd for cmd, _ in self.calls if needle in cmd]


def _take(world, tmp_path, url=PROD_URL, env="prod", server=15):
    return take_backup(
        url,
        env,
        out_dir=tmp_path / "backups",
        server_major_of=lambda u: server,
        which=world.which,
        run=world.run,
        now=lambda: FIXED_NOW,
        out=lambda line: None,
    )


# ---------------------------------------------------------------- secrets


def test_split_url_moves_the_password_out_of_the_dsn():
    target = split_url(PROD_URL)
    assert SECRET_ENC not in target.dsn and SECRET not in target.dsn
    assert (
        target.dsn == "postgresql://postgres.ref1@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
    )
    assert target.password == SECRET  # decoded for PGPASSWORD
    assert (
        target.display
        == "postgresql://postgres.ref1:***@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
    )


def test_split_url_keeps_query_params_and_handles_no_password():
    target = split_url("postgresql://postgres@localhost:5432/postgres?sslmode=require")
    assert target.password is None
    assert target.dsn.endswith("?sslmode=require")
    assert "***" not in target.display


def test_scrub_removes_raw_and_encoded_password():
    target = split_url(PROD_URL)
    text = f"FATAL: bad {SECRET} and {SECRET_ENC}"
    assert SECRET not in target.scrub(text) and SECRET_ENC not in target.scrub(text)


def test_mask_url_never_echoes_garbage():
    assert backup.mask_url("not a url with password hunter2") == "<unparseable database URL>"
    assert "hunter2" not in backup.mask_url("postgresql://u:hunter2@h:1/d")


def test_split_url_rejects_non_postgres_urls_without_echoing_them():
    with pytest.raises(BackupError) as err:
        split_url("https://u:hunter2@example.com")
    assert "hunter2" not in str(err.value)


def test_check_env_matches_refuses_mislabelled_dumps():
    backup.check_env_matches("local", LOCAL_URL)
    backup.check_env_matches("local", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
    backup.check_env_matches("prod", PROD_URL)
    with pytest.raises(BackupError):
        backup.check_env_matches("local", PROD_URL)
    with pytest.raises(BackupError):
        backup.check_env_matches("prod", LOCAL_URL)
    with pytest.raises(BackupError):
        backup.check_env_matches("staging", "postgresql://u:p@[::1]:5432/postgres")


# ---------------------------------------------------------------- tool selection


def test_parse_major():
    assert backup.parse_major("pg_dump (PostgreSQL) 16.4") == 16
    assert backup.parse_major("pg_dump (PostgreSQL) 17.6 (Debian 17.6-1)") == 17
    assert backup.parse_major("garbage") is None


def test_host_pg_dump_is_used_when_new_enough():
    world = FakeWorld(binaries=("pg_dump", "pg_restore", "podman"))
    tool = select_tool(15, which=world.which, run=world.run)
    assert tool.kind == "host" and tool.major == 16
    assert tool.dump_cmd("postgresql://u@h/d")[0] == "/usr/bin/pg_dump"


def test_old_host_pg_dump_falls_back_to_a_container():
    world = FakeWorld(
        binaries=("pg_dump", "pg_restore", "podman"), host_version="pg_dump (PostgreSQL) 14.9"
    )
    tool = select_tool(15, which=world.which, run=world.run)
    assert tool.kind == "container" and tool.major >= 15


def test_host_pg_dump_without_pg_restore_falls_back():
    world = FakeWorld(binaries=("pg_dump", "podman"))
    assert select_tool(15, which=world.which, run=world.run).kind == "container"


def test_container_prefers_a_pulled_image_then_the_lowest_eligible_major():
    pulled_17 = "public.ecr.aws/supabase/postgres:17.6.1.171"
    world = FakeWorld(present_images=(pulled_17,))
    assert select_tool(15, which=world.which, run=world.run).image == pulled_17

    # nothing pulled: the closest major (most restorable) is pulled on demand
    tool = select_tool(15, which=FakeWorld().which, run=FakeWorld().run)
    assert (tool.image, tool.major) == ("public.ecr.aws/supabase/postgres:15.8.1.085", 15)

    # a newer server never gets an older pg_dump
    tool = select_tool(16, which=FakeWorld().which, run=FakeWorld().run)
    assert tool.major >= 16


def test_docker_is_used_when_podman_is_absent():
    world = FakeWorld(binaries=("docker",))
    assert select_tool(15, which=world.which, run=world.run).runtime == "docker"


def test_no_host_tool_and_no_runtime_is_a_clear_error():
    world = FakeWorld(binaries=())
    with pytest.raises(BackupError, match="neither podman nor docker"):
        select_tool(15, which=world.which, run=world.run)


def test_server_newer_than_every_known_image_is_an_error():
    world = FakeWorld()
    with pytest.raises(BackupError, match="no known container image"):
        select_tool(99, which=world.which, run=world.run)


def test_container_commands_carry_no_password_and_stream_stdout():
    tool = Tool(kind="container", major=15, runtime="podman", image="img:15")
    dsn = split_url(PROD_URL).dsn
    cmd = tool.dump_cmd(dsn)
    assert cmd[:3] == ["podman", "run", "--rm"]
    assert "-t" not in cmd and "-i" not in cmd  # a tty would corrupt the binary stream
    assert cmd[cmd.index("-e") + 1] == "PGPASSWORD"  # the NAME only
    assert ["--network", "host"] == cmd[cmd.index("--network") : cmd.index("--network") + 2]
    assert "--format=custom" in cmd and "--no-password" in cmd
    assert not any(
        part.startswith("-f") or part == "--file" for part in cmd
    )  # stdout, no bind mount
    assert all(SECRET not in part and SECRET_ENC not in part for part in cmd)
    listing = tool.list_cmd()
    assert "-i" in listing and listing[-1] == "--list" and "pg_restore" in listing


# ---------------------------------------------------------------- take_backup


def test_take_backup_writes_a_validated_private_dump(tmp_path):
    world = FakeWorld()
    result = _take(world, tmp_path)

    assert result.path == tmp_path / "backups" / "prod-20261108T030405Z.dump"
    assert result.path.read_bytes() == GOOD_ARCHIVE
    assert result.size_bytes == len(GOOD_ARCHIVE)
    assert result.toc_entries == 3  # comment lines excluded
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.path.parent.stat().st_mode) == 0o700
    assert not list(result.path.parent.glob("*.partial"))

    for cmd, kw in world.calls:
        assert all(SECRET not in part and SECRET_ENC not in part for part in cmd)
    ((dump_cmd, dump_kw),) = [(c, k) for c, k in world.calls if "pg_dump" in c]
    assert dump_kw["env"]["PGPASSWORD"] == SECRET
    assert world.commands("--list")  # validated with pg_restore


def test_pg_dump_failure_raises_scrubbed_and_leaves_no_file(tmp_path):
    world = FakeWorld(dump_rc=1, dump_stderr=f"FATAL: password {SECRET} rejected".encode())
    with pytest.raises(BackupError) as err:
        _take(world, tmp_path)
    assert "pg_dump failed (1)" in str(err.value)
    assert SECRET not in str(err.value)
    assert list((tmp_path / "backups").iterdir()) == []


@pytest.mark.parametrize(
    ("world_kwargs", "message"),
    [
        ({"archive": backup.DUMP_MAGIC + b"x"}, "implausibly small"),
        ({"archive": b"NOTADUMP" * 500}, "bad magic"),
        ({"list_rc": 1}, "rejected the dump"),
        ({"toc": ";\n3; 2615 2200 SCHEMA - public pg_database_owner\n"}, "no TABLE DATA"),
    ],
)
def test_implausible_dumps_are_refused(tmp_path, world_kwargs, message):
    world = FakeWorld(**world_kwargs)
    with pytest.raises(BackupError, match=message):
        _take(world, tmp_path)
    assert list((tmp_path / "backups").iterdir()) == []


def test_take_backup_refuses_to_overwrite(tmp_path):
    _take(FakeWorld(), tmp_path)
    with pytest.raises(BackupError, match="already exists"):
        _take(FakeWorld(), tmp_path)


def test_progress_line_is_masked(tmp_path):
    lines = []
    take_backup(
        PROD_URL,
        "prod",
        out_dir=tmp_path,
        server_major_of=lambda u: 15,
        which=FakeWorld().which,
        run=FakeWorld().run,
        now=lambda: FIXED_NOW,
        out=lines.append,
    )
    text = "\n".join(lines)
    assert "***" in text and SECRET not in text and SECRET_ENC not in text


# ---------------------------------------------------------------- CLI + promote glue


def test_cli_requires_the_db_url(monkeypatch, capsys):
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert backup.main(["--env", "local"]) == 1
    assert "SUPABASE_DB_URL is not set" in capsys.readouterr().err


def test_cli_refuses_a_mislabelled_env_before_dumping(monkeypatch, capsys):
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL_URL)
    monkeypatch.setattr(backup, "take_backup", lambda *a, **k: pytest.fail("must not dump"))
    assert backup.main(["--env", "prod"]) == 1
    assert "BACKUP FAILED" in capsys.readouterr().err


def test_cli_success_prints_the_path(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("SUPABASE_DB_URL", LOCAL_URL)
    seen = {}

    def fake_take(url, env, *, out_dir):
        seen.update(url=url, env=env, out_dir=out_dir)
        return backup.BackupResult(
            path=out_dir / "local-x.dump", size_bytes=2048, tool="t", toc_entries=9
        )

    monkeypatch.setattr(backup, "take_backup", fake_take)
    assert backup.main(["--env", "local", "--out-dir", str(tmp_path)]) == 0
    assert seen == {"url": LOCAL_URL, "env": "local", "out_dir": tmp_path}
    out = capsys.readouterr().out
    assert "local-x.dump" in out and "2.0 KiB" in out


def test_default_backup_dir_is_gitignored_repo_root_backups():
    assert backup.BACKUP_DIR == Path(backup.__file__).resolve().parents[2] / "backups"
    gitignore = (backup.REPO_ROOT / ".gitignore").read_text()
    assert "/backups/" in gitignore.splitlines()


def test_promote_backup_port_ends_the_preflight_transaction_first(monkeypatch):
    order = []

    class Conn:
        def rollback(self):
            order.append("rollback")

    def fake_take(url, env):
        order.append(("take", url, env))
        return "result"

    monkeypatch.setattr(promotion_main.backup, "take_backup", fake_take)
    assert promotion_main._backup(Conn(), PROD_URL) == "result"
    assert order == ["rollback", ("take", PROD_URL, "prod")]


def test_human_size():
    assert backup.human_size(10) == "10 B"
    assert backup.human_size(2048) == "2.0 KiB"
    assert backup.human_size(5 * 1024 * 1024) == "5.0 MiB"
    assert backup.human_size(3 * 1024**3) == "3.0 GiB"
