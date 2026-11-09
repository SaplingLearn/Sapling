"""
backend/services/admin_db_scope.py — re-export shim (#118).

The db_user_scope report grouping moved to
``services/admin/analytics/db_scope.py``. This path stays so existing imports
keep working; new code imports ``services.admin.analytics.db_scope``.
"""
from services.admin.analytics.db_scope import (  # noqa: F401  (re-export, #118)
    _RAW_FIELDS,
    _SAMPLE_RIDS,
    _as_int,
    _new_group,
    _span,
    group_rows,
    group_rpc_rows,
    key_of,
    ranked,
)
