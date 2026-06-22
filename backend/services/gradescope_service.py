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
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

from gradescopeapi import DEFAULT_GRADESCOPE_BASE_URL
from gradescopeapi.classes.account import Account
from gradescopeapi.classes.connection import GSConnection

logger = logging.getLogger(__name__)

# Playwright is optional — only the BU SSO flow needs it. Deployments
# without a Chromium binary (e.g. CF Workers) can still use the other
# auth modes; we surface a clean ImportError-style message instead of
# crashing at import time.
#
# Using the SYNC API on purpose: Playwright's async API requires the
# host loop to be ProactorEventLoop on Windows, but uvicorn under FastAPI
# on Windows can be Selector — they conflict at subprocess launch. The
# sync API runs Playwright in its own greenlet-driven loop and is the
# documented pattern for FastAPI + Windows. We call it from the route via
# asyncio.to_thread so the FastAPI event loop stays unblocked.
try:
    from playwright.sync_api import (  # type: ignore[import-not-found]
        sync_playwright,
        TimeoutError as PlaywrightTimeoutError,
        Locator,
        Page,
    )
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on env
    PLAYWRIGHT_AVAILABLE = False
    Locator = Any  # type: ignore[misc,assignment]
    Page = Any  # type: ignore[misc,assignment]


class GradescopeAuthError(Exception):
    """Raised when login fails (invalid creds, captcha, blocked, etc.)."""


class GradescopeFetchError(Exception):
    """Raised when a downstream scrape fails (page format changed, course
    inaccessible, network glitch, etc.)."""


class GradescopeDuoTimeout(GradescopeAuthError):
    """Raised when the user didn't tap their Duo push within the deadline."""


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


# ────────────────────────────────────────────────────────────────────────────
# BU SSO via Playwright
# ────────────────────────────────────────────────────────────────────────────
# Drive a headless Chromium through Gradescope's "School Credentials" entry
# → Boston University → Shibboleth WebLogin → Duo. We hold open until the
# page redirects back to gradescope.com (which happens only after the user
# taps Approve on their phone), then harvest the session cookies. BU
# password lives in-memory for the duration of the request and is never
# persisted; only the resulting cookies are stored.
#
# Selectors are best-effort and may need tuning after a real run — BU's
# Shibboleth template and Gradescope's IdP picker both change occasionally.
# Each step tries multiple fallback selectors before failing.

# Gradescope's normal login page. The school picker is hidden behind a
# "School Credentials" button on this page — we click it first, then the
# typeahead appears.
_GRADESCOPE_LOGIN = "https://www.gradescope.com/login"
_BU_SCHOOL_NAME = "Boston University"

# "School Credentials" entry button on /login. The text varies a little
# between Gradescope rev'd (sometimes "Sign in with school credentials").
_SCHOOL_CREDS_BUTTON_SELECTORS = [
    "a:has-text('School Credentials')",
    "button:has-text('School Credentials')",
    "a:has-text('school credentials')",
    "a:has-text('Sign in with school')",
    "a[href*='saml']",
]

# Typeahead input on the school picker page. Multiple candidates because
# the picker's markup changes more often than the rest of the flow.
_BU_IDP_SEARCH_SELECTORS = [
    "input[placeholder*='school' i]",
    "input[placeholder*='institution' i]",
    "input[placeholder*='search' i]",
    "input[name*='school' i]",
    "input[name*='institution' i]",
    "input[type='search']",
    # last-resort: any visible text-ish input
    "input:not([type='hidden']):not([type='password']):not([type='submit'])",
]
_SHIB_USERNAME_SELECTORS = [
    "input[name='j_username']",
    "input#username",
    "input[name='username']",
]
_SHIB_PASSWORD_SELECTORS = [
    "input[name='j_password']",
    "input#password",
    "input[name='password']",
]
_SHIB_SUBMIT_SELECTORS = [
    "button[name='_eventId_proceed']",
    "button:has-text('Continue')",
    "button:has-text('Login')",
    "button[type='submit']",
    "input[type='submit']",
]

# Post-Duo continuation buttons. Shibboleth's "Trust this browser?" page
# and SAML POST-back pages tend to render one of these. Order matters —
# the more specific the label, the earlier we try. "No"-prefixed labels
# are intentionally absent.
_POST_DUO_BUTTON_LABELS = [
    r"^yes,?\s*trust",      # "Yes, trust browser"
    r"trust\s*browser",
    r"^yes,?\s*this is",    # "Yes, this is my device"
    r"^remember\s*me",
    r"^continue$",
    r"^proceed$",
    r"^submit$",
]
# Fallback selectors when get_by_role doesn't find a button.
_POST_DUO_FALLBACK_SELECTORS = [
    "input[type='submit'][value*='Continue' i]",
    "input[type='submit'][value*='Trust' i]",
    "input[type='submit'][value*='Submit' i]",
    "a:has-text('Continue')",
]


