"""The caller's IP address, for rate-limiting endpoints that have no user id.

Most limiters in this codebase key on an authenticated `user_id`
(`services/request_limits.py` callers: `ocr:{user_id}`, the study-guide
limits, …). A handful of endpoints are deliberately PUBLIC — `POST
/api/careers/apply` and `POST /api/newsletter/subscribe` — and there is no
user to key on, so they key on the caller instead.

HONEST CAVEAT, read before reusing this for anything else
---------------------------------------------------------
An IP taken from a request header is **spoofable in general**: `X-Forwarded-For`
is client-settable, and anything downstream of an untrusted proxy can claim any
address. This helper is therefore sized for ABUSE DAMPENING on public endpoints
(stop one script filling the applications table or the newsletter list), and is
NOT an authorization or identity signal. Never gate access on it, never use it
to attribute an action to a person, and never use it where being wrong is a
security failure rather than a throughput failure.

Header order and why
--------------------
1. ``CF-Connecting-IP`` — set by Cloudflare, which fronts the deploy, and
   OVERWRITTEN by Cloudflare on every request, so a client cannot forge it
   through the edge. This is the trustworthy one in production.
2. ``X-Forwarded-For`` first entry — the standard proxy chain, used when the
   backend runs behind something other than Cloudflare (Railway direct, a
   docker-compose stack). Client-settable; see the caveat.
3. ``request.client.host`` — the socket peer. Correct with no proxy at all.

A request with none of the three (an ASGI scope with no client, which happens
in tests) yields ``"unknown"``; every such caller then shares one bucket, which
is the safe direction — it throttles more, not less.
"""

from __future__ import annotations

from fastapi import Request

#: Cap on the stored key length. An `X-Forwarded-For` is attacker-sized, and
#: the value becomes part of a rate-limit key (a DB column under the
#: `stateless_rate_limit` flag). Bound it so a huge header cannot bloat the
#: limiter's storage or its index.
MAX_IP_LEN = 45  # an IPv6 address with an IPv4 suffix is at most 45 chars


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    ip = value.strip()
    if not ip:
        return None
    return ip[:MAX_IP_LEN]


def client_ip(request: Request) -> str:
    """The caller's best-known IP, or ``"unknown"``. See the module caveat."""
    cf = _clean(request.headers.get("cf-connecting-ip"))
    if cf:
        return cf

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # "client, proxy1, proxy2" — the client is the FIRST entry.
        first = _clean(forwarded.split(",")[0])
        if first:
            return first

    peer = getattr(request, "client", None)
    direct = _clean(getattr(peer, "host", None))
    if direct:
        return direct

    return "unknown"
