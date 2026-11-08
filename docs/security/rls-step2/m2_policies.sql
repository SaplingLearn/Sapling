DROP POLICY IF EXISTS users_select_own ON public.users;
CREATE POLICY users_select_own ON public.users FOR SELECT TO authenticated
    USING (id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_profiles_select_own ON public.user_profiles;
CREATE POLICY user_profiles_select_own ON public.user_profiles FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_profiles_insert_own ON public.user_profiles;
CREATE POLICY user_profiles_insert_own ON public.user_profiles FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_profiles_update_own ON public.user_profiles;
CREATE POLICY user_profiles_update_own ON public.user_profiles FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_settings_select_own ON public.user_settings;
CREATE POLICY user_settings_select_own ON public.user_settings FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_settings_insert_own ON public.user_settings;
CREATE POLICY user_settings_insert_own ON public.user_settings FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_settings_update_own ON public.user_settings;
CREATE POLICY user_settings_update_own ON public.user_settings FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS oauth_tokens_select_own ON public.oauth_tokens;
CREATE POLICY oauth_tokens_select_own ON public.oauth_tokens FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS oauth_tokens_insert_own ON public.oauth_tokens;
CREATE POLICY oauth_tokens_insert_own ON public.oauth_tokens FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS oauth_tokens_update_own ON public.oauth_tokens;
CREATE POLICY oauth_tokens_update_own ON public.oauth_tokens FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS oauth_tokens_delete_own ON public.oauth_tokens;
CREATE POLICY oauth_tokens_delete_own ON public.oauth_tokens FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS gradescope_credentials_select_own ON public.gradescope_credentials;
CREATE POLICY gradescope_credentials_select_own ON public.gradescope_credentials FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS gradescope_credentials_insert_own ON public.gradescope_credentials;
CREATE POLICY gradescope_credentials_insert_own ON public.gradescope_credentials FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS gradescope_credentials_update_own ON public.gradescope_credentials;
CREATE POLICY gradescope_credentials_update_own ON public.gradescope_credentials FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS gradescope_credentials_delete_own ON public.gradescope_credentials;
CREATE POLICY gradescope_credentials_delete_own ON public.gradescope_credentials FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS enrollments_select_own ON public.enrollments;
CREATE POLICY enrollments_select_own ON public.enrollments FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS enrollments_insert_own ON public.enrollments;
CREATE POLICY enrollments_insert_own ON public.enrollments FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS enrollments_update_own ON public.enrollments;
CREATE POLICY enrollments_update_own ON public.enrollments FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS enrollments_delete_own ON public.enrollments;
CREATE POLICY enrollments_delete_own ON public.enrollments FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS notes_select_own ON public.notes;
CREATE POLICY notes_select_own ON public.notes FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS notes_insert_own ON public.notes;
CREATE POLICY notes_insert_own ON public.notes FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS notes_update_own ON public.notes;
CREATE POLICY notes_update_own ON public.notes FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS notes_delete_own ON public.notes;
CREATE POLICY notes_delete_own ON public.notes FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS flashcards_select_own ON public.flashcards;
CREATE POLICY flashcards_select_own ON public.flashcards FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS flashcards_insert_own ON public.flashcards;
CREATE POLICY flashcards_insert_own ON public.flashcards FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS flashcards_update_own ON public.flashcards;
CREATE POLICY flashcards_update_own ON public.flashcards FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS flashcards_delete_own ON public.flashcards;
CREATE POLICY flashcards_delete_own ON public.flashcards FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS sessions_select_own ON public.sessions;
CREATE POLICY sessions_select_own ON public.sessions FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS sessions_insert_own ON public.sessions;
CREATE POLICY sessions_insert_own ON public.sessions FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS sessions_update_own ON public.sessions;
CREATE POLICY sessions_update_own ON public.sessions FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS sessions_delete_own ON public.sessions;
CREATE POLICY sessions_delete_own ON public.sessions FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_attempts_select_own ON public.quiz_attempts;
CREATE POLICY quiz_attempts_select_own ON public.quiz_attempts FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_attempts_insert_own ON public.quiz_attempts;
CREATE POLICY quiz_attempts_insert_own ON public.quiz_attempts FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_attempts_update_own ON public.quiz_attempts;
CREATE POLICY quiz_attempts_update_own ON public.quiz_attempts FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_attempts_delete_own ON public.quiz_attempts;
CREATE POLICY quiz_attempts_delete_own ON public.quiz_attempts FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_context_select_own ON public.quiz_context;
CREATE POLICY quiz_context_select_own ON public.quiz_context FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_context_insert_own ON public.quiz_context;
CREATE POLICY quiz_context_insert_own ON public.quiz_context FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_context_update_own ON public.quiz_context;
CREATE POLICY quiz_context_update_own ON public.quiz_context FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS quiz_context_delete_own ON public.quiz_context;
CREATE POLICY quiz_context_delete_own ON public.quiz_context FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS study_guides_select_own ON public.study_guides;
CREATE POLICY study_guides_select_own ON public.study_guides FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS study_guides_insert_own ON public.study_guides;
CREATE POLICY study_guides_insert_own ON public.study_guides FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS study_guides_update_own ON public.study_guides;
CREATE POLICY study_guides_update_own ON public.study_guides FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS study_guides_delete_own ON public.study_guides;
CREATE POLICY study_guides_delete_own ON public.study_guides FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_nodes_select_own ON public.graph_nodes;
CREATE POLICY graph_nodes_select_own ON public.graph_nodes FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_nodes_insert_own ON public.graph_nodes;
CREATE POLICY graph_nodes_insert_own ON public.graph_nodes FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_nodes_update_own ON public.graph_nodes;
CREATE POLICY graph_nodes_update_own ON public.graph_nodes FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_nodes_delete_own ON public.graph_nodes;
CREATE POLICY graph_nodes_delete_own ON public.graph_nodes FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_edges_select_own ON public.graph_edges;
CREATE POLICY graph_edges_select_own ON public.graph_edges FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_edges_insert_own ON public.graph_edges;
CREATE POLICY graph_edges_insert_own ON public.graph_edges FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_edges_update_own ON public.graph_edges;
CREATE POLICY graph_edges_update_own ON public.graph_edges FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS graph_edges_delete_own ON public.graph_edges;
CREATE POLICY graph_edges_delete_own ON public.graph_edges FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS documents_select_own ON public.documents;
CREATE POLICY documents_select_own ON public.documents FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS documents_insert_own ON public.documents;
CREATE POLICY documents_insert_own ON public.documents FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS documents_update_own ON public.documents;
CREATE POLICY documents_update_own ON public.documents FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS documents_delete_own ON public.documents;
CREATE POLICY documents_delete_own ON public.documents FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS feedback_select_own ON public.feedback;
CREATE POLICY feedback_select_own ON public.feedback FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS feedback_insert_own ON public.feedback;
CREATE POLICY feedback_insert_own ON public.feedback FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS issue_reports_select_own ON public.issue_reports;
CREATE POLICY issue_reports_select_own ON public.issue_reports FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS issue_reports_insert_own ON public.issue_reports;
CREATE POLICY issue_reports_insert_own ON public.issue_reports FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_achievements_select_own ON public.user_achievements;
CREATE POLICY user_achievements_select_own ON public.user_achievements FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_achievements_update_own ON public.user_achievements;
CREATE POLICY user_achievements_update_own ON public.user_achievements FOR UPDATE TO authenticated
    USING (user_id = (SELECT app_auth.uid()))
    WITH CHECK (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_cosmetics_select_own ON public.user_cosmetics;
CREATE POLICY user_cosmetics_select_own ON public.user_cosmetics FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS user_roles_select_own ON public.user_roles;
CREATE POLICY user_roles_select_own ON public.user_roles FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS xp_events_select_own ON public.xp_events;
CREATE POLICY xp_events_select_own ON public.xp_events FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friend_requests_select_party ON public.friend_requests;
CREATE POLICY friend_requests_select_party ON public.friend_requests FOR SELECT TO authenticated
    USING (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friend_requests_insert_sender ON public.friend_requests;
CREATE POLICY friend_requests_insert_sender ON public.friend_requests FOR INSERT TO authenticated
    WITH CHECK (from_user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friend_requests_update_party ON public.friend_requests;
CREATE POLICY friend_requests_update_party ON public.friend_requests FOR UPDATE TO authenticated
    USING (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()))
    WITH CHECK (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friend_requests_delete_party ON public.friend_requests;
CREATE POLICY friend_requests_delete_party ON public.friend_requests FOR DELETE TO authenticated
    USING (from_user_id = (SELECT app_auth.uid()) OR to_user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friendships_select_party ON public.friendships;
CREATE POLICY friendships_select_party ON public.friendships FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR friend_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friendships_insert_party ON public.friendships;
CREATE POLICY friendships_insert_party ON public.friendships FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) OR friend_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS friendships_delete_party ON public.friendships;
CREATE POLICY friendships_delete_party ON public.friendships FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR friend_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS messages_select_own ON public.messages;
CREATE POLICY messages_select_own ON public.messages FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS messages_insert_own ON public.messages;
CREATE POLICY messages_insert_own ON public.messages FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS messages_update_own ON public.messages;
CREATE POLICY messages_update_own ON public.messages FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())))
    WITH CHECK (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS messages_delete_own ON public.messages;
CREATE POLICY messages_delete_own ON public.messages FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.sessions p WHERE p.id = messages.session_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS node_mastery_events_select_own ON public.node_mastery_events;
CREATE POLICY node_mastery_events_select_own ON public.node_mastery_events FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = node_mastery_events.node_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS node_mastery_events_insert_own ON public.node_mastery_events;
CREATE POLICY node_mastery_events_insert_own ON public.node_mastery_events FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = node_mastery_events.node_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS note_concepts_select_own ON public.note_concepts;
CREATE POLICY note_concepts_select_own ON public.note_concepts FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.notes p WHERE p.id = note_concepts.note_id AND p.user_id = (SELECT app_auth.uid())) AND EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = note_concepts.concept_node_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS note_concepts_insert_own ON public.note_concepts;
CREATE POLICY note_concepts_insert_own ON public.note_concepts FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.notes p WHERE p.id = note_concepts.note_id AND p.user_id = (SELECT app_auth.uid())) AND EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = note_concepts.concept_node_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS note_concepts_delete_own ON public.note_concepts;
CREATE POLICY note_concepts_delete_own ON public.note_concepts FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.notes p WHERE p.id = note_concepts.note_id AND p.user_id = (SELECT app_auth.uid())) AND EXISTS (SELECT 1 FROM public.graph_nodes p WHERE p.id = note_concepts.concept_node_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS quiz_responses_select_own ON public.quiz_responses;
CREATE POLICY quiz_responses_select_own ON public.quiz_responses FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS quiz_responses_insert_own ON public.quiz_responses;
CREATE POLICY quiz_responses_insert_own ON public.quiz_responses FOR INSERT TO authenticated
    WITH CHECK (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS quiz_responses_update_own ON public.quiz_responses;
CREATE POLICY quiz_responses_update_own ON public.quiz_responses FOR UPDATE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())))
    WITH CHECK (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS quiz_responses_delete_own ON public.quiz_responses;
CREATE POLICY quiz_responses_delete_own ON public.quiz_responses FOR DELETE TO authenticated
    USING (EXISTS (SELECT 1 FROM public.quiz_attempts p WHERE p.id = quiz_responses.attempt_id AND p.user_id = (SELECT app_auth.uid())));
DROP POLICY IF EXISTS gradebook_categories_select_own ON public.gradebook_categories;
CREATE POLICY gradebook_categories_select_own ON public.gradebook_categories FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
DROP POLICY IF EXISTS gradebook_categories_insert_own ON public.gradebook_categories;
CREATE POLICY gradebook_categories_insert_own ON public.gradebook_categories FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
DROP POLICY IF EXISTS gradebook_categories_update_own ON public.gradebook_categories;
CREATE POLICY gradebook_categories_update_own ON public.gradebook_categories FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
DROP POLICY IF EXISTS gradebook_categories_delete_own ON public.gradebook_categories;
CREATE POLICY gradebook_categories_delete_own ON public.gradebook_categories FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradebook_categories.enrollment_id)));
DROP POLICY IF EXISTS assignments_select_own ON public.assignments;
CREATE POLICY assignments_select_own ON public.assignments FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
DROP POLICY IF EXISTS assignments_insert_own ON public.assignments;
CREATE POLICY assignments_insert_own ON public.assignments FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
DROP POLICY IF EXISTS assignments_update_own ON public.assignments;
CREATE POLICY assignments_update_own ON public.assignments FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
DROP POLICY IF EXISTS assignments_delete_own ON public.assignments;
CREATE POLICY assignments_delete_own ON public.assignments FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(assignments.enrollment_id)));
DROP POLICY IF EXISTS gradescope_course_links_select_own ON public.gradescope_course_links;
CREATE POLICY gradescope_course_links_select_own ON public.gradescope_course_links FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
DROP POLICY IF EXISTS gradescope_course_links_insert_own ON public.gradescope_course_links;
CREATE POLICY gradescope_course_links_insert_own ON public.gradescope_course_links FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
DROP POLICY IF EXISTS gradescope_course_links_update_own ON public.gradescope_course_links;
CREATE POLICY gradescope_course_links_update_own ON public.gradescope_course_links FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
DROP POLICY IF EXISTS gradescope_course_links_delete_own ON public.gradescope_course_links;
CREATE POLICY gradescope_course_links_delete_own ON public.gradescope_course_links FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(gradescope_course_links.enrollment_id)));
DROP POLICY IF EXISTS topic_checklists_select_own ON public.topic_checklists;
CREATE POLICY topic_checklists_select_own ON public.topic_checklists FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
DROP POLICY IF EXISTS topic_checklists_insert_own ON public.topic_checklists;
CREATE POLICY topic_checklists_insert_own ON public.topic_checklists FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
DROP POLICY IF EXISTS topic_checklists_update_own ON public.topic_checklists;
CREATE POLICY topic_checklists_update_own ON public.topic_checklists FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
DROP POLICY IF EXISTS topic_checklists_delete_own ON public.topic_checklists;
CREATE POLICY topic_checklists_delete_own ON public.topic_checklists FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklists.enrollment_id)));
DROP POLICY IF EXISTS topic_checklist_progress_select_own ON public.topic_checklist_progress;
CREATE POLICY topic_checklist_progress_select_own ON public.topic_checklist_progress FOR SELECT TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
DROP POLICY IF EXISTS topic_checklist_progress_insert_own ON public.topic_checklist_progress;
CREATE POLICY topic_checklist_progress_insert_own ON public.topic_checklist_progress FOR INSERT TO authenticated
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
DROP POLICY IF EXISTS topic_checklist_progress_update_own ON public.topic_checklist_progress;
CREATE POLICY topic_checklist_progress_update_own ON public.topic_checklist_progress FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)))
    WITH CHECK ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
