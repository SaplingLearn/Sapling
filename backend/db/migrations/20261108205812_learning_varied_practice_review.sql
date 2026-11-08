-- 20261108205812_learning_varied_practice_review.sql
-- Learning loop spec §13 A141, the review's fixes to 20261108185101. Two
-- changes; every row and every evidence plan the code writes with
-- multi_concept_items off is exactly as before.
--
-- (1) check_items_multi_concept_shape, closed. The constraint 20261108185101
--     added let through a row the code never writes: array_to_string skips
--     NULL elements, so apex_key 'a', component_keys '{a,NULL}' and
--     concept_key 'a' passed, and a per-concept read (concept_key=eq.a) would
--     have met that row. Distinct, non-empty components and a component free
--     of the separator were unenforced too. The replacement keeps the
--     single-concept branch (no apex, no components, no separator) and
--     requires on the multi-concept branch: a one-dimensional array indexed
--     from 1 holding 2 or 3 components, none NULL or empty, all distinct, the
--     first the apex; a concept_key that holds the separator (chr(31)), is
--     exactly the components joined by it, and holds one separator per join
--     (so no component holds one). A CHECK passes on NULL, so the whole
--     expression is COALESCE(..., false): any NULL it meets fails the row.
--     Every stored row passes it (learning/multi_concept.combo_key writes
--     nothing else; a concept's own row is the unchanged first branch).
--
-- (2) node_mastery_events.multi_concept: the evidence journal says which rows
--     a multi-concept item graded (spec §13 A141 (e), (f)). The item's
--     check_items row cannot say it for good: an A23 consent withdrawal or a
--     staff retire deletes it, and the item statistics (learning/item_stats.py)
--     must still keep its answers out of the apex's own items' rest scores and
--     its voids out of their change times. NULL on every other row (no
--     default; adding the column rewrites nothing).
--     learning_evidence_commit is re-created as 20261108103333's definition
--     with three edits, verbatim otherwise: 'multi_concept' in the event key
--     whitelist, its type check (a JSON boolean or null), and its insert
--     column and value. The writer (services/graph_service.py) names the key
--     only on a multi-concept row, so every other row, plan and operation is
--     exactly as before. The registry in
--     backend/tests/test_learning_migration_functions.py pins that this
--     definition keeps every earlier change.
--
-- Deploy order: apply before the code. The item statistics read
-- (routes/admin_check_items.py) selects the new column; nothing else needs
-- it while multi_concept_items is off, and older code never names it.
--
-- Locks (amended before any apply, the second review; sanctioned in
-- tests/test_learning_loop_invariants.py::_AMENDED_BEFORE_ANY_APPLY). This
-- file runs in one transaction (db/migrate.py), and every lock it takes is
-- ACCESS EXCLUSIVE and held to its commit: check_items for the constraint,
-- node_mastery_events for the column. Two rules keep that brief:
--   * lock_timeout 5s: a lock that does not come within 5s fails the file
--     (rolled back, nothing recorded; run it again), instead of queueing
--     every learning_evidence_commit (its own lock_timeout is 2s) behind a
--     waiting ALTER until a long reader finishes;
--   * the CHECK is added NOT VALID, so nothing scans check_items under the
--     lock (new and updated rows are checked at once).
--     20261108224511_learning_varied_practice_validate.sql validates it in its
--     own transaction, under SHARE UPDATE EXCLUSIVE, which blocks no read or
--     write.

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.check_items DROP CONSTRAINT IF EXISTS check_items_multi_concept_shape;
ALTER TABLE public.check_items ADD CONSTRAINT check_items_multi_concept_shape
    CHECK (COALESCE(
        (apex_key IS NULL AND component_keys IS NULL AND strpos(concept_key, chr(31)) = 0)
        OR (
            apex_key IS NOT NULL
            AND component_keys IS NOT NULL
            AND array_ndims(component_keys) = 1
            AND array_lower(component_keys, 1) = 1
            AND cardinality(component_keys) BETWEEN 2 AND 3
            AND array_position(component_keys, NULL) IS NULL
            AND array_position(component_keys, '') IS NULL
            AND component_keys[1] = apex_key
            AND component_keys[1] <> component_keys[2]
            AND (
                cardinality(component_keys) = 2
                OR (component_keys[3] <> component_keys[1] AND component_keys[3] <> component_keys[2])
            )
            AND strpos(concept_key, chr(31)) > 0
            AND concept_key = array_to_string(component_keys, chr(31))
            AND length(concept_key) - length(replace(concept_key, chr(31), ''))
                = cardinality(component_keys) - 1
        ),
        false
    )) NOT VALID;

ALTER TABLE public.node_mastery_events ADD COLUMN IF NOT EXISTS multi_concept boolean;

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
                'multi_concept'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1)
           -- spec §13 A141: a multi-concept item's row says so: a JSON boolean, or absent/null
           OR (x ? 'multi_concept' AND jsonb_typeof(x->'multi_concept') NOT IN ('boolean','null')) THEN
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
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to,
            ev.multi_concept,
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

-- PostgREST resolves functions and columns from its schema cache; the local
-- stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
