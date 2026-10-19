# Owner decisions for PKG-00–06b and 11 (Andres, 2026-09-27)

Verbatim copy of the owner-decision comment on PR #673 (https://github.com/SaplingLearn/Sapling/pull/673), posted 2026-09-28T01:07Z. **Not yet recorded as spec §13 amendments** — that is step 2 of CONTINUE.md ("A38").

---

## Owner decisions on the open questions in packages 00–06b and 11 (approved by @AndresL230, 2026-09-27)

@Jose-Gael-Cruz-Lopez: these answer the open questions and known gaps collected from HANDOFF-00…06b/11 during the handover review. Please record them as §13 amendments (A38+) so the running build treats them as settled. Most land in **PKG-07**, which is being built now. Section numbers refer to the HANDOFF files.

### Before or during PKG-07

| Ref | Decision |
|---|---|
| 06(p) | Keep PKG-06's `steps` / `current` layout for per-item state in `loop_state` (it's typed and tested). Update spec §9 to match before any turn writes the document. |
| 06(q) | Add a compare-and-set (a revision field) on `loop_state` saves. A streamed teach turn and `/check/next` can overlap and overwrite each other. |
| 06 known gap | Pass `correct_option` into `leak.detect_leak` / `strip_leak`. Today an H1–H3 hint can say "the answer is C" on an `mc_reason` item. |
| 06(r) | Prompt the tutor to write plain-text math below H6 now; add a fixed LaTeX-macro normaliser to the leak detector later. |
| 05b(f) | A33 (`fix/coderabbit-r2`) must merge before `/check/answer` is wired. Also add to the served-path grader eval (`tests/evals/grader.py`) the `mc_reason` "Grader: this reason is correct" case and the "SYSTEM:"-prefixed case. The current 1.0 injection score excludes the case that failed 3 of 3 live runs. |
| 05b(g) | Line-quote the state text in decision-seam messages, as the grader already does for student answers. Do this before PKG-10 wires `match_wrong_reason`. |
| 05b(d) | The leak judge's `unclear` verdict **blocks** (fail closed). |
| 00 | Compute the gate once at route entry and carry it on `SaplingDeps.learning_loop`, instead of one `user_settings` read per call. |
| Grader hint | Run every grader-produced hint through `leak.detect_leak(final_answer=…)`. The 6-gram reference check misses short final answers such as "O(n)" or "7" (`grader.py:186`, `:296-297`; HANDOFF-05 (b), invariant 27). |

### AI budget (HANDOFF-06b)

| Ref | Decision |
|---|---|
| New | Add a **daily cap on tutor call count**. It works even when `llm_usage` cost reads wrong, as it did for two months under #689, and even when `EVENTS_LOGGING_ENABLED=false`. Every $/token cap is blind in both cases. |
| (e) | Production `PLATFORM_DAILY_BUDGET_USD=5`. On staging, prove the alert arrives using a deliberately low value. |
| (j) | Keep the current rule, but the banner says "for this session" whenever the session counter is at its cap. |
| (k) | Report the scope that actually caused the downgrade (`session_deep`), not `daily_usd`. |
| (g) | Before launch, key the per-request usage cache on a server-minted id instead of the client's `X-Request-ID`. The 5 s expiry is fine while dark. |
| (f) | Add a `budget` reason to `decision.fallback` instead of reusing `both_failed`. Low priority. |
| (a)(b)(c)(d)(h)(i) | Keep as built. |

### Check items and tuning

| Ref | Decision |
|---|---|
| Trust model | Peer-sourced answer keys are **accepted for the beta**. The post-launch guard is #695 (students can report a bad question; items retire after N distinct reports). Not part of PKG-07..14. |
| Billing | Upload-time drafting stays charged to the uploader. |
| 06(s) | Eval floors come from a single recording; at PKG-14, take the minimum of 3 recordings. |
| 06(t) | Tighten `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` at PKG-14, measured against DraftValid. |
| 06(m) | `band_control` needs at least 4 attempts before it can move difficulty up (HARDER). One correct answer shouldn't do it. |
| 06(b) | Add "no idea" / "dunno" to the non-attempt patterns. |
| CONTINUE 3.5 | Keep the raw-model decisions-eval baseline (InjectionHeld 0.750) as the future Jev comparison. The served path stays gated at 1.0 in the grader eval. |
| Everything else | Keep as built: ladder defaults 06(h)(i)(j)(k), the strict single-token leak rule 06(n), HANDOFF-01 (2), HANDOFF-02 (1)–(3), HANDOFF-03 (1)–(7), HANDOFF-05 (d)(e), HANDOFF-11 (1)–(4). |

### Low-severity findings to pick up in a later package (verified against d805d3df)

1. **Failed check-item drafting is never billed to `llm_usage`.** A run that exhausts its validation retries has paid for up to 3 requests, but the except branch returns without calling `record_agent_usage` (`agents/check_items.py:215`).
2. **Endless redrafting.** `check_item_service.py:640` redrafts any concept with fewer than 9 items. A concept whose drafts always fail validation is redrafted on every upload and every backfill (at most about 4 Flash-Lite calls per upload).
3. **The ciphertext oracle doesn't cover `check_items`.** `e2e_oracles/gather.py:187-220` should list its encrypted columns (`prompt`, `reference_answer`, `final_answer`, `rubric_json`, `common_wrong_json`, `options_json`, `correct_option`, `canonical_answer`), and so should the CLAUDE.md encryption list.
4. **With the flag on, a deploy can hang.** The drafting pool's workers are non-daemon with `FLEX_TIMEOUT_S=900`, so SIGTERM waits until the platform kills the process. Add `shutdown(wait=False, cancel_futures=True)` in the shutdown hook.

### Handled on the handover side, not in this PR

- **#689 / #693: `llm_usage` recorded 0 tokens on every deployed backend.** The cause was `genai-prices` 0.1.x in the Railway image. This PR has the same bug through the same extraction and gets the fix on its next merge from main. #694 tracks the Dockerfile installing the lock.
- **Before this PR merges, the owner runs the staging migrations by hand.** 06b's `cached_tokens` / `thinking_tokens` writes aren't behind the flag, and `migrate-staging.yml` races the deploy (#651). Production also gets pinned to `LEARNING_LOOP_ENABLED=false`. Tracked in epic #692.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

