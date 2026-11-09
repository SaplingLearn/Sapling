"""Auth domain errors (#118). ``routes/auth.py`` maps them to HTTP."""


class AccountNotFound(LookupError):
    """No ``users`` row for the session's id (``GET /me`` answers 404)."""


class AccountDeleted(Exception):
    """The account is soft-deleted (``GET /me`` answers 401)."""
