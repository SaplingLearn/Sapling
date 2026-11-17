"""
backend/services/admin_db_scope.py — alias shim (#118).

The db_user_scope report grouping moved to
``services/admin/analytics/db_scope.py``. This path stays so existing imports
and patch targets (``patch("services.admin_db_scope.<name>")``) keep working:
the old name is bound to the SAME module object, so a patch through either
name reaches the code that runs. New code imports
``services.admin.analytics.db_scope``.
"""
import sys

from services.admin.analytics import db_scope as _db_scope

sys.modules[__name__] = _db_scope
