-- 0044: bring in the 30 badges from the Achievements.dc.html design as the
-- live catalog, and demote the 10 pre-existing seeds to drafts.
--
-- Deliberately non-destructive: the old rows keep their slugs, triggers and
-- earned rows, so nobody loses a badge. Concepts overlap across the two sets
-- (Week Warrior/draft and On Fire/live are both a 7-day streak) — harmless,
-- because drafts are never served to users. Reconciling them is an editorial
-- job for the admin wiki, not a migration.
UPDATE achievements
   SET status = 'draft'
 WHERE slug IN (
   'first_login','streak_7','streak_30','documents_5','documents_25',
   'quizzes_10','flashcards_50','rooms_joined_10','post_count_50','early_adopter'
 );

INSERT INTO achievements (slug, name, description, category, rarity, is_secret, xp_reward, sort_order, status) VALUES
  ('first-steps','First Steps','Complete your first study session, the moment an idea takes root.','activity','common',false,20,0,'live'),
  ('flash','Quick Draw','Review 100 flashcards. Recall gets sharper every pass.','activity','common',false,30,1,'live'),
  ('early-bird','Early Bird','Finish a study session before 7am.','activity','uncommon',false,60,2,'live'),
  ('night-owl','Night Owl','Wrap a study session after midnight.','activity','uncommon',false,60,3,'live'),
  ('on-fire','On Fire','Reach a 7-day study streak.','activity','rare',false,120,4,'live'),
  ('deep-focus','Deep Focus','Study for two straight hours in a single session.','activity','rare',false,120,5,'live'),
  ('quiz-master','Quiz Master','Complete 100 adaptive quizzes.','activity','epic',false,250,6,'live'),
  ('marathon','Evergreen','Hold a 30-day study streak. Growth that never drops its leaves.','activity','epic',false,300,7,'live'),
  ('wildfire','Wildfire','Keep a 60-day streak alive, a blaze that spreads across the calendar.','activity','legendary',false,400,8,'live'),
  ('first-friend','First Sprout','Add your first friend. Learning grows in company.','social','common',false,20,9,'live'),
  ('study-circle','Study Circle','Join your first study room.','social','uncommon',false,60,10,'live'),
  ('helping-hand','Helping Hand','Answer a roommate''s question in a study room.','social','uncommon',false,70,11,'live'),
  ('room-leader','Grovekeeper','Create a study room that five people join.','social','rare',false,150,12,'live'),
  ('popular','Well-Connected','Grow your friends list to ten.','social','rare',false,150,13,'live'),
  ('social-butterfly','Cross-Pollinator','Stay active across five different study rooms.','social','epic',false,250,14,'live'),
  ('mentor','Mentor','Finish first on a study room''s weekly leaderboard.','social','epic',false,280,15,'live'),
  ('sprout','Sprouted','Reach the Sprout growth stage.','milestone','common',false,25,16,'live'),
  ('rooted','Rooted','Master ten concepts across your courses.','milestone','uncommon',false,80,17,'live'),
  ('grade-a','Top Marks','Finish a course with an A in your gradebook.','milestone','uncommon',false,100,18,'live'),
  ('branching','Branching Out','Master fifty concepts.','milestone','rare',false,180,19,'live'),
  ('rings','Seasoned','Reach Level 15.','milestone','rare',false,180,20,'live'),
  ('canopy','Canopy','Master one hundred concepts.','milestone','epic',false,280,21,'live'),
  ('web','Knowledge Web','Grow your knowledge graph to two hundred nodes.','milestone','epic',false,300,22,'live'),
  ('old-growth','Old Growth','Reach the final growth stage. A canopy years in the making.','milestone','legendary',false,500,23,'live'),
  ('golden-hour','Golden Hour','Earn 500 XP in a single day.','special','rare',false,150,24,'live'),
  ('comeback','Second Wind','Rebuild a streak to seven days after a lapse.','special','rare',false,150,25,'live'),
  ('perfect-week','Perfect Week','Hit your daily XP goal seven days in a row.','special','epic',false,200,26,'live'),
  ('secret','???','A hidden achievement. Keep exploring to discover it.','special','epic',true,250,27,'live'),
  ('methuselah','Methuselah','Named for the bristlecone pine in Inyo National Forest, California, roughly 4,800 years old and still growing. Awarded to founding members from Sapling''s earliest days.','special','legendary',false,300,28,'live'),
  ('polymath','Polymath','Master concepts across five different courses.','special','legendary',false,500,29,'live')
ON CONFLICT (slug) DO UPDATE SET
  name        = EXCLUDED.name,
  description = EXCLUDED.description,
  category    = EXCLUDED.category,
  rarity      = EXCLUDED.rarity,
  is_secret   = EXCLUDED.is_secret,
  xp_reward   = EXCLUDED.xp_reward,
  sort_order  = EXCLUDED.sort_order,
  status      = EXCLUDED.status;

-- Rebuild triggers for the LIVE catalog only. Scoped by join rather than a bare
-- DELETE so the drafts keep the triggers they already had — publishing one from
-- the wiki should not silently produce a badge nothing can award.
DELETE FROM achievement_triggers t
 USING achievements a
 WHERE t.achievement_id = a.id AND a.status = 'live';

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT a.id, t.trigger_type, t.trigger_threshold
  FROM achievements a
  JOIN (VALUES
    ('first-steps','session_count',1),
    ('flash','flashcards_reviewed',100),
    ('early-bird','session_before_hour',7),
    ('night-owl','session_after_midnight',1),
    ('on-fire','login_streak',7),
    ('deep-focus','session_minutes',120),
    ('quiz-master','quizzes_completed',100),
    ('marathon','login_streak',30),
    ('wildfire','login_streak',60),
    ('first-friend','friends_count',1),
    ('study-circle','rooms_joined',1),
    ('helping-hand','room_replies',1),
    ('room-leader','owned_room_members',5),
    ('popular','friends_count',10),
    ('social-butterfly','rooms_active',5),
    ('mentor','manual_admin_grant',1),
    ('sprout','level',15),
    ('rooted','concepts_mastered',10),
    ('grade-a','course_grade_a',1),
    ('branching','concepts_mastered',50),
    ('rings','level',15),
    ('canopy','concepts_mastered',100),
    ('web','graph_nodes_count',200),
    ('old-growth','level',50),
    ('golden-hour','xp_in_day',500),
    ('comeback','manual_admin_grant',1),
    ('perfect-week','goal_streak',7),
    ('secret','manual_admin_grant',1),
    ('methuselah','manual_admin_grant',1),
    ('polymath','courses_with_mastery',5)
  ) AS t(slug, trigger_type, trigger_threshold)
    ON t.slug = a.slug;
