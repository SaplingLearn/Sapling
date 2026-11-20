-- 20261120070405_learning_evidence_seeds.sql
-- Learning loop spec §13 A150 (#866 K03, owner decision 2026-11-19): a
-- concept with no learner_state row starts BKT from its stored map score
-- (graph_nodes.mastery_score above 0, clamped to BKT_P_MAX; a never-studied
-- concept, score 0, from the prior BKT_L0). This journals that starting score,
-- so the A123 void replay (learning/evidence_replay.py) starts every node from
-- exactly the belief the original write did, instead of the prior.
--
-- (1) node_mastery_events.seeds jsonb: {node id: stored score} for each node
--     the row is the first to reach while it had no learner_state row (its own
--     concept, or a node its one-hop propagation moved). NULL on every other
--     row (no default; adding the column rewrites nothing), so an operation
--     that starts no node plans and fingerprints exactly as before. The CHECK
--     is NOT VALID: every existing row is NULL (the 20261108072715 choice).
-- (2) learning_evidence_commit is re-created as 20261108205812's definition
--     with three edits, verbatim otherwise: 'seeds' in the event key
--     whitelist; its check (an object, or absent/null, whose keys are plan
--     nodes with a state row in the plan and NO learner_state row yet, and
--     whose values are JSON numbers in [0, 1]); its insert column and value.
-- (3) learning_evidence_void_snapshot is re-created as 20261108072715's
--     definition with one edit: each journal row carries its `seeds`. A CREATE
--     OR REPLACE replaces every SET clause, so it carries 20261108115720's
--     extra_float_digits = 3 itself (exact floats in the snapshot the void
--     replays from).
-- The registry in backend/tests/test_learning_migration_functions.py pins
-- that both definitions keep every earlier change.
--
-- Deploy order: apply before the code (the writer names the key, and the
-- old commit function refuses it). Older code never names it.
--
-- Locks: one transaction (db/migrate.py); the ALTER takes ACCESS EXCLUSIVE on
-- node_mastery_events for a catalog-only change, bounded by lock_timeout 5s
-- (rolled back, nothing recorded, when the lock does not come: run it again)
-- so it never queues every learning_evidence_commit (lock_timeout 2s) behind
-- it. Idempotent: ADD COLUMN IF NOT EXISTS, a guarded constraint, CREATE OR
-- REPLACE, and grants that are re-applied as they stand. node_mastery_events
-- keeps its RLS posture (20261109032302) and its place in the account wipe,
-- bundle and purge (a column, not a table).

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.node_mastery_events ADD COLUMN IF NOT EXISTS seeds jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.node_mastery_events'::regclass
       AND conname = 'node_mastery_events_seeds_check'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_seeds_check
      CHECK (seeds IS NULL OR jsonb_typeof(seeds) = 'object') NOT VALID;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
    item record; retired_items jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    -- §13 A123: a check item staff retired takes no new evidence. A SHARED lock
    -- per graded item (sorted), against check_item_review_decide's EXCLUSIVE one:
    -- a retire decided while this grade was in flight waits for its commit (and
    -- the void sweep then finds the row); a grade arriving after it is refused.
    FOR item IN
        SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
          FROM jsonb_array_elements(p_plan->'events') e
          JOIN graph_nodes g ON g.id = e.value->>'node_id'
         WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
           AND jsonb_typeof(e.value->'question_hash') = 'string'
           AND g.course_id IS NOT NULL
         ORDER BY 1, 2
    LOOP
        PERFORM pg_advisory_xact_lock_shared(
            hashtextextended('check-item-review:'||item.course_id||':'||item.question_hash,0));
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',q.course_id,'question_hash',q.question_hash)
               ORDER BY q.course_id,q.question_hash),'[]') INTO retired_items
      FROM (SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
              FROM jsonb_array_elements(p_plan->'events') e
              JOIN graph_nodes g ON g.id = e.value->>'node_id'
             WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
               AND jsonb_typeof(e.value->'question_hash') = 'string'
               AND g.course_id IS NOT NULL) q
     WHERE EXISTS(SELECT 1 FROM check_item_reviews cr WHERE cr.course_id=q.course_id
                  AND cr.question_hash=q.question_hash AND cr.status='retired');
    IF jsonb_array_length(retired_items) > 0 THEN
        RETURN jsonb_build_object('status','retired','items',retired_items);
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           -- §13 A123: the replay inputs, when present, are well formed
           OR (x ? 'retention' AND jsonb_typeof(x->'retention') NOT IN ('number','null'))
           OR (ev.retention IS NOT NULL AND NOT (ev.retention > 0 AND ev.retention <= 1))
           OR (x ? 'same_session_recheck' AND jsonb_typeof(x->'same_session_recheck') NOT IN ('boolean','null'))
           OR (x ? 'propagated_to' AND jsonb_typeof(x->'propagated_to') NOT IN ('array','null'))
           OR (jsonb_typeof(x->'propagated_to') = 'array' AND EXISTS(
                SELECT 1 FROM jsonb_array_elements(x->'propagated_to') t
                 WHERE jsonb_typeof(t) IS DISTINCT FROM 'string' OR NOT ((t #>> '{}')=ANY(ids))
                    OR (t #>> '{}')=ev.node_id
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=(t #>> '{}'))))
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation',
                'retention','same_session_recheck','propagated_to',
                'student_confidence',
                'seeds',
                'multi_concept'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1)
           -- spec §13 A141: a multi-concept item's row says so: a JSON boolean, or absent/null
           OR (x ? 'multi_concept' AND jsonb_typeof(x->'multi_concept') NOT IN ('boolean','null'))
           -- spec §13 A150: the starting scores, when present: an object naming
           -- plan nodes that start now (no learner_state row) and each one's
           -- score, a JSON number in [0, 1]
           OR (x ? 'seeds' AND jsonb_typeof(x->'seeds') NOT IN ('object','null'))
           OR (jsonb_typeof(x->'seeds') = 'object' AND EXISTS(
                SELECT 1 FROM jsonb_each(x->'seeds') t
                 WHERE NOT (t.key=ANY(ids))
                    OR CASE WHEN jsonb_typeof(t.value) = 'number'
                            THEN NOT ((t.value #>> '{}')::double precision BETWEEN 0 AND 1)
                            ELSE true END
                    OR EXISTS(SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id AND l.node_id=t.key)
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=t.key))) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation,
            retention,same_session_recheck,propagated_to,
            multi_concept,
            seeds,
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to,
            ev.multi_concept,
            ev.seeds,
            ev.student_confidence);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_void_snapshot(
    p_user_id text,p_course_id text,p_question_hash text
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' SET extra_float_digits=3 AS $$
DECLARE ns jsonb; ss jsonb; es jsonb; js jsonb; rs jsonb; ms jsonb; retired boolean;
BEGIN
    IF coalesce(p_user_id,'')='' OR coalesce(p_course_id,'')='' OR coalesce(p_question_hash,'')='' THEN
        RAISE EXCEPTION 'Invalid evidence void snapshot identity';
    END IF;
    retired := EXISTS(SELECT 1 FROM check_item_reviews WHERE course_id=p_course_id
                      AND question_hash=p_question_hash AND status='retired');
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',n.id,'concept_name',n.concept_name,
        'mastery_score',n.mastery_score,'mastery_tier',n.mastery_tier,
        'evidence_version',n.evidence_version) ORDER BY n.id),'[]') INTO ns
      FROM graph_nodes n WHERE n.user_id=p_user_id AND n.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.node_id),'[]') INTO ss
      FROM learner_state s JOIN graph_nodes n ON n.id=s.node_id
     WHERE s.user_id=p_user_id AND n.user_id=p_user_id AND n.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
     WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
       AND a.user_id=p_user_id AND b.user_id=p_user_id
       AND a.course_id=p_course_id AND b.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',e.id,'node_id',e.node_id,'created_at',e.created_at,
        'evidence_seq',e.evidence_seq,'channel',e.channel,'correct',e.correct,'weight',e.weight,
        'assisted',e.assisted,'max_rung',e.max_rung,'reason',e.reason,'confidence',e.confidence,
        'session_id',e.session_id,'question_hash',e.question_hash,'check_item_id',e.check_item_id,
        'planning_recheck',e.planning_observation->'same_session_recheck',
        'same_session_recheck',e.same_session_recheck,'retention',e.retention,
        'propagated_to',e.propagated_to,'seeds',e.seeds,'void',(v.event_id IS NOT NULL))
        ORDER BY e.created_at,e.evidence_seq NULLS LAST,e.id),'[]') INTO js
      FROM node_mastery_events e JOIN graph_nodes n ON n.id=e.node_id
      LEFT JOIN learning_evidence_voids v ON v.event_id=e.id
     WHERE n.user_id=p_user_id AND n.course_id=p_course_id AND e.event_type='evidence';
    SELECT coalesce(jsonb_agg(r.question_hash ORDER BY r.question_hash),'[]') INTO rs
      FROM check_item_reviews r WHERE r.course_id=p_course_id AND r.status='retired';
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',m.id,'node_id',m.node_id,'count',m.count,
        'check_item_id',m.check_item_id,'attempts',(
            SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',a.course_id,
                'question_hash',a.question_hash,'check_item_id',a.check_item_id) ORDER BY a.id),'[]')
              FROM misconception_attempts a WHERE a.misconception_id=m.id)) ORDER BY m.id),'[]') INTO ms
      FROM misconceptions m JOIN graph_nodes n ON n.id=m.node_id
     WHERE m.user_id=p_user_id AND n.user_id=p_user_id AND n.course_id=p_course_id
       AND m.resolved_at IS NULL;
    RETURN jsonb_build_object('status','snapshot','retired',retired,'nodes',ns,'states',ss,
        'edges',es,'journal',js,'retired_hashes',rs,'misconceptions',ms);
END $$;

REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_void_snapshot(text,text,text) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_void_snapshot(text,text,text) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
        GRANT EXECUTE ON FUNCTION learning_evidence_void_snapshot(text,text,text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions and columns from its schema cache; the local
-- stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
