-- 20261125074254_checklist_budget_function_usage.sql
-- The checklist budget's "unknown price" guard read the SAPLING_MODEL_MODE=
-- function seam's usage rows as unpriced bills. checklist_budget_admit and
-- checklist_budget_start refuse ('usage_unavailable') while the student has any
-- llm_usage row this UTC month with cost_usd NULL, so that an unpriced REAL
-- model can never be read as free headroom. But every function-mode agent run
-- records its row as model 'function:<task>', provider 'function', cost NULL
-- (services/llm_pricing.py::cost_usd: "a deliberate free stand-in, not an
-- unpriced real model"). So on the E2E/explore stacks one quiz or tutor turn
-- made every later learning-loop checklist refresh of that student answer 503
-- for the rest of the month, while the checklist run itself is the seam's
-- non-billable path (services/checklist_budget_run.py) and never bills.
--
-- Re-create the two functions with that one condition narrowed: a NULL cost
-- on a function-seam row (provider 'function' AND model 'function:%', the
-- pair llm_pricing.usage_provider writes for that seam only) is not an unknown
-- price. A NULL cost on any other row, a negative or non-finite cost and a
-- missing or negative token count still refuse. NOTHING else changed (bodies
-- copied from 20261118194745 for admit, 20261108033310 for start). CREATE OR
-- REPLACE keeps their signatures and grants (service_role only). No real-mode
-- environment ever writes a function-seam row, so production is unchanged.

CREATE OR REPLACE FUNCTION checklist_budget_admit(
    p_user_id text, p_enrollment_id text, p_input_hash text,
    p_operation_id uuid, p_receipt_id text, p_policy text,
    p_daily_usd numeric, p_monthly_usd numeric, p_daily_tokens bigint,
    p_held_usd numeric, p_held_tokens bigint, p_models text[]
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    a checklist_budget_accounts%ROWTYPE;
    r checklist_budget_reservations%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    day_spend numeric; month_spend numeric; tokens bigint;
    day_holds numeric; month_holds numeric; token_holds bigint;
BEGIN
    IF p_user_id IS NULL OR length(p_user_id) NOT BETWEEN 1 AND 255
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_operation_id IS NULL
       OR p_receipt_id IS NULL OR p_policy IS DISTINCT FROM 'checklist-50k-3x8192-v2'
       OR p_input_hash IS NULL OR p_daily_usd IS NULL OR p_daily_usd <= 0
       OR p_monthly_usd IS NULL OR p_monthly_usd <= 0 OR p_daily_tokens IS NULL OR p_daily_tokens <= 0
       OR p_daily_usd::text IN ('NaN','Infinity','-Infinity') OR p_monthly_usd::text IN ('NaN','Infinity','-Infinity')
       OR p_held_usd IS NULL OR p_held_usd::text IN ('NaN','Infinity','-Infinity') OR p_held_usd <= 0
       OR round(p_held_usd, 10) <> p_held_usd OR p_held_tokens IS NULL OR p_held_tokens <= 0
       OR p_models IS NULL OR cardinality(p_models) = 0 OR array_position(p_models, NULL) IS NOT NULL
       OR EXISTS (SELECT 1 FROM unnest(p_models) AS label WHERE label !~ '^[a-z]+:[A-Za-z0-9._-]+$') THEN
        RAISE EXCEPTION 'Invalid checklist admission identity/policy';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=p_enrollment_id AND e.user_id=p_user_id) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    INSERT INTO checklist_budget_accounts(user_id) VALUES(p_user_id) ON CONFLICT DO NOTHING;
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    -- Workers may only tighten stored policy. A stale/looser worker cannot
    -- undo a lower cap; changing it upward requires an explicit DB policy edit.
    UPDATE checklist_budget_accounts SET daily_usd=least(daily_usd,p_daily_usd),
        monthly_usd=least(monthly_usd,p_monthly_usd),daily_tokens=least(daily_tokens,p_daily_tokens)
        WHERE user_id=p_user_id RETURNING * INTO a;
    -- Prepared leases may be released: start is a fenced compare-and-swap under
    -- this same mutex, so an expired prepared operation can never dispatch later.
    UPDATE checklist_budget_reservations SET state='released', reason='prepared_expired'
        WHERE user_id=p_user_id AND state='prepared' AND expires_at <= t;
    -- A started timeout is exposure, never a refund. It ceases to own the cache
    -- claim so a deliberate later refresh may reserve additional capacity.
    UPDATE checklist_budget_reservations SET state='unknown', reason='dispatch_outcome_unknown'
        WHERE user_id=p_user_id AND state='started' AND expires_at <= t;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.enrollment_id IS DISTINCT FROM p_enrollment_id
           OR r.input_hash IS DISTINCT FROM p_input_hash OR r.receipt_id IS DISTINCT FROM p_receipt_id
           OR r.held_usd IS DISTINCT FROM p_held_usd OR r.held_tokens IS DISTINCT FROM p_held_tokens
           OR r.models IS DISTINCT FROM p_models THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','reservation',to_jsonb(r));
    END IF;
    IF EXISTS (SELECT 1 FROM topic_checklists WHERE enrollment_id=p_enrollment_id AND input_hash=p_input_hash) THEN
        RETURN jsonb_build_object('status','cached');
    END IF;
    SELECT * INTO r FROM checklist_budget_reservations
        WHERE enrollment_id=p_enrollment_id AND state IN ('prepared','started');
    IF FOUND THEN RETURN jsonb_build_object('status','busy','reservation',to_jsonb(r)); END IF;
    IF a.blocked THEN RETURN jsonb_build_object('status','blocked'); END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    -- Unknown legacy prices/negative or malformed counters cannot establish
    -- remaining headroom. No coalesce(NULL cost,0) financial fallback.
    -- A function-seam row's NULL cost is a free stand-in, not an unknown price.
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at >= m
               AND ((cost_usd IS NULL AND (provider IS DISTINCT FROM 'function'
                                         OR model IS NULL OR model NOT LIKE 'function:%'))
                    OR cost_usd < 0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens < 0)) THEN
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at >= d),0), coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at >= d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO day_spend, month_spend, tokens FROM llm_usage WHERE user_id=p_user_id AND created_at >= m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0)
        INTO day_holds,month_holds,token_holds FROM checklist_budget_reservations
        WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    IF day_spend + day_holds + p_held_usd > a.daily_usd
       OR month_spend + month_holds + p_held_usd > a.monthly_usd
       OR tokens + token_holds + p_held_tokens > a.daily_tokens THEN
        RETURN jsonb_build_object('status','denied','retry_at', CASE
            WHEN month_spend + month_holds + p_held_usd > a.monthly_usd THEN m + interval '1 month'
            ELSE d + interval '1 day' END);
    END IF;
    UPDATE checklist_budget_accounts SET next_fence=next_fence+1 WHERE user_id=p_user_id RETURNING * INTO a;
    INSERT INTO checklist_budget_reservations(operation_id,user_id,enrollment_id,input_hash,fence,state,
        created_at,expires_at,receipt_id,held_usd,held_tokens,models) VALUES(p_operation_id,p_user_id,
        p_enrollment_id,p_input_hash,a.next_fence,'prepared',t,t + interval '2 minutes',p_receipt_id,
        p_held_usd,p_held_tokens,p_models) RETURNING * INTO r;
    RETURN jsonb_build_object('status','admitted','reservation',to_jsonb(r));
