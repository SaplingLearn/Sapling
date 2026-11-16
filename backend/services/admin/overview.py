"""
backend/services/admin/overview.py

``GET /api/admin/analytics/overview``: user/role/waitlist totals and the
30-day signup + approval series.

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from db.connection import table


def analytics_overview():

    users = table("users").select("id,is_approved,created_at") or []
    roles = table("roles").select("id,slug,name,color") or []
    user_roles = table("user_roles").select("role_id") or []

    role_index = {r["id"]: r for r in roles}
    role_counter: Counter = Counter()
    for ur in user_roles:
        role_counter[ur["role_id"]] += 1

    admin_role_ids = {r["id"] for r in roles if r.get("slug") == "admin"}
    admin_count = sum(c for rid, c in role_counter.items() if rid in admin_role_ids)

    approved = sum(1 for u in users if u.get("is_approved"))
    # Waiting on approval = waitlist signups not yet approved. Unapproved
    # sign-ins don't create accounts, so `users` can't answer this.
    waitlist = table("newsletter_emails").select("approved_at") or []
    totals = {
        "users": len(users),
        "approved": approved,
        "pending": sum(1 for w in waitlist if not w.get("approved_at")),
        "admins": admin_count,
    }

    today = datetime.now(timezone.utc).date()
    window = [today - timedelta(days=i) for i in range(29, -1, -1)]
    by_day_signups: Counter = Counter()
    for u in users:
        ca = u.get("created_at") or ""
        try:
            d = datetime.fromisoformat(ca.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if d in window:
            by_day_signups[d.isoformat()] += 1

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    approval_events = table("admin_audit_log").select(
        "created_at",
        filters={"action": "eq.user.approve", "created_at": f"gte.{cutoff}"},
    ) or []
    by_day_approvals: Counter = Counter()
    for ev in approval_events:
        ca = ev.get("created_at") or ""
        try:
            d = datetime.fromisoformat(ca.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        if d in window:
            by_day_approvals[d.isoformat()] += 1

    signups_by_day = [{"date": d.isoformat(), "count": by_day_signups.get(d.isoformat(), 0)} for d in window]
    approvals_by_day = [{"date": d.isoformat(), "count": by_day_approvals.get(d.isoformat(), 0)} for d in window]

    role_counts = []
    for rid, count in role_counter.items():
        r = role_index.get(rid)
        if not r:
            continue
        role_counts.append({"slug": r["slug"], "name": r["name"], "color": r["color"], "count": count})
    role_counts.sort(key=lambda x: x["count"], reverse=True)

    return {
        "totals": totals,
        "signups_by_day": signups_by_day,
        "approvals_by_day": approvals_by_day,
        "role_counts": role_counts,
    }
