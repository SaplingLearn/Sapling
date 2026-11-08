"""Generate the RLS step 2b policies and step 2c grants (docs/security/rls-step2-plan.md).

Every policy is TO authenticated and anchored on app_auth.uid() (step 2a).
Output is idempotent: DROP POLICY IF EXISTS before each CREATE, and GRANT is
idempotent by nature. Both bodies are wrapped in a DO block that returns early
on a bare Postgres without the `authenticated` role, like the repo's other
role-touching migrations.

Usage (from the repo root):
    python docs/security/rls-step2/gen_policies.py policies          # body of <ts>_rls_policies.sql
    python docs/security/rls-step2/gen_policies.py grants            # body of <ts>_rls_authenticated_grants.sql
    python docs/security/rls-step2/gen_policies.py reverse-policies  # DROP POLICY list (header comment)
    python docs/security/rls-step2/gen_policies.py reverse-grants    # REVOKE list (header comment)
    python docs/security/rls-step2/gen_policies.py buckets           # JSON: bucket -> tables
    python docs/security/rls-step2/gen_policies.py check < tables.txt
        # one public table name per line (e.g. from a replayed schema); exits 1
        # unless every live table is in a bucket and every bucket table exists.

History:
  * 2026-11-08 first draft (m2_policies.sql / m3_grants.sql), against main +
    #805 + #807.
  * 2026-11-08 W2a, for the real migrations. Schema re-checked against a full
    replay (main + 2a): still the same 68 tables, so no inventory change. Two
    policy fixes found while writing the cross-user tests:
      - rooms SELECT also admits `owner_id = U`. The backend inserts with
        `Prefer: return=representation`, so the new row must pass the SELECT
        policy; the owner of a just-created PRIVATE room is not a member yet,
        so the draft's `is_public OR is_room_member(id)` refused the RETURNING.
      - room_members SELECT also admits `user_id = U` (own membership rows).
        is_room_member() is a STABLE SQL function and reads the statement's
        snapshot, which does not contain the row being inserted, so the
        draft's predicate refused the RETURNING of a user's own join.
    Both are the caller's own rows, so neither widens cross-user access.
"""
import json
import sys

U = "(SELECT app_auth.uid())"
policies: list[tuple[str, str, str]] = []   # (table, name, CREATE POLICY statement)
grants: list[tuple[str, str]] = []          # (table, privilege spec)


def pol(table, name, cmd, using=None, check=None):
    assert len(name) <= 63, name
    s = f"CREATE POLICY {name} ON public.{table} FOR {cmd} TO authenticated"
    if using:
        s += f"\n    USING ({using})"
    if check:
        s += f"\n    WITH CHECK ({check})"
    policies.append((table, name, s))


def owner(table, pred, cmds="SIUD", prefix=None):
    p = prefix or table
    if "S" in cmds:
        pol(table, f"{p}_select_own", "SELECT", using=pred)
    if "I" in cmds:
        pol(table, f"{p}_insert_own", "INSERT", check=pred)
    if "U" in cmds:
        pol(table, f"{p}_update_own", "UPDATE", using=pred, check=pred)
    if "D" in cmds:
        pol(table, f"{p}_delete_own", "DELETE", using=pred)


def grant(table, privs):
    grants.append((table, privs))


own = f"user_id = {U}"

