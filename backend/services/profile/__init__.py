"""Profile domain (#118): identity/profile/settings rows, the public
profile projection, cosmetics, the achievements view and the data export.
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
from services.profile.errors import UserNotFound
from services.profile.public import public_profile

__all__ = [
    "UserNotFound",
    "achievements_view",
    "cosmetics_catalog",
    "export_account_data",
    "owned_cosmetics_by_type",
    "public_profile",
    "replace_featured_achievements",
]
