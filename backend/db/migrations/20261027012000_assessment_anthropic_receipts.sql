-- Extend the existing conservative hold policy to the assessment Haiku slot.
-- Haiku's bounded maximum (.017288 USD) is below the unchanged .07644 hold.
-- Keep existing Gemini receipts and all atomic/CAS/refund protections intact.
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
        IF bill.model = 'gemini-2.5-flash' AND bill.provider = 'gemini' THEN
            expected := round(((bill.prompt_tokens-coalesce(bill.cached_tokens,0)) * .0003
                        + coalesce(bill.cached_tokens,0) * .00003 + bill.completion_tokens * .0025)/1000,10);
        ELSIF bill.model = 'claude-haiku-5-5' AND bill.provider = 'anthropic' AND bill.cached_tokens = 0 THEN
            expected := round((bill.prompt_tokens * .0001 + bill.completion_tokens * .0005)/1000,10);
        ELSE RETURN jsonb_build_object('status','conflict'); END IF;
        IF bill.id IS DISTINCT FROM r.receipt_id OR bill.user_id IS DISTINCT FROM p_user_id
           OR bill.feature IS DISTINCT FROM 'topic_checklist' OR bill.task IS DISTINCT FROM 'topic_checklist'
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
NOTIFY pgrst, 'reload schema';
