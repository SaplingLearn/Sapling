-- 20261108103333_learning_evidence_commit_reconcile.sql
-- Learning loop spec §13 A123 × A127: the one definition of
-- learning_evidence_commit that carries BOTH branches' changes.
--
-- Two wave-2 migrations re-create this function, each from a different base:
--   * 20261108072715_learning_evidence_void.sql (A123) takes a SHARED advisory
--     lock on every check item a batch grades (key check-item-review:<course>:<hash>,
--     the key check_item_review_decide holds EXCLUSIVELY), refuses a batch that
--     grades an item staff retired (status 'retired', nothing written), and
--     admits and journals the replay inputs `retention`, `same_session_recheck`
--     and `propagated_to`;
--   * 20261108092032_learning_student_confidence.sql (A127) was written on the
--     pre-A123 body (20261019141950) and admits and journals `student_confidence`.
-- Migrations apply in filename order, so A127's CREATE OR REPLACE ran last and
-- dropped all of A123's changes: no item lock, no retired refusal, and every
-- evidence row that journals A123's replay keys refused as invalid.
--
-- This migration re-creates the function as A123's definition with A127's
-- three edits, verbatim: `student_confidence` in the key whitelist, its type
-- and range check, and its insert column and value. Neither earlier migration
-- is edited (both are kept byte-identical to their branches). No wave-2
-- migration had been applied anywhere when this was written; apply it in the
-- same run as the two above, before the code (rollout:
-- docs/operations/learning-engineering-readiness.md). The registry in
-- backend/tests/test_learning_migration_functions.py pins that the last
-- definition keeps every change an earlier migration made.

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
                'student_confidence'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1) THEN
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
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to,
            ev.student_confidence);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; the local stack does not
-- reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
