"""
backend/services/admin/analytics/ — the admin analytics domain (#118).

``routes/admin_analytics.py`` keeps the endpoints (auth, query params, the
per-endpoint rollups); the shared pieces live here:

- ``models``: the response models.
- ``scan``: range resolution and the capped, paged range scan.
- ``series``: day bucketing for ``?bucket=day``.
- ``db_scope``: grouping for the ``db_user_scope`` rollout report (was
  ``services/admin_db_scope.py``, which stays as a re-export shim).
"""
from __future__ import annotations

from services.admin.analytics import db_scope, models, scan, series  # noqa: F401

__all__ = ["db_scope", "models", "scan", "series"]
