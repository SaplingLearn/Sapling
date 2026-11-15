"""Profile domain (#118): identity/profile/settings rows, the public
profile projection, cosmetics, the achievements view, the data export and
the student's own account delete.
``routes/profile.py`` is the HTTP layer over these.

Display-name resolution stays in ``services/profiles.py`` (a CLAUDE.md
chokepoint, unrelated to this package).
"""
from services.profile.account import export_account_data
from services.profile.achievements import (
    achievements_view,
    replace_featured_achievements,
)
from services.profile.cosmetics import cosmetics_catalog, owned_cosmetics_by_type
from services.profile.deletion import delete_account
from services.profile.errors import DeletionNotConfirmed, UserNotFound
from services.profile.public import public_profile

__all__ = [
    "DeletionNotConfirmed",
    "UserNotFound",
    "achievements_view",
    "cosmetics_catalog",
    "delete_account",
    "export_account_data",
    "owned_cosmetics_by_type",
    "public_profile",
    "replace_featured_achievements",
]
