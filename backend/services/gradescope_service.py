"""backend/services/gradescope_service.py

Thin wrapper around the unofficial `gradescopeapi` package. Logs in with a
student's Gradescope email/password and surfaces just the bits the
gradebook needs: courses + assignments-with-grades.

Caveats worth being honest about:
- Gradescope has no official public API. `gradescopeapi` scrapes the web
  UI with a logged-in session, so any UI change on Gradescope's side can
  break this without warning.
- Sessions are not persisted here. Routes pass in plaintext credentials,
  we log in for the duration of the request, and let the connection go
  out of scope. Per-user credentials are encrypted at rest by the route
  layer using `services.encryption`.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from bs4 import BeautifulSoup

from gradescopeapi import DEFAULT_GRADESCOPE_BASE_URL
from gradescopeapi.classes.account import Account
from gradescopeapi.classes.connection import GSConnection

logger = logging.getLogger(__name__)


class GradescopeAuthError(Exception):
    """Raised when login fails (invalid creds, captcha, blocked, etc.)."""


class GradescopeFetchError(Exception):
    """Raised when a downstream scrape fails (page format changed, course
    inaccessible, network glitch, etc.)."""


# Look like a recent desktop Chrome. The library's default `python-requests`
# User-Agent gets flagged by Gradescope's bot/anomaly defenses, which can
# surface as a "security" password-reset email instead of a normal login
# error. These headers + a real form-encoded body are what actually makes
# the /login POST behave like a browser.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
}


def login_with_cookies(
    signed_token: str | None,
    gradescope_session: str | None,
) -> GSConnection:
    """Build a logged-in GSConnection from pasted browser cookies.

    For SSO accounts (BU, other Shibboleth schools) we can't post the
    /login form — Duo 2FA stops us. Instead the user signs in normally in
    their browser, copies the session cookies from DevTools, and pastes
    them here. We validate by hitting /account; anything other than a
    200 on a non-/login URL means the cookies are stale or wrong.

    `gradescope_session` is required (the actual session cookie).
    `signed_token` is the "remember me" cookie — optional, present on
    long-lived sessions; including it extends the session's lifetime.
    """
    base_url = DEFAULT_GRADESCOPE_BASE_URL
    if not gradescope_session:
        raise GradescopeAuthError("Missing _gradescope_session cookie")

    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    # Domain '.gradescope.com' so cookies are sent for both www and root.
    session.cookies.set(
        "_gradescope_session",
        gradescope_session.strip(),
        domain=".gradescope.com",
        path="/",
    )
    if signed_token:
        session.cookies.set(
            "signed_token",
            signed_token.strip(),
            domain=".gradescope.com",
            path="/",
        )

    try:
        r = session.get(f"{base_url}/account", timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        raise GradescopeAuthError(f"Couldn't reach Gradescope: {e}") from e

    if r.status_code != 200 or "/login" in (r.url or ""):
        raise GradescopeAuthError(
            "Session cookies are invalid or expired. Re-copy them from your browser."
        )

    # Pick up X-CSRF-Token for any later POSTs the library makes.
    soup = BeautifulSoup(r.text, "html.parser")
    csrf = soup.select_one('meta[name="csrf-token"]')
    if csrf and csrf.get("content"):
        session.headers.update({"X-CSRF-Token": csrf["content"]})

    conn = GSConnection(base_url)
    conn.session = session
    conn.logged_in = True
    conn.account = Account(session, base_url)
    return conn


def login(email: str, password: str) -> GSConnection:
    """Authenticate with Gradescope. Returns a logged-in GSConnection.

    Reimplemented here instead of calling gradescopeapi's built-in login
    because that version has two bugs:
      1. It sends the form fields via `params=` (URL query string) instead
         of `data=` (form body). Gradescope's Rails backend doesn't see
         the credentials in the POST body and routes the request into the
         security-anomaly path, which emails the user a password reset
         link as if the login were suspicious.
      2. It leaves the default python-requests User-Agent on the session,
         which the same anomaly heuristics flag on its own.

    Both issues are fixed here. The resulting authenticated `Session` is
    handed back to a real `GSConnection` so the rest of the library
    (`account.get_courses()`, `account.get_assignments()`, etc.) continues
    to work as designed.
    """
    base_url = DEFAULT_GRADESCOPE_BASE_URL
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)

    try:
        # Step 1: load the homepage to grab the CSRF authenticity_token
        # and set the initial _gradescope_session cookie.
        home = session.get(base_url, timeout=20)
        home.raise_for_status()
    except requests.RequestException as e:
        raise GradescopeAuthError(f"Couldn't reach Gradescope: {e}") from e

    soup = BeautifulSoup(home.text, "html.parser")
    token_input = soup.select_one(
        'form[action="/login"] input[name="authenticity_token"]'
    )
    if not token_input or not token_input.get("value"):
        raise GradescopeAuthError(
            "Couldn't find the Gradescope login form — site markup may have changed."
        )
    auth_token = token_input["value"]

    # Step 2: POST the form. `data=` (not `params=`) is the critical fix.
    form = {
        "utf8": "✓",
        "session[email]": email,
        "session[password]": password,
        "session[remember_me]": "0",
        "commit": "Log In",
        "session[remember_me_sso]": "0",
        "authenticity_token": auth_token,
    }
    try:
        resp = session.post(
            f"{base_url}/login",
            data=form,
            timeout=20,
            allow_redirects=True,
            headers={"Referer": f"{base_url}/login"},
        )
    except requests.RequestException as e:
        raise GradescopeAuthError(f"Login request failed: {e}") from e

    # Success looks like: at least one 302 in the redirect chain AND the
    # final URL isn't /login (which is where Gradescope bounces failed
    # attempts back to with a flash error).
    redirected = bool(resp.history) and any(
        h.status_code in (301, 302, 303) for h in resp.history
    )
    landed_off_login = "/login" not in (resp.url or "")
    if not (redirected and landed_off_login):
        # Try to surface the in-page error if Gradescope rendered one.
        err_soup = BeautifulSoup(resp.text, "html.parser")
        flash = err_soup.select_one(".alert, .flash, .error")
        detail = flash.get_text(strip=True) if flash else None
        raise GradescopeAuthError(
            detail or "Invalid Gradescope credentials"
        )

    # Pick up X-CSRF-Token from the landed page so subsequent POSTs work.
    landed_soup = BeautifulSoup(resp.text, "html.parser")
    csrf = landed_soup.select_one('meta[name="csrf-token"]')
    if csrf and csrf.get("content"):
        session.headers.update({"X-CSRF-Token": csrf["content"]})

    # Hand the authenticated session to a real GSConnection so the rest
    # of the library can use it.
    conn = GSConnection(base_url)
    conn.session = session
    conn.logged_in = True
    conn.account = Account(session, base_url)
    return conn


def list_student_courses(conn: GSConnection) -> list[dict[str, Any]]:
    """Surface student-role courses only. Instructor courses are dropped —
    this integration is scoped to a student's own gradebook.
    """
    try:
        all_courses = conn.account.get_courses()  # type: ignore[union-attr]
    except Exception as e:
        raise GradescopeFetchError(f"Failed to list courses: {e}") from e

    student_courses = all_courses.get("student", {}) if isinstance(all_courses, dict) else {}
    return [
        {
            "id": str(cid),
            "name": getattr(c, "name", "") or "",
            "full_name": getattr(c, "full_name", "") or "",
            "semester": getattr(c, "semester", "") or "",
            "year": getattr(c, "year", "") or "",
            "num_assignments": getattr(c, "num_assignments", "") or "",
        }
        for cid, c in student_courses.items()
    ]


def _parse_grade(value: Any) -> float | None:
    """Gradescope returns grades as strings — '85.0', '—', '', '/'.
    Anything non-numeric becomes None.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("—", "-", "/", "N/A"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def list_assignments(conn: GSConnection, course_id: str) -> list[dict[str, Any]]:
    """Return parsed assignments for a Gradescope course.

    Date fields are ISO strings (or None). Grades are numeric (or None).
    """
    try:
        assignments = conn.account.get_assignments(course_id)  # type: ignore[union-attr]
    except Exception as e:
        raise GradescopeFetchError(
            f"Failed to list assignments for course {course_id}: {e}"
        ) from e

    out: list[dict[str, Any]] = []
    for a in assignments:
        due_dt = getattr(a, "due_date", None)
        release_dt = getattr(a, "release_date", None)
        out.append(
            {
                "id": str(getattr(a, "assignment_id", "")),
                "name": getattr(a, "name", "") or "",
                "release_date": release_dt.isoformat() if release_dt else None,
                "due_date": due_dt.isoformat() if due_dt else None,
                "submissions_status": getattr(a, "submissions_status", None),
                "points_earned": _parse_grade(getattr(a, "grade", None)),
                "points_possible": _parse_grade(getattr(a, "max_grade", None)),
            }
        )
    return out
