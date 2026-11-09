"""
Admin routes — role, achievement, cosmetic, and user management.
All routes require admin role.

The handlers check the caller and call ``services/admin/`` (#118), which
holds the reads, writes and audit logging; ``_admin_errors`` maps that
package's domain errors to the status codes these routes always answered.
"""

import logging
from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from db.connection import table
from models import (
    CreateRoleBody,
    AssignRoleBody,
    RevokeRoleBody,
    CreateAchievementBody,
    CreateAchievementTriggerBody,
    UpdateAchievementTriggerBody,
    GrantAchievementBody,
    CreateCosmeticBody,
    LinkAchievementCosmeticBody,
    LinkRoleCosmeticBody,
    AllowlistEmailBody,
    AllowlistBulkBody,
    AchievementIconBody,
    UpdateXpRuleBody,
)
from services.admin import (
    AdminError,
    Conflict,
    InvalidRequest,
    NotFound,
    Unprocessable,
    achievements,
    allowlist,
    audit,
    cosmetics,
    feedback,
    overview,
    roles,
    users,
    xp_rules,
)
from routes._errors import domain_status
from services.admin_audit import log_admin_action
from services.auth_guard import require_admin, get_session_user_id
from routes.admin_flags import record_flag_change
from services.feature_flags import clear_feature_flags_cache, clear_user_roles_cache
from services.users_search import paginate_users

# Moved to services/admin/ (#118); re-exported so imports and patches of the
# old names on this module keep working.
from services.admin.allowlist import (  # noqa: F401  (re-export, #118)
    _ALLOWLIST_COLUMNS,
    _APPROVE_COLUMNS,
    _IN_CHUNK,
    _approve_waitlist,
    _chunks,
    _grant_linked_accounts,
    _in_list,
    _send_statuses,
    _waitlist_rows,
    _with_invite_status,
)
from services.admin.roles import _admin_user_count, _role_slug  # noqa: F401  (re-export, #118)
from services.admin.users import _back_on_waitlist  # noqa: F401  (re-export, #118)

logger = logging.getLogger(__name__)

router = APIRouter()

_ERROR_STATUS = {InvalidRequest: 400, NotFound: 404, Conflict: 409, Unprocessable: 422}


@contextmanager
def _admin_errors():
    """Map a ``services.admin`` domain error to its HTTP status, same detail."""
    try:
        yield
    except AdminError as e:
        raise HTTPException(status_code=domain_status(e, _ERROR_STATUS), detail=e.detail)


# ── Roles ────────────────────────────────────────────────────────────────────

@router.get("/roles")
def list_roles(request: Request):
    require_admin(request)
    return roles.list_roles()