DROP POLICY IF EXISTS topic_checklist_progress_delete_own ON public.topic_checklist_progress;
CREATE POLICY topic_checklist_progress_delete_own ON public.topic_checklist_progress FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_enrollment(topic_checklist_progress.enrollment_id)));
DROP POLICY IF EXISTS rooms_select_visible ON public.rooms;
CREATE POLICY rooms_select_visible ON public.rooms FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL AND (is_public OR (SELECT app_auth.is_room_member(rooms.id))));
DROP POLICY IF EXISTS rooms_insert_owner ON public.rooms;
CREATE POLICY rooms_insert_owner ON public.rooms FOR INSERT TO authenticated
    WITH CHECK (owner_id = (SELECT app_auth.uid()) AND created_by = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS rooms_update_owner ON public.rooms;
CREATE POLICY rooms_update_owner ON public.rooms FOR UPDATE TO authenticated
    USING (owner_id = (SELECT app_auth.uid()))
    WITH CHECK (owner_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS room_members_select_comember ON public.room_members;
CREATE POLICY room_members_select_comember ON public.room_members FOR SELECT TO authenticated
    USING ((SELECT app_auth.is_room_member(room_members.room_id)));
DROP POLICY IF EXISTS room_members_insert_self ON public.room_members;
CREATE POLICY room_members_insert_self ON public.room_members FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) AND NOT EXISTS (SELECT 1 FROM public.room_bans b WHERE b.room_id = room_members.room_id AND b.user_id = (SELECT app_auth.uid())) AND ((SELECT app_auth.owns_room(room_members.room_id)) OR EXISTS (SELECT 1 FROM public.rooms r WHERE r.id = room_members.room_id AND r.is_public)));
DROP POLICY IF EXISTS room_members_delete_self_or_owner ON public.room_members;
CREATE POLICY room_members_delete_self_or_owner ON public.room_members FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR (SELECT app_auth.owns_room(room_members.room_id)));
DROP POLICY IF EXISTS room_bans_select_owner_or_self ON public.room_bans;
CREATE POLICY room_bans_select_owner_or_self ON public.room_bans FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()) OR (SELECT app_auth.owns_room(room_bans.room_id)));
DROP POLICY IF EXISTS room_bans_write_owner ON public.room_bans;
CREATE POLICY room_bans_write_owner ON public.room_bans FOR INSERT TO authenticated
    WITH CHECK (banned_by = (SELECT app_auth.uid()) AND (SELECT app_auth.owns_room(room_bans.room_id)));
