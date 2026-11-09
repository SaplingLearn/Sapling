"""Auth domain (#118): OAuth state, the account side of a Google sign-in,
the /pending token and waitlist, the ``/me`` overview and the test-login
gate. ``routes/auth.py`` is the HTTP layer over these.

``services/session_tokens.py`` (the session wire format) and
``services/auth_guard.py`` (the request guard) are CLAUDE.md chokepoints and
stay where they are.
"""
from services.auth.accounts import account_overview
from services.auth.errors import AccountDeleted, AccountNotFound
from services.auth.signin import (
    SignInResult,
    fetch_google_userinfo,
    record_google_sign_in,
    welcome_and_achievements_after_sign_in,
)
from services.auth.waitlist import join_waitlist

__all__ = [
    "AccountDeleted",
    "AccountNotFound",
    "SignInResult",
    "account_overview",
    "fetch_google_userinfo",
    "join_waitlist",
    "record_google_sign_in",
    "welcome_and_achievements_after_sign_in",
]
