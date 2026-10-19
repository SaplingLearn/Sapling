-- Checklist-participant capacity admission, not a global/provider invoice cap.
-- Apply before the service. Account lock serializes all participating operations.
-- USD estimate = 50,000 cumulative input * .0003/1000 +
-- 3 * 8,192 output (including thinking) * .0025/1000 = .0764400000.
-- The native full-input count is a provider oracle estimate, not an invoice bound.
CREATE TABLE IF NOT EXISTS checklist_budget_accounts (
    user_id text PRIMARY KEY,
    policy text NOT NULL DEFAULT 'flash-50k-3x8192-v1' CHECK (policy = 'flash-50k-3x8192-v1'),
    daily_usd numeric(18,10) NOT NULL DEFAULT .20 CHECK (daily_usd > 0 AND daily_usd <= .20),
    monthly_usd numeric(18,10) NOT NULL DEFAULT 2.00 CHECK (monthly_usd > 0 AND monthly_usd <= 2.00),
    daily_tokens bigint NOT NULL DEFAULT 400000 CHECK (daily_tokens > 0 AND daily_tokens <= 400000),
    blocked boolean NOT NULL DEFAULT false,
    next_fence bigint NOT NULL DEFAULT 0
);
-- Deliberately no cascade: deleting an enrollment/user cannot erase possible bills.
CREATE TABLE IF NOT EXISTS checklist_budget_reservations (
    operation_id uuid PRIMARY KEY,
    user_id text NOT NULL REFERENCES checklist_budget_accounts(user_id),
    enrollment_id text NOT NULL,
    input_hash text NOT NULL,
    fence bigint NOT NULL,
    state text NOT NULL CHECK (state IN ('prepared','started','unknown','settled','released')),
    held_usd numeric(18,10) NOT NULL DEFAULT .0764400000 CHECK (held_usd = .0764400000),
    held_tokens bigint NOT NULL DEFAULT 74576 CHECK (held_tokens = 74576),
    created_at timestamptz NOT NULL,
    dispatch_at timestamptz,
    expires_at timestamptz NOT NULL,
    receipt_id text NOT NULL UNIQUE,
    receipt jsonb,
    fingerprint text,
    reason text,
    cache_published boolean NOT NULL DEFAULT false,
    UNIQUE (user_id, fence)
);
CREATE UNIQUE INDEX IF NOT EXISTS checklist_budget_active_enrollment
    ON checklist_budget_reservations(enrollment_id) WHERE state IN ('prepared','started');
CREATE INDEX IF NOT EXISTS checklist_budget_holds ON checklist_budget_reservations(user_id, state);