DROP POLICY IF EXISTS room_bans_update_owner ON public.room_bans;
CREATE POLICY room_bans_update_owner ON public.room_bans FOR UPDATE TO authenticated
    USING ((SELECT app_auth.owns_room(room_bans.room_id)))
    WITH CHECK (banned_by = (SELECT app_auth.uid()) AND (SELECT app_auth.owns_room(room_bans.room_id)));
DROP POLICY IF EXISTS room_bans_delete_owner ON public.room_bans;
CREATE POLICY room_bans_delete_owner ON public.room_bans FOR DELETE TO authenticated
    USING ((SELECT app_auth.owns_room(room_bans.room_id)));
DROP POLICY IF EXISTS room_activity_select_member ON public.room_activity;
CREATE POLICY room_activity_select_member ON public.room_activity FOR SELECT TO authenticated
    USING ((SELECT app_auth.is_room_member(room_activity.room_id)));
DROP POLICY IF EXISTS room_activity_insert_member ON public.room_activity;
CREATE POLICY room_activity_insert_member ON public.room_activity FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) AND (SELECT app_auth.is_room_member(room_activity.room_id)));
DROP POLICY IF EXISTS room_summaries_select_member ON public.room_summaries;
CREATE POLICY room_summaries_select_member ON public.room_summaries FOR SELECT TO authenticated
    USING ((SELECT app_auth.is_room_member(room_summaries.room_id)));