def _dump_page_state(page: "Page") -> str:
    """Build a short diagnostic string for error messages when a selector
    step fails. Includes URL, page title, and a summary of every input
    element on the page so we can adjust selectors without guessing."""
    try:
        url = page.url
    except Exception:
        url = "<unknown>"
    try:
        title = page.title()
    except Exception:
        title = "<unknown>"
    try:
        inputs = page.eval_on_selector_all(
            "input, button, a",
            """els => els.slice(0, 40).map(e => {
                if (e.tagName === 'INPUT') {
                    return `input[name='${e.name||''}' type='${e.type||''}' placeholder='${e.placeholder||''}' id='${e.id||''}']`;
                }
                if (e.tagName === 'BUTTON') {
                    return `button[text='${(e.innerText||'').slice(0, 40)}' name='${e.name||''}']`;
                }
                if (e.tagName === 'A') {
                    return `a[text='${(e.innerText||'').slice(0, 40)}' href='${(e.href||'').slice(0, 60)}']`;
                }
                return e.tagName;
            })""",
        )
        elements_str = "; ".join(inputs)
    except Exception as ex:
        elements_str = f"<eval failed: {ex}>"
    return f"page={url} title={title!r} elements=[{elements_str}]"


def _first_visible(page: "Page", selectors: list[str], timeout_ms: int) -> "Locator":
    """Return the first selector in `selectors` that resolves to a visible
    element within `timeout_ms` per selector. Raises GradescopeAuthError
    if none match — that's how we know BU/Shibboleth markup drifted."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return loc
        except PlaywrightTimeoutError:
            continue
    raise GradescopeAuthError(
        f"Couldn't find any of these elements on the page: {selectors}. "
        "BU/Shibboleth markup may have changed."
    )


def login_via_bu_sso(
    bu_username: str,
    bu_password: str,
    duo_timeout_seconds: int = 120,
) -> dict[str, str]:
    """Run a full BU-SSO + Duo dance and return the resulting Gradescope
    cookies. Caller is responsible for storing them. Synchronous so it can
    be invoked from a worker thread via asyncio.to_thread without
    bumping into Windows event-loop quirks.

    Raises:
        GradescopeAuthError      — bad creds, missing selectors, Duo denied
        GradescopeDuoTimeout     — Duo push not approved within deadline
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise GradescopeAuthError(
            "Playwright is not installed on the backend. Run "
            "`pip install playwright && playwright install chromium`."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=_BROWSER_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            # Knock out a couple of the most obvious headless tells. Real
            # anti-bot evasion is its own discipline; this is the floor.
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )
            page = context.new_page()

            # Step 1: Land on Gradescope's login page. wait_until='commit'
            # returns as soon as the navigation commits, ~1s faster than
            # 'domcontentloaded'. The selector waits below will block on
            # whatever element we need anyway.
            try:
                page.goto(_GRADESCOPE_LOGIN, timeout=20000, wait_until="commit")
            except PlaywrightTimeoutError as e:
                raise GradescopeAuthError(f"Couldn't reach Gradescope: {e}") from e

            # Step 2: Click "School Credentials" to reveal the IdP picker.
            try:
                school_btn = _first_visible(
                    page, _SCHOOL_CREDS_BUTTON_SELECTORS, 6000
                )
                school_btn.click()
            except GradescopeAuthError as e:
                raise GradescopeAuthError(
                    f"Couldn't find the 'School Credentials' button on /login. "
                    f"{_dump_page_state(page)}. Original: {e}"
                ) from e

            # Step 3: Type "Boston University" into the school search.
            # Skipping wait_for_load_state — the selector wait below
            # already blocks until the search input is visible.
            try:
                search = _first_visible(page, _BU_IDP_SEARCH_SELECTORS, 8000)
                search.fill(_BU_SCHOOL_NAME)
                bu_option = page.get_by_text(_BU_SCHOOL_NAME, exact=False).first
                bu_option.wait_for(state="visible", timeout=5000)
                bu_option.click()
            except (PlaywrightTimeoutError, GradescopeAuthError) as e:
                raise GradescopeAuthError(
                    f"Couldn't pick Boston University from Gradescope's school picker. "
                    f"{_dump_page_state(page)}. Original: {e}"
                ) from e

            # Step 4: Wait for redirect to shib.bu.edu (just URL — don't
            # block on load state, since the selector wait below handles
            # readiness).
            try:
                page.wait_for_url("**shib.bu.edu/**", timeout=15000)
            except PlaywrightTimeoutError as e:
                raise GradescopeAuthError(
                    f"Didn't land on BU's WebLogin (currently at {page.url}): {e}"
                ) from e

            # Step 5: Fill BU username + password, click Continue. Trimmed
            # per-selector timeouts — these elements appear within the
            # first DOM commit, so 5s is plenty.
            username_field = _first_visible(page, _SHIB_USERNAME_SELECTORS, 5000)
            username_field.fill(bu_username)
            password_field = _first_visible(page, _SHIB_PASSWORD_SELECTORS, 3000)
            password_field.fill(bu_password)
            submit = _first_visible(page, _SHIB_SUBMIT_SELECTORS, 3000)
            # NOTE: from here until the Duo push lands on the user's phone,
            # latency is out of our hands (BU → Duo servers → APNs/FCM).
            submit.click()

            # Step 5: Wait for the redirect chain to end on gradescope.com,
            # clicking through any post-Duo interstitials along the way.
            #
            # The flow after Continue is usually:
            #   submit -> Duo iframe -> (user taps Approve on phone) ->
            #   "Trust this browser?" page -> SAML POST -> gradescope.com
            #
            # Those middle steps need clicks. We poll every ~1.5s, check if
            # we've landed on Gradescope, and otherwise look for known
            # continuation buttons ("Yes, trust browser", "Continue",
            # "Submit") and click whichever is visible.
            deadline = time.monotonic() + duo_timeout_seconds
            last_diag_url = ""
            while time.monotonic() < deadline:
                current_url = page.url or ""
                if "gradescope.com" in current_url and "/login" not in current_url:
                    break
                # Try to click through any visible continuation button.
                # Order matters: most-specific labels first so we don't
                # mis-click a "No" when "Yes, trust browser" exists.
                for label_pat in _POST_DUO_BUTTON_LABELS:
                    try:
                        btn = page.get_by_role(
                            "button", name=re.compile(label_pat, re.I)
                        ).first
                        btn.click(timeout=600)
                        break
                    except PlaywrightTimeoutError:
                        continue
                    except Exception:
                        continue
                else:
                    # No button clicked this iteration. Also try inputs of
                    # type=submit and bare <a> "Continue" links.
                    for sel in _POST_DUO_FALLBACK_SELECTORS:
                        try:
                            page.locator(sel).first.click(timeout=600)
                            break
                        except Exception:
                            continue
                last_diag_url = current_url
                page.wait_for_timeout(1500)
            else:
                # Loop ran out the clock without breaking on success.
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)
                except Exception as exc:
                    # Non-fatal: fall back to empty body text for the
                    # diagnostic keyword checks below.
                    logger.debug("Could not read page body text for SSO diagnostics", exc_info=exc)
                lowered = body_text.lower()
                url = page.url or last_diag_url
                if "shib.bu.edu" in url:
                    if any(k in lowered for k in ("login failed", "incorrect", "invalid")):
                        raise GradescopeAuthError(
                            "BU login failed — username or password is incorrect."
                        )
                    if any(k in lowered for k in ("denied", "rejected", "declined")):
                        raise GradescopeAuthError(
                            "Duo push was denied. Try again and tap Approve."
                        )
                    if "captcha" in lowered:
                        raise GradescopeAuthError(
                            "BU WebLogin asked for a CAPTCHA — the automated flow "
                            "can't solve those. Use cookie paste instead."
                        )
                    raise GradescopeDuoTimeout(
                        f"Stuck on Shibboleth after Duo for {duo_timeout_seconds}s. "
                        f"{_dump_page_state(page)}"
                    )
                raise GradescopeAuthError(
                    f"SSO ended at an unexpected URL: {url}. {_dump_page_state(page)}"
                )

            # Step 6: Tiny settle so cookies are committed by the browser
            # before we read them. domcontentloaded fires fast and is
            # enough — networkidle waits for trailing analytics calls,
            # which we don't care about.
            try:
                page.wait_for_load_state("domcontentloaded", timeout=4000)
            except PlaywrightTimeoutError:
                # Intentional non-fatal: the settle is best-effort; continue
                # to the cookie-harvest checks even if the load state lags.
                logger.debug("Timed out waiting for domcontentloaded; continuing with cookie harvest checks.")

            if "/login" in (page.url or ""):
                raise GradescopeAuthError(
                    "Reached Gradescope but it bounced us back to /login — "
                    "SAML assertion may have been rejected."
                )

            # Step 7: Harvest the Gradescope session cookies.
            all_cookies = context.cookies()
            gs_cookies = {
                c["name"]: c["value"]
                for c in all_cookies
                if "gradescope.com" in (c.get("domain") or "")
            }
            if "_gradescope_session" not in gs_cookies:
                raise GradescopeAuthError(
                    "Couldn't find a Gradescope session cookie after SSO. "
                    f"Found: {list(gs_cookies.keys())}"
                )

            return {
                "_gradescope_session": gs_cookies["_gradescope_session"],
                "signed_token": gs_cookies.get("signed_token", "") or "",
            }
        finally:
            try:
                browser.close()
            except Exception as _close_err:
                logger.debug("browser.close() failed: %s", _close_err)
