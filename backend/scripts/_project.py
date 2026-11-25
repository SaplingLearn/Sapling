"""Which Supabase project a script is pointed at, shared by the ops scripts.

`project_ref` names the project for the backfills' `--project` refusal and
their banners; `require_local_test_db` is the seed fixtures' guard that
refuses anything but a loopback database under APP_ENV local/test.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlsplit

#: Loopback hosts: the only hosts a local/test seed fixture may write to.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
#: Hosts `project_ref` reports as `local` (loopback plus the container aliases).
LOCAL_HOSTS = LOOPBACK_HOSTS | {"0.0.0.0", "host.docker.internal"}
#: A hosted project's host is `<ref>` + this suffix.
SUPABASE_SUFFIX = ".supabase.co"
#: The project name `project_ref` gives a local URL.
LOCAL_PROJECT = "local"
#: The APP_ENV values a seed fixture runs under.
LOCAL_APP_ENVS = frozenset({"local", "test"})


def project_ref(supabase_url: str) -> str:
    """The project `supabase_url` points at: `<ref>` of `<ref>.supabase.co`,
    `local` for a loopback URL, else the bare host."""
    host = (urlparse(supabase_url).hostname or "").lower()
    if not host or host in LOCAL_HOSTS:
        return LOCAL_PROJECT
    if host.endswith(SUPABASE_SUFFIX):
        return host[: -len(SUPABASE_SUFFIX)].split(".")[0]
    return host


def require_local_test_db(what: str) -> None:
    """Refuse unless SUPABASE_URL is a loopback host AND APP_ENV is local/test.
    `what` names the fixtures in the error ("Close-beat fixtures")."""
    host = urlsplit(os.getenv("SUPABASE_URL", "")).hostname
    if host not in LOOPBACK_HOSTS or os.getenv("APP_ENV") not in LOCAL_APP_ENVS:
        raise RuntimeError(f"{what} require a local/test loopback database")