DROP POLICY IF EXISTS room_reactions_select_member ON public.room_reactions;
CREATE POLICY room_reactions_select_member ON public.room_reactions FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.room_messages m WHERE m.id = room_reactions.message_id AND (SELECT app_auth.is_room_member(m.room_id))));
DROP POLICY IF EXISTS room_reactions_insert_self ON public.room_reactions;
CREATE POLICY room_reactions_insert_self ON public.room_reactions FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT app_auth.uid()) AND EXISTS (SELECT 1 FROM public.room_messages m WHERE m.id = room_reactions.message_id AND (SELECT app_auth.is_room_member(m.room_id))));
DROP POLICY IF EXISTS room_reactions_delete_self ON public.room_reactions;
CREATE POLICY room_reactions_delete_self ON public.room_reactions FOR DELETE TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS offering_concept_stats_select_enrolled ON public.offering_concept_stats;
CREATE POLICY offering_concept_stats_select_enrolled ON public.offering_concept_stats FOR SELECT TO authenticated
    USING ((SELECT app_auth.enrolled_in_offering(offering_concept_stats.offering_id)));
DROP POLICY IF EXISTS offering_summary_select_enrolled ON public.offering_summary;
CREATE POLICY offering_summary_select_enrolled ON public.offering_summary FOR SELECT TO authenticated
    USING ((SELECT app_auth.enrolled_in_offering(offering_summary.offering_id)));
