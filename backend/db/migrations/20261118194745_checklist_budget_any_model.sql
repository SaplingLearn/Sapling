-- The checklist budget priced one model only. 20261019125459 fixed every hold
-- at gemini-2.5-flash's worst case (.0764400000 USD, 74576 tokens) and
-- settlement re-priced each bill at flash's rates and refused any other
-- model or provider. The topic_checklist slot defaults to claude-haiku-5-5
-- (agents/_providers.py, ADR 0030), with gemini-2.5-flash as its llm_fallback,
-- so every real-mode refresh was refused (PR #866 review B1).
--
-- Now the backend prices the hold from services/llm_pricing for the models
-- that can serve the run (the slot's model and its fallback,
-- services/checklist_budget.py::price_hold) and admission stores the hold with
-- those models as `provider:model` labels. Settlement accepts a bill from one
-- of the reservation's own models only, priced by the backend: a bill over its
-- hold still blocks the account for reconciliation, as before.
--
-- 20261019125459 and 20261108033310 are applied and stay as they are. Here:
--   * checklist_budget_reservations: held_usd/held_tokens lose their fixed
--     CHECKs and defaults (any positive hold, stated at admission); a new
--     NOT NULL `models`, filled for existing rows with the one model every one
--     of them was admitted and priced for.
--   * checklist_budget_accounts.policy: the policy is 'checklist-50k-3x8192-v2'.
--   * checklist_budget_admit: a new signature (+ p_held_usd, p_held_tokens,
--     p_models), the one the backend calls (PostgREST picks an overload by its
--     argument names). The 9-argument function stays as it is (the learning
--     release verifier inventories every declared signature) but can no longer
--     admit anything: its INSERT names no hold or models, which now have no
--     default, so a worker still on the old code fails and rolls back instead
--     of holding the old fixed amount.
--   * checklist_budget_reconcile: the same signature; no fixed model, provider
--     or price.
-- checklist_budget_start and checklist_budget_read are unchanged: start sums
-- the stored holds, whatever they are.

DO $$ DECLARE c record; BEGIN
    FOR c IN
        SELECT conrelid::regclass AS tbl, conname FROM pg_constraint
        WHERE contype = 'c' AND (
            (conrelid = 'checklist_budget_reservations'::regclass
             AND (pg_get_constraintdef(oid) LIKE '%held_usd%' OR pg_get_constraintdef(oid) LIKE '%held_tokens%'))
            OR (conrelid = 'checklist_budget_accounts'::regclass AND pg_get_constraintdef(oid) LIKE '%policy%'))
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', c.tbl, c.conname);
    END LOOP;
END $$;

ALTER TABLE checklist_budget_reservations
    ALTER COLUMN held_usd DROP DEFAULT,
    ALTER COLUMN held_tokens DROP DEFAULT,
    ADD COLUMN IF NOT EXISTS models text[];
UPDATE checklist_budget_reservations SET models = ARRAY['gemini:gemini-2.5-flash'] WHERE models IS NULL;
ALTER TABLE checklist_budget_reservations
    ALTER COLUMN models SET NOT NULL,
    ADD CONSTRAINT checklist_budget_reservations_hold_check CHECK (held_usd > 0 AND held_tokens > 0),
    ADD CONSTRAINT checklist_budget_reservations_models_check
        CHECK (cardinality(models) > 0 AND array_position(models, NULL) IS NULL);

UPDATE checklist_budget_accounts SET policy = 'checklist-50k-3x8192-v2';
ALTER TABLE checklist_budget_accounts
    ALTER COLUMN policy SET DEFAULT 'checklist-50k-3x8192-v2',
    ADD CONSTRAINT checklist_budget_accounts_policy_check CHECK (policy = 'checklist-50k-3x8192-v2');

-- 20261108033310's body, with the hold and its models taken from the caller.
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

-- 20261108033310's body; the settle check names no model, provider or price.
CREATE OR REPLACE FUNCTION checklist_budget_reconcile(
    p_user_id text,p_operation_id uuid,p_fence bigint,p_action text,
    p_receipt jsonb DEFAULT NULL,p_fingerprint text DEFAULT NULL,p_content text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    bill llm_usage%ROWTYPE;
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
        -- The bill comes from one of the models this hold was priced for, and
        -- the backend priced it (services/llm_pricing): positive and finite.
        IF bill.id IS DISTINCT FROM r.receipt_id OR bill.user_id IS DISTINCT FROM p_user_id
           OR bill.feature IS DISTINCT FROM 'topic_checklist' OR bill.task IS DISTINCT FROM 'topic_checklist'
           OR bill.model IS NULL OR bill.provider IS NULL
           OR NOT (bill.provider || ':' || bill.model = ANY(r.models))
           OR bill.created_at IS DISTINCT FROM r.dispatch_at OR bill.session_id IS NOT NULL
           OR bill.prompt_tokens IS NULL OR bill.prompt_tokens <= 0 OR bill.completion_tokens IS NULL OR bill.completion_tokens <= 0
           OR bill.total_tokens IS DISTINCT FROM bill.prompt_tokens+bill.completion_tokens
           OR bill.cached_tokens IS NULL OR bill.cached_tokens < 0 OR bill.cached_tokens > bill.prompt_tokens
           -- NULL: a provider that bills thinking inside its output reports no count
           OR (bill.thinking_tokens IS NOT NULL
               AND (bill.thinking_tokens < 0 OR bill.thinking_tokens > bill.completion_tokens))
           OR bill.cost_usd IS NULL OR bill.cost_usd::text IN ('NaN','Infinity','-Infinity') OR bill.cost_usd <= 0
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
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id FOR SHARE OF e,o,c) THEN
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
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id FOR SHARE OF e,o,c) THEN
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

REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint,numeric,bigint,text[]) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint,numeric,bigint,text[]) FROM %I',role_name);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint,numeric,bigint,text[]) TO service_role;
    END IF;
END $$;
NOTIFY pgrst, 'reload schema';