# ---- Bucket inventory (plan §1.2–§1.6) ------------------------------------
# Every public table must be in exactly one bucket; `check` enforces it and
# backend/tests/integration/test_rls_policies_db.py pins the same lists.
BUCKETS = {
    "A_owned": [
        "users", "user_profiles", "user_settings", "oauth_tokens", "gradescope_credentials",
        "enrollments", "documents", "notes", "flashcards", "sessions", "quiz_attempts",
        "quiz_context", "study_guides", "graph_nodes", "graph_edges", "feedback",
        "issue_reports", "user_achievements", "user_cosmetics", "user_roles", "xp_events",
        "friend_requests", "friendships",
    ],
    "B_via_parent": [
        "messages", "node_mastery_events", "note_concepts", "quiz_responses",
        "gradebook_categories", "assignments", "gradescope_course_links", "topic_checklists",
        "topic_checklist_progress",
    ],
    "C_shared": [
        "rooms", "room_members", "room_bans", "room_messages", "room_reactions",
        "room_activity", "room_summaries", "offering_concept_stats", "offering_summary",
        "course_chunks", "course_chunk_contributors", "course_chunk_sources",
    ],
    "D_catalog": [
        "schools", "terms", "courses", "course_offerings", "achievements",
        "achievement_triggers", "achievement_cosmetics", "cosmetics", "roles",
        "role_cosmetics", "growth_stages", "xp_rules",
    ],
    "E_service_only": [
        "events", "llm_usage", "feature_flags", "feature_flag_targets", "admin_audit_log",
        "email_broadcasts", "email_sends", "email_suppressions", "newsletter_emails",
        "job_applications", "encryption_key_check", "schema_migrations", "jobs",
    ],
}
# room_messages is bucket C but gets its policy and grants in step 2e (the
# realtime JWT bridge), so nothing below touches it.
DEFERRED = {"room_messages"}

# ---- Bucket A: owned directly -------------------------------------------
owner("users", f"id = {U}", "S"); grant("users", "SELECT")
owner("user_profiles", own, "SIU"); grant("user_profiles", "SELECT, INSERT, UPDATE")
owner("user_settings", own, "SIU"); grant("user_settings", "SELECT, INSERT, UPDATE")
for t in ("oauth_tokens", "gradescope_credentials", "enrollments", "notes",
          "flashcards", "sessions", "quiz_attempts", "quiz_context",
          "study_guides", "graph_nodes", "graph_edges"):
    owner(t, own); grant(t, "SELECT, INSERT, UPDATE, DELETE")
owner("documents", own)
grant("documents", "SELECT, INSERT, DELETE")
# Not the index_* lease columns (document_indexing owns them, svc), nor id /
# user_id / request_id / created_at (set once at insert).
DOCUMENTS_UPDATABLE = (
    "file_name", "category", "summary", "concept_notes", "flashcards", "processed_at",
    "deleted_at", "extracted_text", "shareability", "shareability_confidence", "offering_id",
)
grant("documents", f"UPDATE ({', '.join(DOCUMENTS_UPDATABLE)})")
for t in ("feedback", "issue_reports"):
    owner(t, own, "SI"); grant(t, "SELECT, INSERT")
owner("user_achievements", own, "SU")
grant("user_achievements", "SELECT"); grant("user_achievements", "UPDATE (is_featured)")
for t in ("user_cosmetics", "user_roles", "xp_events"):
    owner(t, own, "S"); grant(t, "SELECT")
fr = f"from_user_id = {U} OR to_user_id = {U}"
pol("friend_requests", "friend_requests_select_party", "SELECT", using=fr)
pol("friend_requests", "friend_requests_insert_sender", "INSERT", check=f"from_user_id = {U}")
pol("friend_requests", "friend_requests_update_party", "UPDATE", using=fr, check=fr)
pol("friend_requests", "friend_requests_delete_party", "DELETE", using=fr)
grant("friend_requests", "SELECT, INSERT, UPDATE, DELETE")
fs = f"user_id = {U} OR friend_id = {U}"
pol("friendships", "friendships_select_party", "SELECT", using=fs)
pol("friendships", "friendships_insert_party", "INSERT", check=fs)
pol("friendships", "friendships_delete_party", "DELETE", using=fs)
grant("friendships", "SELECT, INSERT, DELETE")


# ---- Bucket B: owned through a parent -----------------------------------
def via(parent, fk, pk="id", col="user_id"):
    return (f"EXISTS (SELECT 1 FROM public.{parent} p "
            f"WHERE p.{pk} = {fk} AND p.{col} = {U})")


owner("messages", via("sessions", "messages.session_id"))
owner("node_mastery_events", via("graph_nodes", "node_mastery_events.node_id"), "SI")
nc = (via("notes", "note_concepts.note_id") + " AND " +
      via("graph_nodes", "note_concepts.concept_node_id"))
owner("note_concepts", nc, "SID")
owner("quiz_responses", via("quiz_attempts", "quiz_responses.attempt_id"))
for t in ("gradebook_categories", "assignments", "gradescope_course_links",
          "topic_checklists", "topic_checklist_progress"):
    owner(t, f"(SELECT app_auth.owns_enrollment({t}.enrollment_id))")