DROP POLICY IF EXISTS course_chunks_select_readable ON public.course_chunks;
CREATE POLICY course_chunks_select_readable ON public.course_chunks FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL AND (visibility = 'shared' OR uploader_id = (SELECT app_auth.uid()) OR EXISTS (SELECT 1 FROM public.course_chunk_contributors k WHERE k.chunk_id = course_chunks.id AND k.user_id = (SELECT app_auth.uid()))));
DROP POLICY IF EXISTS course_chunk_contributors_select_own ON public.course_chunk_contributors;
CREATE POLICY course_chunk_contributors_select_own ON public.course_chunk_contributors FOR SELECT TO authenticated
    USING (user_id = (SELECT app_auth.uid()));
DROP POLICY IF EXISTS course_chunk_sources_select_readable ON public.course_chunk_sources;
CREATE POLICY course_chunk_sources_select_readable ON public.course_chunk_sources FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM public.course_chunks c WHERE c.id = course_chunk_sources.chunk_id));
DROP POLICY IF EXISTS schools_select_signed_in ON public.schools;
CREATE POLICY schools_select_signed_in ON public.schools FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS terms_select_signed_in ON public.terms;
CREATE POLICY terms_select_signed_in ON public.terms FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS courses_select_signed_in ON public.courses;
CREATE POLICY courses_select_signed_in ON public.courses FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS course_offerings_select_signed_in ON public.course_offerings;
CREATE POLICY course_offerings_select_signed_in ON public.course_offerings FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS achievements_select_signed_in ON public.achievements;
CREATE POLICY achievements_select_signed_in ON public.achievements FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS achievement_triggers_select_signed_in ON public.achievement_triggers;
CREATE POLICY achievement_triggers_select_signed_in ON public.achievement_triggers FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS achievement_cosmetics_select_signed_in ON public.achievement_cosmetics;
CREATE POLICY achievement_cosmetics_select_signed_in ON public.achievement_cosmetics FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS cosmetics_select_signed_in ON public.cosmetics;
CREATE POLICY cosmetics_select_signed_in ON public.cosmetics FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS roles_select_signed_in ON public.roles;
CREATE POLICY roles_select_signed_in ON public.roles FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS role_cosmetics_select_signed_in ON public.role_cosmetics;
CREATE POLICY role_cosmetics_select_signed_in ON public.role_cosmetics FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS growth_stages_select_signed_in ON public.growth_stages;
CREATE POLICY growth_stages_select_signed_in ON public.growth_stages FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
DROP POLICY IF EXISTS xp_rules_select_signed_in ON public.xp_rules;
CREATE POLICY xp_rules_select_signed_in ON public.xp_rules FOR SELECT TO authenticated
    USING ((SELECT app_auth.uid()) IS NOT NULL);
