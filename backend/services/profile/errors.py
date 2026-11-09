"""Profile domain errors (#118). The route layer maps them to HTTP."""


class UserNotFound(LookupError):
    """The account is missing, soft-deleted, or its 1:1 row vanished.

    ``routes/profile.py`` answers it as ``404 {"detail": "User not found"}``.
    """
