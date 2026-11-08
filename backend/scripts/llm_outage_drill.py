"""LLM forced-outage drill client (#119, plan phase 5).

Drives a few real tutor and quiz requests against a running backend that was
booted with ``SAPLING_LLM_FORCE_OUTAGE=<provider>`` and reports, per request,
whether the student would have seen an error, then which models actually
served the drill (from the admin LLM-cost rollup) so you can see the fallback
happen. The runbook is docs/ops/llm-outage-drill.md.

Run from backend/:

    python -m scripts.llm_outage_drill                        # localhost:5000, test-login
    python -m scripts.llm_outage_drill --url http://localhost:8000 --user-id rich-user-active
    SAPLING_DRILL_SESSION=<sapling_session cookie> \\
        python -m scripts.llm_outage_drill --url https://<staging-api> --i-know

Auth: on localhost (APP_ENV=local/test) it mints a session through
``POST /api/auth/test-login`` for ``--user-id``. Anywhere else pass the
``sapling_session`` cookie of an ADMIN test account in ``SAPLING_DRILL_SESSION``
(never on the command line, where it lands in shell history) — admin, so the
script can also read ``/api/admin/llm/drill`` and the per-model rollup. A
non-admin session still runs the requests; it just can't show the models.

Safety: any URL that is not localhost needs ``--i-know``. The script only
calls the public API as the given user (tutor turns, one quiz) and the
admin READ endpoints; it changes no configuration.

Exit status: 0 when the outcome matches ``--expect`` (default ``fallback``:
no user-facing errors), 1 when it does not, 2 when the drill could not run
(unreachable, auth failed).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

SESSION_COOKIE = "sapling_session"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
REQUEST_TIMEOUT_S = 300.0
#: Tests inject an httpx.MockTransport here; None = the real network.
_transport: httpx.BaseTransport | None = None


@dataclass
class Outcome:
    name: str
    status: int | None
    ok: bool
    seconds: float
    note: str = ""


def _is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def _sse_events(text: str) -> list[dict]:
    events, cur = [], {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                events.append(cur)
                cur = {}
            continue
        if line.startswith(":") or ":" not in line:
            continue
        field, _, value = line.partition(":")
        cur[field.strip()] = value.lstrip()
    if cur:
        events.append(cur)
    parsed = []
    for ev in events:
        try:
            data = json.loads(ev.get("data") or "{}")
        except ValueError:
            data = {"raw": ev.get("data")}
        parsed.append({"event": ev.get("event"), "data": data})
    return parsed


class Drill:
    def __init__(self, base: str, token: str, user_id: str):
        self.base = base.rstrip("/")
        self.user_id = user_id
        self.client = httpx.Client(
            base_url=self.base, cookies={SESSION_COOKIE: token}, timeout=REQUEST_TIMEOUT_S,
            headers={"X-Drill": "llm-outage"}, transport=_transport,
        )
        self.outcomes: list[Outcome] = []

    def _record(self, name, started, status, ok, note=""):
        out = Outcome(name, status, ok, time.monotonic() - started, note)
        self.outcomes.append(out)
        mark = "ok   " if ok else "ERROR"
        print(f"  [{mark}] {name:<22} status={status} {out.seconds:6.1f}s  {note}")
        return out

    def _json(self, name, method, path, body=None):
        started = time.monotonic()
        try:
            r = self.client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            self._record(name, started, None, False, f"transport: {type(exc).__name__}")
            return None
        detail = ""
        if r.status_code >= 400:
            try:
                detail = str(r.json().get("detail"))[:120]
            except ValueError:
                detail = r.text[:120]
        self._record(name, started, r.status_code, r.status_code < 400, detail)
        return r.json() if r.status_code < 400 else None

    def _stream(self, name, path, body):
        started = time.monotonic()
        try:
            r = self.client.post(path, json=body, headers={"Accept": "text/event-stream"})
        except httpx.HTTPError as exc:
            self._record(name, started, None, False, f"transport: {type(exc).__name__}")
            return
        if r.status_code >= 400:
            self._record(name, started, r.status_code, False, r.text[:120])
            return
        events = _sse_events(r.text)
        errors = [e for e in events if e["event"] == "error"
                  or (isinstance(e["data"], dict) and e["data"].get("type") == "error")]
        done = any(e["event"] == "done"
                   or (isinstance(e["data"], dict) and e["data"].get("type") == "done")
                   for e in events)
        if errors:
            msg = errors[-1]["data"].get("message") if isinstance(errors[-1]["data"], dict) else ""
            self._record(name, started, r.status_code, False, f"SSE error: {msg}")
        else:
            self._record(name, started, r.status_code, done, "" if done else "stream ended without done")

    # -- scenario --------------------------------------------------------

    def run(self, turns: int, concept_node_id: str | None) -> None:
        print("Tutor (JSON):")
        start = self._json("start-session", "POST", "/api/learn/start-session",
                           {"user_id": self.user_id, "topic": "Outage drill", "mode": "socratic"})
        session_id = (start or {}).get("session_id")
        if session_id:
            for i in range(turns):
                self._json(f"chat turn {i + 1}", "POST", "/api/learn/chat",
                           {"session_id": session_id, "user_id": self.user_id,
                            "message": f"Drill question {i + 1}: explain one key idea briefly."})
            print("Tutor (SSE):")
            self._stream("chat/stream", "/api/learn/chat/stream",
                         {"session_id": session_id, "user_id": self.user_id,
                          "message": "Drill: one more short explanation, please."})
            self._json("end-session", "POST", "/api/learn/end-session",
                       {"session_id": session_id, "user_id": self.user_id})
        print("Quiz:")
        node = concept_node_id or self._first_concept_node()
        if node:
            self._json("quiz/generate", "POST", "/api/quiz/generate",
                       {"user_id": self.user_id, "concept_node_id": node, "num_questions": 3})
        else:
            print("  (skipped: no concept node; pass --concept-node-id)")

    def _first_concept_node(self) -> str | None:
        try:
            r = self.client.get(f"/api/graph/{self.user_id}")
            nodes = (r.json().get("nodes") or []) if r.status_code == 200 else []
            return nodes[0]["id"] if nodes else None
        except (httpx.HTTPError, ValueError, KeyError, AttributeError):
            return None

    # -- admin reads (optional) ------------------------------------------

    def drill_state(self) -> dict | None:
        try:
            r = self.client.get("/api/admin/llm/drill")
        except httpx.HTTPError:
            return None
        return r.json() if r.status_code == 200 else None

    def served_models(self, since_iso: str) -> dict[str, int] | None:
        try:
            r = self.client.get("/api/admin/analytics/llm/cost",
                                params={"from": since_iso, "group_by": "model"})
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        return {row["key"]: row["calls"] for row in r.json().get("rows", [])}


def _session(args, base: str) -> str:
    token = os.getenv("SAPLING_DRILL_SESSION", "").strip()
    if token:
        return token
    if not _is_local(base):
        sys.exit("SAPLING_DRILL_SESSION is required for a non-localhost URL (see the docstring).")
    with httpx.Client(timeout=30, transport=_transport) as client:
        r = client.post(f"{base.rstrip('/')}/api/auth/test-login",
                        json={"user_id": args.user_id, "ttl": 3600})
    if r.status_code != 200:
        print(f"test-login failed ({r.status_code}); is APP_ENV=local/test? "
              "Otherwise set SAPLING_DRILL_SESSION.", file=sys.stderr)
        sys.exit(2)
    return r.json()["token"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default="http://localhost:5000", help="backend base URL")
    p.add_argument("--i-know", action="store_true",
                   help="required for any non-localhost URL (e.g. staging)")
    p.add_argument("--user-id", default="rich-user-active",
                   help="the account the requests run as (test-login on localhost)")
    p.add_argument("--turns", type=int, default=2, help="JSON tutor turns to send")
    p.add_argument("--concept-node-id", help="graph node to quiz on (default: the user's first)")
    p.add_argument("--expect", choices=("fallback", "errors"), default="fallback",
                   help="fallback: no user-facing errors (llm_fallback on); "
                        "errors: every request fails cleanly (llm_fallback off)")
    p.add_argument("--settle", type=float, default=8.0,
                   help="seconds to wait for llm_usage rows before reading the rollup")
    args = p.parse_args(argv)

    if not _is_local(args.url) and not args.i_know:
        print(f"{args.url} is not localhost; re-run with --i-know if you mean it.", file=sys.stderr)
        return 2
    try:
        token = _session(args, args.url)
    except httpx.HTTPError as exc:
        print(f"cannot reach {args.url}: {type(exc).__name__}", file=sys.stderr)
        return 2

    drill = Drill(args.url, token, args.user_id)
    since = datetime.now(timezone.utc).isoformat()
    state = drill.drill_state()
    print(f"LLM outage drill against {args.url} as {args.user_id}")
    if state is None:
        print("  drill state: unknown (not an admin session, or an older backend)")
    else:
        fo = state.get("forced_outage") or {}
        print(f"  forced outage: {fo.get('providers') or 'NONE'}"
              + (f"  (refused: {fo['refused']})" if fo.get("refused") else ""))
        print(f"  llm_fallback: {state.get('llm_fallback')}   breakers: {state.get('breakers')}")
        if not fo.get("providers"):
            print("  WARNING: this worker is not drilling; the results below are a normal run.")

    drill.run(args.turns, args.concept_node_id)

    errors = [o for o in drill.outcomes if not o.ok]
    print(f"\n{len(drill.outcomes) - len(errors)} ok, {len(errors)} user-facing error(s) "
          f"out of {len(drill.outcomes)} request(s).")

    time.sleep(max(0.0, args.settle))
    models = drill.served_models(since)
    if models is None:
        print("Served models: unknown (needs an admin session). Check the backend log for "
              "'llm fallback:' lines and 'LLM FORCED-OUTAGE DRILL ARMED' at boot.")
    else:
        print("Served models since the drill started (llm_usage, all users):")
        for name, calls in sorted(models.items(), key=lambda kv: -kv[1]):
            print(f"  {name:<28} {calls} call(s)")
    after = drill.drill_state()
    if after is not None:
        print(f"Breakers after: {after.get('breakers')}")

    if args.expect == "fallback":
        return 0 if not errors else 1
    return 0 if errors and len(errors) == len(drill.outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
