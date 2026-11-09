\set QUIET 1
\pset footer off
\echo '== coverage: granted command with no matching policy (expect 0 rows)'
SELECT t.relname, p.priv
  FROM pg_class t CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p(priv)
 WHERE t.relnamespace='public'::regnamespace AND t.relkind='r'
   AND has_table_privilege('authenticated', t.oid, p.priv)
   AND NOT EXISTS (SELECT 1 FROM pg_policy po WHERE po.polrelid=t.oid
        AND (po.polcmd='*' OR po.polcmd = CASE p.priv WHEN 'SELECT' THEN 'r' WHEN 'INSERT' THEN 'a' WHEN 'UPDATE' THEN 'w' ELSE 'd' END));
\echo '== tables with policies but RLS off (expect only room_messages if any)'
SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r' AND NOT relrowsecurity;
\echo '== policies referencing auth.uid (expect 0)'
SELECT polrelid::regclass, polname FROM pg_policy WHERE coalesce(pg_get_expr(polqual, polrelid),'') ~ '(^|[^_])auth\.uid' OR coalesce(pg_get_expr(polwithcheck, polrelid),'') ~ '(^|[^_])auth\.uid';
\echo '== bucket counts by authenticated privilege'
SELECT CASE WHEN has_table_privilege('authenticated',c.oid,'INSERT') OR has_table_privilege('authenticated',c.oid,'UPDATE') OR has_table_privilege('authenticated',c.oid,'DELETE') THEN 'read+write'
            WHEN has_table_privilege('authenticated',c.oid,'SELECT') THEN 'read-only'
            ELSE 'no access (service-only or room_messages)' END k, count(*), string_agg(relname, ' ' ORDER BY relname) FILTER (WHERE NOT has_table_privilege('authenticated',c.oid,'SELECT')) none_list
  FROM pg_class c WHERE relnamespace='public'::regnamespace AND relkind='r' GROUP BY 1;
BEGIN;
INSERT INTO schools(id,name,slug) VALUES ('s1','S','s');
INSERT INTO courses(id,school_id,course_code,course_name) VALUES ('c1','s1','CS101','Intro');
INSERT INTO course_offerings(id,course_id,term_id) VALUES ('o1','c1',(SELECT id FROM terms LIMIT 1));
INSERT INTO users(id,email) VALUES ('user_A','a@x'),('user_B','b@x');
INSERT INTO enrollments(id,user_id,offering_id) VALUES ('eA','user_A','o1'),('eB','user_B','o1');
INSERT INTO notes(id,user_id,offering_id,title,body) VALUES ('nA','user_A','o1','t','b');
INSERT INTO gradebook_categories(id,enrollment_id,name,weight) VALUES ('gA','eA','HW',1);
INSERT INTO sessions(id,user_id,mode,topic) VALUES ('sA','user_A','socratic','t');
INSERT INTO messages(id,session_id,role,content) VALUES ('mA','sA','user','hi');
INSERT INTO rooms(id,name,invite_code,created_by,owner_id,is_public) VALUES ('rPriv','p','X1','user_A','user_A',false),('rPub','q','X2','user_A','user_A',true);
INSERT INTO room_members(room_id,user_id) VALUES ('rPriv','user_A'),('rPub','user_A');
INSERT INTO offering_concept_stats(id,offering_id,concept_name) VALUES ('ocs','o1','limits');
INSERT INTO course_chunks(id,course_id,chunk_text,visibility,uploader_id,category) VALUES ('ccPriv','c1','x','private','user_A','lecture'),('ccShared','c1','y','shared','user_A','lecture');
SET LOCAL ROLE authenticated;
SELECT set_config('request.jwt.claims','{"iss":"sapling-api","sub":"user_B","role":"authenticated"}',true) \g /dev/null
\echo '== as user_B (sapling-api token): rows of A visible (expect notes 0, gradebook 0, messages 0, rooms 1 public, members 0, stats 1 same offering, chunks 1 shared, courses 1)'
SELECT (SELECT count(*) FROM notes) notes, (SELECT count(*) FROM gradebook_categories) gb, (SELECT count(*) FROM messages) msgs, (SELECT count(*) FROM rooms) rooms, (SELECT count(*) FROM room_members) members, (SELECT count(*) FROM offering_concept_stats) stats, (SELECT count(*) FROM course_chunks) chunks, (SELECT count(*) FROM courses) courses;
\echo '== B joins A private room directly (expect RLS violation)'
SAVEPOINT a; INSERT INTO room_members(room_id,user_id) VALUES ('rPriv','user_B'); ROLLBACK TO SAVEPOINT a;
\echo '== B joins public room (expect ok)'
SAVEPOINT b; INSERT INTO room_members(room_id,user_id) VALUES ('rPub','user_B'); SELECT count(*) AS members_visible_after_join FROM room_members; ROLLBACK TO SAVEPOINT b;
\echo '== B adds category to A enrollment (expect RLS violation)'
SAVEPOINT c; INSERT INTO gradebook_categories(id,enrollment_id,name,weight) VALUES ('gX','eA','x',1); ROLLBACK TO SAVEPOINT c;
\echo '== B updates documents.index_status (expect permission denied: column grant)'
SAVEPOINT d; UPDATE documents SET index_status='indexed' WHERE user_id='user_B'; ROLLBACK TO SAVEPOINT d;
SELECT set_config('request.jwt.claims','{"iss":"https://ref.supabase.co/auth/v1","sub":"00000000-0000-0000-0000-000000000001","role":"authenticated"}',true) \g /dev/null
\echo '== GoTrue-style authenticated token (expect all 0)'
SELECT (SELECT count(*) FROM courses) courses, (SELECT count(*) FROM rooms) rooms, (SELECT count(*) FROM course_chunks) chunks;
ROLLBACK;
