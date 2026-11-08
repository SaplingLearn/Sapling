"""Generate the draft policy migration (steps 2b/2c/2d) for the RLS plan.

Every policy is TO authenticated and anchored on app_auth.uid(). Output is
idempotent: DROP POLICY IF EXISTS before each CREATE.
"""
import sys

U = "(SELECT app_auth.uid())"
out: list[str] = []
grants: list[str] = []


def pol(table, name, cmd, using=None, check=None):
    out.append(f"DROP POLICY IF EXISTS {name} ON public.{table};")
    s = f"CREATE POLICY {name} ON public.{table} FOR {cmd} TO authenticated"
    if using:
        s += f"\n    USING ({using})"
    if check:
        s += f"\n    WITH CHECK ({check})"
    out.append(s + ";")


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
    grants.append(f"GRANT {privs} ON public.{table} TO authenticated;")


own = f"user_id = {U}"

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
grant("documents", "UPDATE (file_name, category, summary, concept_notes, flashcards, "
      "processed_at, deleted_at, extracted_text, shareability, shareability_confidence, offering_id)")
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
    using=f"{U} IS NOT NULL AND (is_public OR {member.format('rooms.id')})")
pol("rooms", "rooms_insert_owner", "INSERT", check=f"owner_id = {U} AND created_by = {U}")
pol("rooms", "rooms_update_owner", "UPDATE", using=f"owner_id = {U}",
    check=f"owner_id = {U}")
grant("rooms", "SELECT, INSERT, UPDATE")
pol("room_members", "room_members_select_comember", "SELECT", using=member.format("room_members.room_id"))
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
for t in ("schools", "terms", "courses", "course_offerings", "achievements",
          "achievement_triggers", "achievement_cosmetics", "cosmetics", "roles",
          "role_cosmetics", "growth_stages", "xp_rules"):
    pol(t, f"{t}_select_signed_in", "SELECT", using=f"{U} IS NOT NULL")
    grant(t, "SELECT")

# ---- functions the request path calls -------------------------------------
fn = ["GRANT EXECUTE ON FUNCTION public.match_course_chunks(vector, integer, text, text) TO authenticated;",
      "GRANT EXECUTE ON FUNCTION public.apply_mastery_delta(text, text, double precision, "
      "double precision, double precision, double precision) TO authenticated;"]

which = sys.argv[1] if len(sys.argv) > 1 else "policies"
if which == "policies":
    print("\n".join(out))
else:
    print("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN RETURN; END IF;")
    for g in grants + fn:
        print(f"  EXECUTE $q${g.rstrip(';')}$q$;")
    print("END $$;")
