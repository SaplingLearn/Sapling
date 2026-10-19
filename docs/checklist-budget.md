# Checklist capacity reservations

The checklist paid-cache-miss path uses the backend-only RPCs in
`20261019125459_checklist_budget.sql`. Apply that migration before deploying all
participating workers. A missing/unavailable RPC fails closed. Reads, checkmarks,
empty evidence and a current cached checklist remain free.

The database serializes participating requests with a per-user account row.
Admission includes committed canonical `llm_usage` and unresolved checklist holds.
The stored ceilings are the current generation defaults: **$0.20 per UTC day,
$2.00 per UTC month, and 400,000 tokens per UTC day**. Tighter configured values
can only lower those stored limits; a stale or more permissive worker cannot
raise them. Raising a stored policy requires an explicit, reviewed database
policy change. NULL/non-finite/negative prices or invalid token totals in the
current month's ledger prevent paid admission. Shadow/extra decision tokens
retain the existing daily-token exclusion; their dollar costs still count.

The pinned policy is Gemini 2.5 Flash with 50,000 **cumulative** estimated input
tokens, at most three logical generation requests and 8,192 output tokens per
request, including thinking. Its full-input counter includes the system/schema
and retry envelope. At the current canonical prices the capacity hold is:

- Input: 50,000 × $0.0003 / 1,000 = $0.015.
- Output: 3 × 8,192 × $0.0025 / 1,000 = $0.06144.
- Total: **$0.07644 and 74,576 tokens**.

This uses the provider's full-input counting oracle as an estimate. It is not a
literal invoice bound, and countTokens is not generation. Client deadlines cannot
prove that remote work stopped. The tracker observes each logical SDK generation
handler and its response; it cannot prove invisible transport/provider retries.
Other features do not reserve through this mutex, so this is **not a global
spend cap**. Their queued/in-flight usage and concurrent ledger writes remain a
shared-budget exposure. Older workers must be replaced before claiming the
checklist-participant guarantee.

An operation is `prepared`, `started`, `unknown`, `settled` or `released`.
`start` is a fenced compare-and-swap immediately before the first generation
handler, after token preflight. It rechecks ownership, UTC window and capacity.
Only its first successful acknowledgment authorizes dispatch; a replay does not.
The start RPC runs off the event loop, so cancellation while awaiting its
acknowledgment never enters generation. The synchronous bridge may still wait
for a running DB HTTP call during executor cleanup; the provider deadline is
not a hard bound on total HTTP response time.
An expired prepared operation can be released because its old fence cannot start.
A started operation does **not** expire into a refund. After a two-minute grace
it becomes unknown, retaining its entire original-window hold, while another
explicit refresh may reserve additional capacity. The new request must fit
alongside all current-window exposure. The UI's retryable error and Retry-After
explain the delay; allowance denials identify the next UTC window. Old unknown
records remain available for reconciliation when their windows roll over.

The worker records every actual response and independently counts entered model
handlers. A final bill requires all attempts to have complete, consistent native
usage for the approved served model. Complete bills settle even if the outline
fails semantic validation; invalid output never updates the cache. Incomplete,
network, timeout, cancellation and crashed-worker outcomes retain exposure. A
live worker may release a hold only when it proves it never entered billable
generation. An explicit local `FunctionModel` is a nonbillable test seam, never a
zero-counter fallback for a real provider.

Settlement atomically writes one stable canonical `llm_usage` receipt and the
reservation transition, plus an encrypted cache only for a valid owned newest
operation. Checklist usage is never also queued. Identical settlement replay is
idempotent; changed receipt content conflicts. Lost acknowledgments use the same
identity, then read back exact receipt content. An older result may settle its
bill but cannot overwrite a newer operation's cache. Deleting enrollment/user
records does not delete financial exposure. A measured bill beyond its estimate
is recorded in full and blocks further paid checklist admission pending explicit
operator reconciliation; saved checklists and other free actions remain usable.

Python unit tests cover the adapter, tracker, strict receipt and service protocol.
Real PostgreSQL concurrency, rollback, grants, UTC waits and ambiguous-ACK tests
are separate required gates; passing unit mocks alone does not validate them.