grant("messages", "SELECT, INSERT, UPDATE, DELETE")
grant("node_mastery_events", "SELECT, INSERT")
grant("note_concepts", "SELECT, INSERT, DELETE")
for t in ("quiz_responses", "gradebook_categories", "assignments",
          "gradescope_course_links", "topic_checklists", "topic_checklist_progress"):
    grant(t, "SELECT, INSERT, UPDATE, DELETE")

# ---- Bucket C: shared ----------------------------------------------------
member = "(SELECT app_auth.is_room_member({}))"
pol("rooms", "rooms_select_visible", "SELECT",
    using=f"{U} IS NOT NULL AND (is_public OR owner_id = {U} OR {member.format('rooms.id')})")
pol("rooms", "rooms_insert_owner", "INSERT", check=f"owner_id = {U} AND created_by = {U}")
pol("rooms", "rooms_update_owner", "UPDATE", using=f"owner_id = {U}",
    check=f"owner_id = {U}")
grant("rooms", "SELECT, INSERT, UPDATE")
pol("room_members", "room_members_select_self_or_comember", "SELECT",
    using=f"user_id = {U} OR {member.format('room_members.room_id')}")
pol("room_members", "room_members_insert_self", "INSERT",
    check=(f"user_id = {U} AND NOT EXISTS (SELECT 1 FROM public.room_bans b "
           f"WHERE b.room_id = room_members.room_id AND b.user_id = {U}) AND ("
           f"(SELECT app_auth.owns_room(room_members.room_id)) OR EXISTS (SELECT 1 FROM public.rooms r "
           f"WHERE r.id = room_members.room_id AND r.is_public))"))
pol("room_members", "room_members_delete_self_or_owner", "DELETE",
    using=f"user_id = {U} OR (SELECT app_auth.owns_room(room_members.room_id))")
grant("room_members", "SELECT, INSERT, DELETE")
pol("room_bans", "room_bans_select_owner_or_self", "SELECT",
    using=f"user_id = {U} OR (SELECT app_auth.owns_room(room_bans.room_id))")
pol("room_bans", "room_bans_write_owner", "INSERT",
    check=f"banned_by = {U} AND (SELECT app_auth.owns_room(room_bans.room_id))")
pol("room_bans", "room_bans_update_owner", "UPDATE",
    using="(SELECT app_auth.owns_room(room_bans.room_id))",
    check=f"banned_by = {U} AND (SELECT app_auth.owns_room(room_bans.room_id))")
pol("room_bans", "room_bans_delete_owner", "DELETE", using="(SELECT app_auth.owns_room(room_bans.room_id))")
grant("room_bans", "SELECT, INSERT, UPDATE, DELETE")
for t in ("room_activity",):
    pol(t, f"{t}_select_member", "SELECT", using=member.format(f"{t}.room_id"))
    pol(t, f"{t}_insert_member", "INSERT", check=f"user_id = {U} AND " + member.format(f"{t}.room_id"))
    grant(t, "SELECT, INSERT")
pol("room_summaries", "room_summaries_select_member", "SELECT", using=member.format("room_summaries.room_id"))
grant("room_summaries", "SELECT")
msg_room = ("EXISTS (SELECT 1 FROM public.room_messages m WHERE m.id = room_reactions.message_id "
            "AND (SELECT app_auth.is_room_member(m.room_id)))")
pol("room_reactions", "room_reactions_select_member", "SELECT", using=msg_room)
pol("room_reactions", "room_reactions_insert_self", "INSERT", check=f"user_id = {U} AND {msg_room}")
pol("room_reactions", "room_reactions_delete_self", "DELETE", using=f"user_id = {U}")
grant("room_reactions", "SELECT, INSERT, DELETE")
# room_messages: step 2e (with the realtime bridge), kept out of this file.

for t in ("offering_concept_stats", "offering_summary"):
    pol(t, f"{t}_select_enrolled", "SELECT", using=f"(SELECT app_auth.enrolled_in_offering({t}.offering_id))")
    grant(t, "SELECT")
