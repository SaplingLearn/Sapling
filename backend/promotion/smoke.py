"""Post-deploy smoke checks against the live production surface (#516).

Unauthenticated surface only. A 401/403 on a guarded route is a PASS: it proves
the router is MOUNTED, and the failure mode this catches is a 404 from code that
never shipped.

Checks are DATA, and the fetcher is injected, so the suite is testable without a
network. Deliberately excluded: assertions about specific term data (#515 asserted
`fall-2026` and a start date), which pass today and rot next term.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

DEFAULT_API = "https://api.saplinglearn.com"
DEFAULT_WEB = "https://saplinglearn.com"


@dataclass(frozen=True)
class Check:
    name: str
    target: str  # "api" | "web"
    path: str
    expect_status: tuple[int, ...]
    expect_body: str = ""
    method: str = "GET"


@dataclass
class Result:
    check: Check
    ok: bool
    status: int | None
    detail: str


CHECKS: list[Check] = [
    Check("api health", "api", "/api/health", (200,), '"status":"ok"'),
    # Mounted-not-404. These routers only exist in promoted code.
    Check("academics mounted", "api", "/api/semesters", (200,)),
    Check("notes mounted", "api", "/api/notes", (200, 401, 403, 405)),
    Check("admin analytics mounted", "api", "/api/admin/analytics/usage/summary", (401, 403)),
    Check("auth entrypoint", "api", "/api/auth/google", (200, 302, 307, 400, 401)),
    # The local/test session minter must be OFF in production. POST specifically:
    # a GET returns 405, which would mask a live endpoint.
    Check("test-login disabled", "api", "/api/auth/test-login", (404,), method="POST"),
    Check("web root", "web", "/", (200,), "<"),
    # Proves the frontend worker's build-time BACKEND_URL is right; a wrong one 500s.
    Check("web -> api proxy", "web", "/api/health", (200,), '"status":"ok"'),
]


def run_checks(fetch, api_base: str, web_base: str, checks: list[Check] | None = None) -> list[Result]:
    """Run each check through `fetch(method, url) -> (status | None, body)`."""
    results: list[Result] = []
    for check in checks if checks is not None else CHECKS:
        base = api_base if check.target == "api" else web_base
        url = f"{base.rstrip('/')}{check.path}"
        status, body = fetch(check.method, url)

        if status is None:
            results.append(Result(check, False, None, f"no response from {url}: {body[:120]}"))
            continue
        if status not in check.expect_status:
            expected = "/".join(str(s) for s in check.expect_status)
            results.append(Result(check, False, status, f"{url} -> {status}, expected {expected}"))
            continue
        if check.expect_body and check.expect_body not in body:
            results.append(Result(check, False, status, f"{url} -> {status} but missing {check.expect_body!r}"))
            continue
        results.append(Result(check, True, status, f"{url} -> {status}"))
    return results


def live_commit(fetch, api_base: str) -> str:
    """Deployed short SHA from /api/health, or "" if unreachable/unparseable."""
    status, body = fetch("GET", f"{api_base.rstrip('/')}/api/health")
    if status != 200:
        return ""
    try:
        return str(json.loads(body).get("commit", ""))
    except (ValueError, AttributeError):
        return ""


def format_results(results: list[Result]) -> str:
    return "\n".join(
        f"  {'PASS' if r.ok else 'FAIL'}  {r.check.name}  ({r.detail})" for r in results
    )


def httpx_fetch(method: str, url: str) -> tuple[int | None, str]:
    """Real IO. Imported lazily so importing this module costs nothing."""
    import httpx

    try:
        response = httpx.request(method, url, timeout=25.0, follow_redirects=False)
        return response.status_code, response.text
    except httpx.HTTPError as exc:  # DNS, TLS, timeout, refused
        return None, str(exc)
