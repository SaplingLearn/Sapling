"""Every service-role opt-out under the `db_user_scope` flag, with its reason (#115).

docs/security/rls-step2-plan.md §4.4: once the flag is past ``off`` a request's
PostgREST calls run as the student, and each place that deliberately keeps the
service role (``@runs_as_service``, ``with service_scope()``, a
``service_route`` / ``admin_service_route`` dependency on an endpoint or a
router mount) bypasses RLS. This test finds them all by AST and compares the
set with ``ALLOWLIST`` below, in the style of ``test_migration_naming.py``: a
new opt-out fails CI until it is listed here with a one-line reason, so it
shows up in review instead of quietly widening the service-role surface. A
removed one fails too, so the list never claims an opt-out that is gone.

(Outside a request every call is service role with no marker at all: lifespan
workers, the sweeper, scripts and seeds. Those are not listed.)
"""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

#: (file, function | "<prefix> <router>", kind) -> why it keeps the service role.
ALLOWLIST: dict[tuple[str, str, str], str] = {
    # ── Router mounts (main.py) ──
    ("main.py", "/api/admin admin_router", "admin_service_route"): "admin portal: every user's rows",
    ("main.py", "/api/admin/accounts admin_accounts_router", "admin_service_route"):
        "#804 seed/wipe/copy account tools: other users' rows",
    ("main.py", "/api/admin/accounts admin_account_sync_router", "admin_service_route"):
        "#804 cross-environment account copy",
    ("main.py", "/api/admin/analytics admin_analytics_router", "admin_service_route"):
        "events/llm_usage rollups (service-only tables)",
    ("main.py", "/api/admin/documents admin_documents_router", "admin_service_route"):
        "stuck-index listing + forced re-index (index_* lease, shared chunks)",
    ("main.py", "/api/admin/email admin_email_router", "admin_service_route"): "email_* tables are service-only",
    ("main.py", "/api/admin/flags admin_flags_router", "admin_service_route"): "feature_flags is service-only",
    ("main.py", "gemini_test", "admin_service_route"): "admin LLM probe (records usage)",
    ("main.py", "/api/auth auth.router", "service_route"):
        "OAuth callback / test-login / pending: run before a session exists; users is account state",
    ("main.py", "/api/careers careers.router", "service_route"): "public; job_applications is service-only",
    ("main.py", "/api/email email_router", "service_route"): "public unsubscribe; email_suppressions is service-only",
    ("main.py", "/api/internal internal_metrics_router", "service_route"):
        "server-to-server bearer; canopy_metrics() is service_role-only",
    ("main.py", "/api/internal/account-sync internal_account_sync_router", "service_route"):
        "server-to-server bearer account copy",
    ("main.py", "/api/newsletter newsletter_router", "service_route"): "public; newsletter_emails is service-only",
    ("main.py", "/api/social social.router", "service_route"):
        "until step 2e: room_messages has no policies; invite join/owner transfer/teardown/"
        "friendships are cross-user (plan §6.3: social last)",
    # ── Endpoints ──
    ("routes/academics.py", "get_semesters", "service_route"): "public catalog read, no session",
    ("routes/calendar.py", "calendar_callback", "service_route"):
        "Google redirect: no session, user from the signed state cookie",
    ("routes/gamification.py", "get_leaderboard", "service_route"):
        "cross-user projection (everyone's weekly XP); scope + privacy applied in code",
    ("routes/onboarding.py", "search_courses", "service_route"): "public catalog search, no session",
    ("routes/onboarding.py", "save_onboarding_profile", "service_scope"):
        "users.onboarding_completed: users is SELECT-only for students",
    ("routes/profile.py", "check_username", "service_route"): "unauthenticated; looks at other users' usernames",
    ("routes/profile.py", "get_public_profile", "service_route"):
        "cross-user projection (anonymous too); creates the target's missing rows; visibility in code",
    ("routes/profile.py", "get_roles", "service_route"): "public roles of any user",
    ("routes/profile.py", "delete_account", "service_scope"): "users.deleted_at: account state",
    ("routes/quiz.py", "_daily_spend_exceeded", "runs_as_service"): "llm_usage is service-only (bucket E)",
    # ── Services ──
    ("services/academics.py", "resolve_offering", "service_scope"): "on-demand course_offerings insert (catalog)",
    ("services/academics.py", "school_peer_user_ids", "runs_as_service"): "reads other students' enrollments",
    ("services/achievement_service.py", "check_achievements", "runs_as_service"): "awards are server decisions",
    ("services/achievement_service.py", "get_user_stat", "runs_as_service"): "achievement counters",
    ("services/achievement_service.py", "grant_linked_cosmetics", "runs_as_service"): "cosmetic awards",
    ("services/admin_audit.py", "log_admin_action", "runs_as_service"): "admin_audit_log is service-only",
    ("services/auth_guard.py", "_read_account_state", "service_scope"):
        "decides whether the subject is a live account; runs before identity is trusted",
    ("services/auth_guard.py", "require_admin", "service_scope"): "authorization read of user_roles",
    ("services/auth_guard.py", "_checker", "service_scope"): "require_role: authorization read of user_roles",
    ("services/chunk_visibility.py", "record_contributors", "runs_as_service"): "course_chunk_contributors ledger",
    ("services/chunk_visibility.py", "record_sources", "runs_as_service"): "course_chunk_sources ledger",
    ("services/chunk_visibility.py", "resync_user_chunk_visibility", "runs_as_service"):
        "rewrites shared course_chunks visibility",
    ("services/chunk_visibility.py", "withdraw_document_chunks", "runs_as_service"):
        "rewrites shared course_chunks + ledgers",
    ("services/course_context_service.py", "_read_course_context", "runs_as_service"):
        "class aggregate behind a shared per-process cache",
    ("services/course_context_service.py", "update_course_context", "runs_as_service"):
        "class stats over every classmate (silently wrong under a user scope)",
    ("services/document_indexing.py", "index_document", "runs_as_service"):
        "owns documents.index_* lease + shared course_chunks",
    ("services/email_service.py", "is_suppressed", "runs_as_service"): "email_suppressions",
    ("services/email_service.py", "notification_opt_out_hashes", "runs_as_service"): "every user's opt-out",
    ("services/email_service.py", "send_email", "runs_as_service"): "email_sends/email_suppressions",
    ("services/email_service.py", "suppress", "runs_as_service"): "email_suppressions",
    ("services/email_service.py", "unsuppress", "runs_as_service"): "email_suppressions",
    ("services/events_service.py", "_flush_batch", "runs_as_service"): "events/llm_usage are service-only",
    ("services/events_service.py", "_flush_rows_individually", "runs_as_service"): "events/llm_usage",
    ("services/events_service.py", "_insert_late", "runs_as_service"): "events/llm_usage",
    ("services/feature_flags.py", "_user_roles", "service_scope"): "flag store (decides db_user_scope itself)",
    ("services/feature_flags.py", "read_config", "service_scope"): "flag store (decides db_user_scope itself)",
    ("services/graph_service.py", "ensure_user_exists", "runs_as_service"): "inserts a users row",
    ("services/profiles.py", "get_display_name", "runs_as_service"): "other users' names",
    ("services/profiles.py", "get_display_names", "runs_as_service"): "other users' names",
    ("services/rag_service.py", "index_document_chunks", "runs_as_service"): "shared content-addressed chunks",
    ("services/rag_service.py", "index_document_chunks_detailed", "runs_as_service"): "shared chunks",
    ("services/social_cache_service.py", "get_cached_summary", "runs_as_service"): "room_summaries cache",
    ("services/social_cache_service.py", "invalidate", "runs_as_service"): "room_summaries cache",
    ("services/social_cache_service.py", "save_summary", "runs_as_service"): "room_summaries cache",
    ("services/streak_service.py", "touch_streak", "runs_as_service"): "users streak columns",
    ("services/users_search.py", "paginate_users", "runs_as_service"): "admin directory of every user",
    ("services/xp_service.py", "award_xp", "runs_as_service"): "xp_events + users.total_xp",
    ("services/xp_service.py", "record_ledger_row", "runs_as_service"): "xp_events is SELECT-only for students",
    ("services/xp_service.py", "settle_ledger_writes", "runs_as_service"): "users.total_xp",
}