CREATE OR REPLACE FUNCTION checklist_budget_admit(
    p_user_id text, p_enrollment_id text, p_input_hash text,
    p_operation_id uuid, p_receipt_id text, p_policy text,
    p_daily_usd numeric, p_monthly_usd numeric, p_daily_tokens bigint
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
       OR p_receipt_id IS NULL OR p_policy IS DISTINCT FROM 'flash-50k-3x8192-v1'
       OR p_input_hash IS NULL OR p_daily_usd IS NULL OR p_daily_usd <= 0
       OR p_monthly_usd IS NULL OR p_monthly_usd <= 0 OR p_daily_tokens IS NULL OR p_daily_tokens <= 0
       OR p_daily_usd::text IN ('NaN','Infinity','-Infinity') OR p_monthly_usd::text IN ('NaN','Infinity','-Infinity') THEN
        RAISE EXCEPTION 'Invalid checklist admission identity/policy';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=p_enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL) THEN
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
           OR r.input_hash IS DISTINCT FROM p_input_hash OR r.receipt_id IS DISTINCT FROM p_receipt_id THEN
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
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at >= m
               AND (cost_usd IS NULL OR cost_usd < 0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
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
    IF day_spend + day_holds + .07644 > a.daily_usd
       OR month_spend + month_holds + .07644 > a.monthly_usd
       OR tokens + token_holds + 74576 > a.daily_tokens THEN
        RETURN jsonb_build_object('status','denied','retry_at', CASE
            WHEN month_spend + month_holds + .07644 > a.monthly_usd THEN m + interval '1 month'
            ELSE d + interval '1 day' END);
    END IF;
    UPDATE checklist_budget_accounts SET next_fence=next_fence+1 WHERE user_id=p_user_id RETURNING * INTO a;
    INSERT INTO checklist_budget_reservations(operation_id,user_id,enrollment_id,input_hash,fence,state,
        created_at,expires_at,receipt_id) VALUES(p_operation_id,p_user_id,p_enrollment_id,p_input_hash,
        a.next_fence,'prepared',t,t + interval '2 minutes',p_receipt_id) RETURNING * INTO r;
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
                   WHERE e.id=r.enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL) THEN
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
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at>=m
               AND (cost_usd IS NULL OR cost_usd<0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
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

CREATE OR REPLACE FUNCTION checklist_budget_read(p_user_id text,p_operation_id uuid)
RETURNS jsonb LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT jsonb_build_object('status','found','reservation',to_jsonb(r))
    FROM checklist_budget_reservations r WHERE user_id=p_user_id AND operation_id=p_operation_id;
$$;

CREATE OR REPLACE FUNCTION checklist_budget_reconcile(
    p_user_id text,p_operation_id uuid,p_fence bigint,p_action text,
    p_receipt jsonb DEFAULT NULL,p_fingerprint text DEFAULT NULL,p_content text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    bill llm_usage%ROWTYPE;
    expected numeric;
    published boolean := false;
BEGIN
    PERFORM 1 FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF p_action='settle' THEN
        IF r.state='settled' THEN
            IF r.receipt IS DISTINCT FROM p_receipt OR r.fingerprint IS DISTINCT FROM p_fingerprint THEN
                RETURN jsonb_build_object('status','conflict');
            END IF;
            RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
        END IF;
        IF r.state NOT IN ('started','unknown') OR p_receipt IS NULL
           OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$' THEN RETURN jsonb_build_object('status','conflict'); END IF;
        bill := jsonb_populate_record(NULL::llm_usage,p_receipt);
        expected := round(((bill.prompt_tokens-coalesce(bill.cached_tokens,0)) * .0003
                    + coalesce(bill.cached_tokens,0) * .00003 + bill.completion_tokens * .0025)/1000,10);
        IF bill.id IS DISTINCT FROM r.receipt_id OR bill.user_id IS DISTINCT FROM p_user_id
           OR bill.feature IS DISTINCT FROM 'topic_checklist' OR bill.task IS DISTINCT FROM 'topic_checklist'
           OR bill.model IS DISTINCT FROM 'gemini-2.5-flash' OR bill.provider IS DISTINCT FROM 'gemini'
           OR bill.created_at IS DISTINCT FROM r.dispatch_at OR bill.session_id IS NOT NULL
           OR bill.prompt_tokens IS NULL OR bill.prompt_tokens <= 0 OR bill.completion_tokens IS NULL OR bill.completion_tokens <= 0
           OR bill.total_tokens IS DISTINCT FROM bill.prompt_tokens+bill.completion_tokens
           OR bill.cached_tokens IS NULL OR bill.cached_tokens < 0 OR bill.cached_tokens > bill.prompt_tokens
           OR bill.thinking_tokens IS NULL OR bill.thinking_tokens < 0 OR bill.thinking_tokens > bill.completion_tokens
           OR bill.cost_usd IS NULL OR bill.cost_usd::text IN ('NaN','Infinity','-Infinity')
           OR bill.cost_usd IS DISTINCT FROM expected OR expected <= 0
           OR p_receipt - ARRAY['id','user_id','request_id','feature','task','model','provider','prompt_tokens',
                'completion_tokens','total_tokens','cached_tokens','thinking_tokens','session_id','cost_usd','created_at'] <> '{}'::jsonb
        THEN RETURN jsonb_build_object('status','conflict'); END IF;
        -- Stable id plus exact content verification makes ambiguous insert ACKs
        -- safe to replay; NEVER additionally enqueue this checklist bill.
        INSERT INTO llm_usage(id,user_id,request_id,feature,task,model,provider,prompt_tokens,completion_tokens,
            total_tokens,cached_tokens,thinking_tokens,session_id,cost_usd,created_at)
        VALUES(bill.id,bill.user_id,bill.request_id,bill.feature,bill.task,bill.model,bill.provider,bill.prompt_tokens,
            bill.completion_tokens,bill.total_tokens,bill.cached_tokens,bill.thinking_tokens,bill.session_id,bill.cost_usd,bill.created_at)
        ON CONFLICT(id) DO NOTHING;
        IF NOT EXISTS (SELECT 1 FROM llm_usage u WHERE u.id=bill.id AND u.created_at=bill.created_at AND (to_jsonb(u)-'created_at') @> (p_receipt-'created_at')) THEN
            RAISE EXCEPTION 'Checklist receipt identity already has different content';
        END IF;
        IF bill.cost_usd > r.held_usd OR bill.total_tokens > r.held_tokens THEN
            UPDATE checklist_budget_accounts SET blocked=true WHERE user_id=p_user_id;
        END IF;
        -- A late old result may settle its bill but cannot overwrite a newer
        -- operation's cache, even when that newer operation failed/was released.
        IF p_content IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='settled',receipt=p_receipt,fingerprint=p_fingerprint,
            cache_published=published,reason=NULL WHERE operation_id=p_operation_id RETURNING * INTO r;
        RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
    ELSIF p_action='no_dispatch' AND r.state IN ('prepared','started','unknown') THEN
        -- Trusted backend proof: this process never entered the generation
        -- handler. Counter-only requests are not billed generation. A process
        -- crash cannot provide this proof, so its started hold remains unknown.
        -- p_content here is exclusively the explicit local FunctionModel seam
        -- in the trusted backend; it never creates a paid usage row.
        IF p_content IS NOT NULL AND r.state='prepared' AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id
            AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='released',cache_published=published,reason='no_generation_dispatched'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='unknown' AND r.state IN ('started','unknown') THEN
        -- Preserve exclusivity until grace expiry; admission changes expired
        -- started -> unknown and retains the entire financial hold.
        UPDATE checklist_budget_reservations SET reason='dispatch_outcome_unknown'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='no_dispatch' AND r.state='released' THEN NULL;
    ELSE RETURN jsonb_build_object('status','conflict');
    END IF;
    RETURN jsonb_build_object('status',r.state,'reservation',to_jsonb(r));
END $$;

ALTER TABLE checklist_budget_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE checklist_budget_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE checklist_budget_accounts,checklist_budget_reservations FROM PUBLIC;
REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint), checklist_budget_start(text,uuid,bigint),
    checklist_budget_read(text,uuid), checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
            EXECUTE format('REVOKE ALL ON TABLE checklist_budget_accounts,checklist_budget_reservations FROM %I',role_name);
            EXECUTE format('REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint), checklist_budget_start(text,uuid,bigint), checklist_budget_read(text,uuid), checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text) FROM %I',role_name);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT SELECT,INSERT,UPDATE ON TABLE checklist_budget_accounts,checklist_budget_reservations TO service_role;
        GRANT EXECUTE ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint), checklist_budget_start(text,uuid,bigint),
            checklist_budget_read(text,uuid), checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text) TO service_role;
    END IF;
END $$;
NOTIFY pgrst, 'reload schema';
