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
from services.open_access import ACCESS_OPEN, access_kind, gate_open, has_access


def analytics_overview():

    users = table("users").select("id,is_approved,open_access_at,created_at") or []
    roles = table("roles").select("id,slug,name,color") or []
    user_roles = table("user_roles").select("role_id") or []

    role_index = {r["id"]: r for r in roles}
    role_counter: Counter = Counter()
    for ur in user_roles:
        role_counter[ur["role_id"]] += 1

    admin_role_ids = {r["id"] for r in roles if r.get("slug") == "admin"}
    admin_count = sum(c for rid, c in role_counter.items() if rid in admin_role_ids)

    # People with access: approved, or in through the open gate while it is
    # open (services/open_access.py). `open_access` counts the latter alone.
    open_now = gate_open()
    approved = sum(1 for u in users if has_access(u, open_now=open_now))
    open_ids = {u.get("id") for u in users if access_kind(u, open_now=open_now) == ACCESS_OPEN}
    # Waiting on approval = waitlist signups not yet approved. Unapproved
    # sign-ins don't create accounts, so `users` can't answer this. An
    # open-access entrant's row is unapproved too, but while the gate is open
    # they are in, not waiting (they are counted under `open_access`).
    waitlist = table("newsletter_emails").select("approved_at,joined_user_id") or []
    totals = {
        "users": len(users),
        "approved": approved,
        "open_access": len(open_ids),
        "pending": sum(
            1 for w in waitlist
            if not w.get("approved_at") and w.get("joined_user_id") not in open_ids
        ),
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