def _kind_of(segment: str) -> str | None:
    if "admin_service_route" in segment or "_ADMIN_SVC" in segment:
        return "admin_service_route"
    if "service_route" in segment or "_SVC" in segment:
        return "service_route"
    return None


def scan() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    files = [BACKEND / "main.py"] + sorted(
        p for d in ("routes", "services", "agents") for p in (BACKEND / d).rglob("*.py")
    )
    for path in files:
        rel = str(path.relative_to(BACKEND))
        src = path.read_text()
        tree = ast.parse(src)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def enclosing(n):
            while n in parents:
                n = parents[n]
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return n.name
            return "<module>"

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "runs_as_service":
                        found.add((rel, node.name, "runs_as_service"))
                    elif isinstance(dec, ast.Call):
                        kind = _kind_of(ast.get_source_segment(src, dec) or "")
                        if kind:
                            found.add((rel, node.name, kind))
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    call = item.context_expr
                    if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "service_scope":
                        found.add((rel, enclosing(node), "service_scope"))
            elif isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "include_router":
                deps = next((k.value for k in node.keywords if k.arg == "dependencies"), None)
                kind = _kind_of(ast.get_source_segment(src, deps) or "") if deps is not None else None
                if kind:
                    prefix = next(k.value.value for k in node.keywords if k.arg == "prefix")
                    found.add((rel, f"{prefix} {ast.get_source_segment(src, node.args[0])}", kind))
    return found


def test_every_service_role_opt_out_is_listed_with_a_reason():
    found = scan()
    unlisted = sorted(found - set(ALLOWLIST))
    stale = sorted(set(ALLOWLIST) - found)
    assert not unlisted, (
        "new service-role opt-out(s) under db_user_scope; add each to ALLOWLIST with a "
        f"one-line reason (they bypass RLS): {unlisted}"
    )
    assert not stale, f"ALLOWLIST names opt-outs that no longer exist; remove them: {stale}"
    assert all(reason.strip() for reason in ALLOWLIST.values())
