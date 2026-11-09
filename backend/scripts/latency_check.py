"""Chat time-to-first-token while a large PDF uploads (#116, phase 2).

LOCAL ONLY. Never run in CI, never against staging or production: it mints
sessions through POST /api/auth/test-login (which only exists under
APP_ENV=local/test) and, with --flag both|on|off, flips the `jobs_queue` flag
through the admin API.

The architecture-hardening plan's phase-2 "done when" is: a 50-page PDF upload
does not move chat latency. This measures exactly that, on the local stack:

  1. idle      N streamed chat turns, nothing else running
  2. upload    the same, while POST /api/documents/upload runs on --pdf

once per flag setting. TTFT is the time from sending POST
/api/learn/chat/stream to the first SSE `token` event (the first token of the
reply) — the `chat_stream` measure the plan's "under 3 s p95" target names.

Usage (from backend/, the local stack up — `make e2e-up` or your dev stack):

    python scripts/latency_check.py --pdf ~/big-50-pages.pdf
    python scripts/latency_check.py --pdf big.pdf --flag both --samples 8
    python scripts/latency_check.py --url http://127.0.0.1:5001 --pdf big.pdf

With --flag both the script records the flag's current default variant,
sets it to off then on (PATCH /api/admin/flags/jobs_queue as --admin-user),
and restores it at the end. After each flip it waits out the server's flag
snapshot TTL (services/feature_flags.py, 30 s by default; --flag-settle) so
every sample runs under the new value, and every pass uploads DIFFERENT bytes
(the PDF plus a unique `%` comment line after it), so the content-addressed
OCR cache cannot make the second pass's upload cheaper than the first's. Note `jobs_queue` only moves work to the queue:
with it ON the upload's heavy work runs in `python -m worker`, so start one
(`cd backend && python -m worker`) or the "on" numbers measure a queue nobody
drains.

In function mode (SAPLING_MODEL_MODE=function, the e2e stack) the tutor is a
fixed handler, so TTFT measures the server, not a model: that is the point —
it isolates the contention the upload causes. Exit code: 0 measured, 2 usage /
environment error.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
FLAG = "jobs_queue"
EXIT_USAGE = 2


def is_local_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in LOCAL_HOSTS


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; NaN for no values."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(pct / 100 * len(ordered))))
    return ordered[rank - 1]


@dataclass
class Scenario:
    name: str
    ttft: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    upload_seconds: float | None = None

    def row(self) -> str:
        if not self.ttft:
            return f"{self.name:<18} no samples  errors={len(self.errors)}"
        up = f"  upload={self.upload_seconds:.1f}s" if self.upload_seconds is not None else ""
        return (f"{self.name:<18} n={len(self.ttft):<3} "
                f"p50={statistics.median(self.ttft):6.3f}s "
                f"p95={percentile(self.ttft, 95):6.3f}s "
                f"max={max(self.ttft):6.3f}s errors={len(self.errors)}{up}")


class Client:
    def __init__(self, base: str, timeout: float) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout

    def session(self, user_id: str) -> httpx.Client:
        """An httpx client carrying a freshly minted sapling_session cookie."""
        c = httpx.Client(base_url=self.base, timeout=self.timeout)
        r = c.post("/api/auth/test-login", json={"user_id": user_id, "ttl": 3600})
        if r.status_code == 404:
            raise SystemExit(
                f"{self.base}/api/auth/test-login is 404: the backend is not running "
                "with APP_ENV=local/test, so this is not a local stack. Refusing.")
        r.raise_for_status()
        body = r.json()
        c.cookies.set(body["cookie_name"], body["token"])
        return c


def start_session(c: httpx.Client, user_id: str, course_id: str) -> str:
    r = c.post("/api/learn/start-session",
               json={"user_id": user_id, "course_id": course_id, "topic": "latency check"})
    r.raise_for_status()
    return r.json()["session_id"]


def chat_ttft(c: httpx.Client, user_id: str, session_id: str) -> float:
    """Seconds from sending the turn to its first `token` SSE event. The rest
    of the stream is drained so the turn finishes cleanly."""
    body = {"session_id": session_id, "user_id": user_id,
            "message": "Give me one short hint.", "turn_id": uuid.uuid4().hex}
    started = time.perf_counter()
    first: float | None = None
    with c.stream("POST", "/api/learn/chat/stream", json=body) as r:
        r.raise_for_status()
        event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.partition(":")[2].strip()
            elif line.startswith("data:") and first is None:
                data = line.partition(":")[2].strip()
                kind = event
                if kind is None:
                    try:
                        kind = json.loads(data).get("type")
                    except ValueError:
                        kind = None
                if kind == "token":
                    first = time.perf_counter() - started
    if first is None:
        raise RuntimeError("the stream ended without a token event")
    return first


def unique_pdf(raw: bytes, tag: str) -> bytes:
    """`raw` with a PDF comment line appended, so each pass uploads bytes
    the server has never hashed: extraction is cached on sha256(file bytes)
    (services/extraction_service.py), and a second upload of the same file
    would skip OCR and flatter whichever pass ran second. Readers ignore a
    `%` comment after %%EOF."""
    sep = b"" if raw.endswith((b"\n", b"\r")) else b"\n"
    return raw + sep + f"%sapling-latency-check {tag}\n".encode("ascii")


def upload(c: httpx.Client, user_id: str, course_id: str, name: str, body: bytes) -> float:
    """Run the streaming upload to completion; seconds it took."""
    started = time.perf_counter()
    files = {"file": (name, body, "application/pdf")}
    data = {"user_id": user_id, "course_id": course_id}
    with c.stream("POST", "/api/documents/upload", files=files, data=data) as r:
        r.raise_for_status()
        for _ in r.iter_lines():
            pass
    return time.perf_counter() - started


def flag_settle_seconds(override: float | None = None) -> float:
    """How long to wait after flipping the flag: the server's flag snapshot
    TTL (a worker keeps its snapshot that long, so samples taken sooner can
    still run under the old value), plus a small margin. Read from
    services/feature_flags.py rather than copied, never below its default."""
    if override is not None:
        return max(0.0, override)
    from services.feature_flags import DEFAULT_SNAPSHOT_TTL_S, snapshot_ttl_s

    return max(DEFAULT_SNAPSHOT_TTL_S, snapshot_ttl_s()) + 2.0


def sample(c, user_id, session_id, n, gap, scenario: Scenario, until=None) -> None:
    for i in range(n):
        if until is not None and until.is_set() and i >= 1:
            break
        try:
            scenario.ttft.append(chat_ttft(c, user_id, session_id))
        except Exception as exc:  # keep measuring; report at the end
            scenario.errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(gap)


def run_pair(cl: Client, args, label: str, body: bytes) -> list[Scenario]:
    student = cl.session(args.user_id)
    session_id = start_session(student, args.user_id, args.course_id)

    idle = Scenario(f"{label}/idle")
    sample(student, args.user_id, session_id, args.samples, args.gap, idle)

    loaded = Scenario(f"{label}/upload")
    uploader = cl.session(args.user_id)
    done = threading.Event()
    upload_err: list[str] = []

    def _upload():
        try:
            loaded.upload_seconds = upload(uploader, args.user_id, args.course_id,
                                           args.pdf.name, body)
        except Exception as exc:
            upload_err.append(f"{type(exc).__name__}: {exc}")
        finally:
            done.set()

    t = threading.Thread(target=_upload, daemon=True)
    t.start()
    time.sleep(args.upload_head_start)
    sample(student, args.user_id, session_id, args.samples, args.gap, loaded, until=done)
    t.join(timeout=args.timeout)
    loaded.errors.extend(f"upload: {e}" for e in upload_err)
    if not done.is_set():
        loaded.errors.append("upload: still running after the chat samples")
    return [idle, loaded]


def flag_config(admin: httpx.Client) -> dict:
    """The flag's default + rollout, to restore exactly at the end. (Per-user
    and per-role targets are left alone throughout; a target pinning the
    measuring student overrides the default, so use a student without one.)"""
    r = admin.get("/api/admin/flags")
    r.raise_for_status()
    for f in r.json()["flags"]:
        if f.get("key") == FLAG:
            return {"default_variant": f.get("default_variant") or "off",
                    "rollout_percent": f.get("rollout_percent") or 0,
                    "rollout_variant": f.get("rollout_variant")}
    raise RuntimeError(f"flag {FLAG!r} is not in the registry")


def set_flag(admin: httpx.Client, config: dict) -> None:
    r = admin.patch(f"/api/admin/flags/{FLAG}", json=config)
    r.raise_for_status()


def only(variant: str) -> dict:
    return {"default_variant": variant, "rollout_percent": 0, "rollout_variant": None}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default="http://localhost:5000",
                   help="backend base URL (default http://localhost:5000)")
    p.add_argument("--pdf", type=Path, required=True,
                   help="the large PDF to upload (e.g. 50 scanned pages)")
    p.add_argument("--user-id", default="rich-user-active",
                   help="a seeded, approved student (default: db.seed_local_rich's)")
    p.add_argument("--admin-user", default="rich-user-admin",
                   help="a seeded admin, used only to flip the flag")
    p.add_argument("--course-id", default="rich-course-cs101")
    p.add_argument("--samples", type=int, default=5, help="chat turns per scenario")
    p.add_argument("--gap", type=float, default=0.5, help="seconds between turns")
    p.add_argument("--upload-head-start", type=float, default=2.0,
                   help="seconds the upload runs before the first loaded sample")
    p.add_argument("--flag", choices=("current", "off", "on", "both"), default="current",
                   help="jobs_queue setting(s) to measure under (default: leave it)")
    p.add_argument("--flag-settle", type=float, default=None,
                   help="seconds to wait after flipping the flag before sampling "
                        "(default: the server's flag snapshot TTL + 2 s)")
    p.add_argument("--timeout", type=float, default=600.0)
    p.add_argument("--i-know", action="store_true",
                   help="allow a non-localhost --url (it still needs test-login)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not is_local_url(args.url) and not args.i_know:
        print(f"refusing {args.url}: not localhost. This script is for the local "
              "stack; pass --i-know only for another LOCAL address.", file=sys.stderr)
        return EXIT_USAGE
    if not args.pdf.is_file():
        print(f"--pdf {args.pdf}: no such file", file=sys.stderr)
        return EXIT_USAGE

    raw = args.pdf.read_bytes()
    run_tag = uuid.uuid4().hex
    cl = Client(args.url, args.timeout)
    results: list[Scenario] = []
    if args.flag == "current":
        results += run_pair(cl, args, "flag=current", unique_pdf(raw, f"{run_tag}-current"))
    else:
        admin = cl.session(args.admin_user)
        before = flag_config(admin)
        settle = flag_settle_seconds(args.flag_settle)
        try:
            for variant in (("off", "on") if args.flag == "both" else (args.flag,)):
                set_flag(admin, only(variant))
                print(f"{FLAG}={variant}: waiting {settle:.0f}s for the flag snapshot "
                      "to expire on the server", file=sys.stderr)
                time.sleep(settle)
                results += run_pair(cl, args, f"{FLAG}={variant}",
                                    unique_pdf(raw, f"{run_tag}-{variant}"))
        finally:
            set_flag(admin, before)

    print(f"\nchat time-to-first-token, {args.url}, pdf={args.pdf.name}")
    for s in results:
        print("  " + s.row())
        for err in s.errors[:3]:
            print(f"      ! {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