cc = (f"{U} IS NOT NULL AND (visibility = 'shared' OR uploader_id = {U} OR EXISTS "
      f"(SELECT 1 FROM public.course_chunk_contributors k WHERE k.chunk_id = course_chunks.id AND k.user_id = {U}))")
pol("course_chunks", "course_chunks_select_readable", "SELECT", using=cc)
grant("course_chunks", "SELECT")
pol("course_chunk_contributors", "course_chunk_contributors_select_own", "SELECT", using=own)
grant("course_chunk_contributors", "SELECT")
pol("course_chunk_sources", "course_chunk_sources_select_readable", "SELECT",
    using="EXISTS (SELECT 1 FROM public.course_chunks c WHERE c.id = course_chunk_sources.chunk_id)")
grant("course_chunk_sources", "SELECT")

# ---- Bucket D: catalog ---------------------------------------------------
for t in BUCKETS["D_catalog"]:
    pol(t, f"{t}_select_signed_in", "SELECT", using=f"{U} IS NOT NULL")
    grant(t, "SELECT")

# ---- functions the request path calls -------------------------------------
# Both SECURITY INVOKER: RLS on course_chunks / graph_nodes still applies inside.
FUNCTIONS = [
    "public.match_course_chunks(vector, integer, text, text)",
    "public.apply_mastery_delta(text, text, double precision, double precision, "
    "double precision, double precision)",
]


def _self_check():
    all_tables = [t for ts in BUCKETS.values() for t in ts]
    dup = {t for t in all_tables if all_tables.count(t) > 1}
    assert not dup, f"tables in more than one bucket: {dup}"
    touched = {t for t, _, _ in policies} | {t for t, _ in grants}
    service_only = set(BUCKETS["E_service_only"])
    assert not touched & service_only, touched & service_only
    assert not touched & DEFERRED, touched & DEFERRED
    expected = set(all_tables) - service_only - DEFERRED
    assert touched == expected, (expected - touched, touched - expected)
    names = [n for _, n, _ in policies]
    assert len(names) == len(set(names)), "duplicate policy name"


def _do_block(stmts):
    lines = ["DO $$",
             "BEGIN",
             "    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN",
             "        RETURN;",
             "    END IF;"]
    for s in stmts:
        body = s.replace("\n", "\n        ")
        lines.append(f"    EXECUTE $q${body}$q$;")
    lines.append("END $$;")
    return "\n".join(lines)


def main(argv):
    _self_check()
    which = argv[1] if len(argv) > 1 else "policies"
    if which == "policies":
        stmts = []
        for table, name, create in policies:
            stmts.append(f"DROP POLICY IF EXISTS {name} ON public.{table}")
            stmts.append(create)
        print(_do_block(stmts))
    elif which == "grants":
        stmts = [f"GRANT {privs} ON public.{t} TO authenticated" for t, privs in grants]
        stmts += [f"GRANT EXECUTE ON FUNCTION {f} TO authenticated" for f in FUNCTIONS]
        print(_do_block(stmts))
    elif which == "reverse-policies":
        for table, name, _ in policies:
            print(f"DROP POLICY IF EXISTS {name} ON public.{table};")
    elif which == "reverse-grants":
        for t, privs in grants:
            print(f"REVOKE {privs} ON public.{t} FROM authenticated;")
        for f in FUNCTIONS:
            print(f"REVOKE EXECUTE ON FUNCTION {f} FROM authenticated;")
    elif which == "buckets":
        print(json.dumps(BUCKETS, indent=1))
    elif which == "check":
        live = {ln.strip() for ln in sys.stdin if ln.strip()}
        bucketed = {t for ts in BUCKETS.values() for t in ts}
        unbucketed, gone = sorted(live - bucketed), sorted(bucketed - live)
        print(f"{len(live)} live tables; {len(bucketed)} bucketed; "
              + ", ".join(f"{k}={len(v)}" for k, v in BUCKETS.items()))
        print(f"{len(policies)} policies on {len({t for t, _, _ in policies})} tables; "
              f"{len(grants)} grant lines on {len({t for t, _ in grants})} tables; "
              f"{len(FUNCTIONS)} function grants")
        if unbucketed or gone:
            print(f"FAIL: in no bucket: {unbucketed}; bucketed but absent: {gone}")
            return 1
        print("OK: every public table is in exactly one bucket")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