@router.post("/roles")
def create_role(body: CreateRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return roles.create_role(body, actor)


@router.patch("/roles/{role_id}")
def update_role(role_id: str, request: Request, body: dict = {}):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return roles.update_role(role_id, body, actor)


@router.post("/roles/assign")
def assign_role(body: AssignRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return roles.assign_role(body, actor)


@router.delete("/roles/revoke")
def revoke_role(body: RevokeRoleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return roles.revoke_role(body, actor)


@router.get("/roles/{role_id}/cosmetics")
def list_role_cosmetics(role_id: str, request: Request):
    require_admin(request)
    return roles.list_role_cosmetics(role_id)


@router.post("/roles/cosmetics")
def link_role_cosmetic(body: LinkRoleCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return roles.link_role_cosmetic(body, actor)


@router.delete("/roles/cosmetics")
def unlink_role_cosmetic(body: LinkRoleCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return roles.unlink_role_cosmetic(body, actor)


@router.delete("/roles/{role_id}")
def delete_role(role_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    if _role_slug(role_id) == "admin":
        raise HTTPException(status_code=409, detail="Cannot delete the admin role.")
    table("roles").delete(filters={"id": f"eq.{role_id}"})
    log_admin_action(actor_id=actor, action="role.delete", target_type="role", target_id=role_id)
    # #620: a role's flag rules name it by id with no FK, so they would
    # outlive it. Remove them, each audited like an admin rule delete.
    removed = table("feature_flag_targets").delete(
        filters={"target_type": "eq.role", "target_id": f"eq.{role_id}"},
    ) or []
    for rule in removed:
        record_flag_change(actor, rule["flag_key"], f"role:{role_id}", rule.get("variant"), None)
    clear_feature_flags_cache()
    clear_user_roles_cache()
    return {"deleted": True}


# ── Achievements ─────────────────────────────────────────────────────────────

@router.get("/achievements")
def list_achievements(request: Request):
    require_admin(request)
    return achievements.list_achievements()


@router.post("/achievements")
def create_achievement(body: CreateAchievementBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return achievements.create_achievement(body, actor)


@router.patch("/achievements/{achievement_id}")
def update_achievement(achievement_id: str, request: Request, body: dict = {}):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return achievements.update_achievement(achievement_id, body, actor)


@router.post("/achievements/{achievement_id}/icon")
def upload_icon(achievement_id: str, body: AchievementIconBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return achievements.upload_icon(achievement_id, body, actor)


@router.delete("/achievements/cosmetics")
def unlink_achievement_cosmetic(body: LinkAchievementCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return achievements.unlink_achievement_cosmetic(body, actor)


@router.delete("/achievements/{achievement_id}")
def delete_achievement(achievement_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return achievements.delete_achievement(achievement_id, actor)


@router.post("/achievements/grant")
def grant_achievement(body: GrantAchievementBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return achievements.grant_achievement(body, actor)


@router.post("/achievements/triggers")
def create_trigger(body: CreateAchievementTriggerBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return achievements.create_trigger(body, actor)


@router.get("/achievements/{achievement_id}/triggers")
def list_triggers(achievement_id: str, request: Request):
    require_admin(request)
    return achievements.list_triggers(achievement_id)


@router.patch("/achievements/triggers/{trigger_id}")
def update_trigger(trigger_id: str, body: UpdateAchievementTriggerBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return achievements.update_trigger(trigger_id, body, actor)


@router.delete("/achievements/triggers/{trigger_id}")
def delete_trigger(trigger_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return achievements.delete_trigger(trigger_id, actor)


@router.get("/achievements/{achievement_id}/cosmetics")
def list_achievement_cosmetics(achievement_id: str, request: Request):
    require_admin(request)
    return achievements.list_achievement_cosmetics(achievement_id)


@router.post("/achievements/cosmetics")
def link_achievement_cosmetic(body: LinkAchievementCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return achievements.link_achievement_cosmetic(body, actor)


# ── XP rules ─────────────────────────────────────────────────────────────────

@router.get("/xp-rules")
def list_xp_rules(request: Request):
    require_admin(request)
    return xp_rules.list_xp_rules()


@router.patch("/xp-rules/{key}")
def update_xp_rule(key: str, body: UpdateXpRuleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return xp_rules.update_xp_rule(key, body, actor)


# ── Cosmetics ────────────────────────────────────────────────────────────────

@router.get("/cosmetics")
def list_cosmetics(request: Request):
    require_admin(request)
    return cosmetics.list_cosmetics()


@router.post("/cosmetics")
def create_cosmetic(body: CreateCosmeticBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return cosmetics.create_cosmetic(body, actor)


@router.patch("/cosmetics/{cosmetic_id}")
def update_cosmetic(cosmetic_id: str, request: Request, body: dict = {}):
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return cosmetics.update_cosmetic(cosmetic_id, body, actor)


@router.delete("/cosmetics/{cosmetic_id}")
def delete_cosmetic(cosmetic_id: str, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    return cosmetics.delete_cosmetic(cosmetic_id, actor)


# ── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
def list_users(
    request: Request,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    require_admin(request)
    return paginate_users(q=q, page=page, page_size=page_size)


@router.patch("/users/{user_id}/unapprove")
def unapprove_user(user_id: str, request: Request):
    """Remove a user's access. They leave Admin → Users and reappear in
    Admin → Allowlist as a signup; their account and data are kept."""
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return users.unapprove_user(user_id, actor)


# ── Newsletter Allowlist ──────────────────────────────────────────────────────

@router.get("/allowlist")
def list_allowlist(request: Request):
    # #130: the admin portal's adminListAllowlist() (frontend/src/lib/api.ts)
    # reads this list; approve/revoke existed without the GET.
    require_admin(request)
    return allowlist.list_allowlist()


@router.post("/allowlist/approve")
def approve_allowlist(body: AllowlistEmailBody, request: Request, background_tasks: BackgroundTasks):
    """Approve one address — the bulk path's rules for a single email (#757):
    normalised, case twins reached, `approved_at` never re-stamped, and an
    existing account let in at once."""
    require_admin(request)
    actor = get_session_user_id(request)
    return allowlist.approve_allowlist(body, actor, background_tasks)


@router.post("/allowlist/approve-bulk")
def approve_allowlist_bulk(body: AllowlistBulkBody, request: Request, background_tasks: BackgroundTasks):
    """Approve up to 500 addresses at once (rules: `_approve_waitlist`)."""
    require_admin(request)
    actor = get_session_user_id(request)
    return allowlist.approve_allowlist_bulk(body, actor, background_tasks)


@router.post("/allowlist/revoke")
def revoke_allowlist(body: AllowlistEmailBody, request: Request):
    """Take an address's approval back — and the access it granted (#757).

    Reaches every case twin (sign-in reads the approved twin, so revoking only
    the exact spelling could leave it approved), clears the "joined" stamp so
    no row reads "joined but not approved", and sets the linked account's
    `users.is_approved` to false at once instead of leaving it signed in.
    `joined_user_id` is kept: it is the only link back to the account
    (users.email is nonce-encrypted), which a re-approve or a retried revoke
    needs. The waitlist is written first so a failed account write is retried
    by the admin repeating the revoke, never undone by the student's next
    sign-in re-reading an approved row.
    """
    require_admin(request)
    actor = get_session_user_id(request)
    with _admin_errors():
        return allowlist.revoke_allowlist(body, actor)


# ── Feedback + issue reports (#520) ──────────────────────────────────────────
# These tables are 🔒 at rest (comment/topic/description); the Supabase
# dashboard shows ciphertext, so this is the only human-readable surface.

@router.get("/feedback")
def list_feedback(request: Request, limit: int = 200):
    require_admin(request)
    return feedback.list_feedback(limit)


@router.get("/issue-reports")
def list_issue_reports(request: Request, limit: int = 200):
    require_admin(request)
    return feedback.list_issue_reports(limit)


# ── Audit log ────────────────────────────────────────────────────────────────

@router.get("/audit")
def list_audit(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[str] = None,
):
    require_admin(request)
    return audit.list_audit(page, page_size, action, target_type, actor_id)


# ── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics/overview")
def analytics_overview(request: Request):
    require_admin(request)
    return overview.analytics_overview()