END $$;

CREATE OR REPLACE FUNCTION checklist_budget_start(p_user_id text,p_operation_id uuid,p_fence bigint)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    a checklist_budget_accounts%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    ds numeric; ms numeric; ts bigint;
    dh numeric; mh numeric; th bigint;
BEGIN
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF r.state <> 'prepared' OR r.expires_at <= t OR EXISTS (SELECT 1 FROM checklist_budget_accounts WHERE user_id=p_user_id AND blocked) THEN RETURN jsonb_build_object('status','not_started','reservation',to_jsonb(r)); END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=r.enrollment_id AND e.user_id=p_user_id) THEN
        UPDATE checklist_budget_reservations SET state='released',reason='ownership_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','ownership');
    END IF;
    -- Do not move a prepared hold across UTC windows. Re-admit after midnight.
    IF (t AT TIME ZONE 'UTC')::date <> (r.created_at AT TIME ZONE 'UTC')::date THEN
        UPDATE checklist_budget_reservations SET state='released',reason='window_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','window_changed');
    END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    -- As in admit: a function-seam row's NULL cost is not an unknown price.
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at>=m
               AND ((cost_usd IS NULL AND (provider IS DISTINCT FROM 'function'
                                         OR model IS NULL OR model NOT LIKE 'function:%'))
                    OR cost_usd<0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens<0)) THEN
        UPDATE checklist_budget_reservations SET state='released',reason='usage_unavailable' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at>=d),0),coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at>=d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO ds,ms,ts FROM llm_usage WHERE user_id=p_user_id AND created_at>=m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at)>=d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at)>=m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at)>=d),0)
        INTO dh,mh,th FROM checklist_budget_reservations WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    -- This includes the already-reserved operation, not another new hold.
    IF ds+dh>a.daily_usd OR ms+mh>a.monthly_usd OR ts+th>a.daily_tokens THEN
        UPDATE checklist_budget_reservations SET state='released',reason='capacity_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','denied');
    END IF;
    UPDATE checklist_budget_reservations SET state='started', dispatch_at=t,
        expires_at=t+interval '2 minutes' WHERE operation_id=p_operation_id RETURNING * INTO r;
    -- Only this successful CAS authorizes one logical run. A replay NEVER grants
    -- dispatch; an ambiguous start acknowledgment must not launch a second call.
    RETURN jsonb_build_object('status','started','reservation',to_jsonb(r));
END $$;

NOTIFY pgrst, 'reload schema';
