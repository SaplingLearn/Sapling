# HANDOFF-a37 — mc-reason-options

Written by the fix lane `fix/mc-reason-options` (spec §13 A37, a PKG-04 reopen) for its round 4: the series coordinator's design decision that ends the oscillation between two fix rounds. Rounds 1–3 are recorded in HANDOFF-04 (Post-hoc changes) and spec §13 A37; this file is the hand-off for the lane as it stands after round 4. Read by PKG-07 (it depends on this lane), PKG-10 (misconceptions read `common_wrong_json`) and PKG-13/14. Keep every heading, even if the answer is "none".

## What changed

An `mc_reason` draft's distractors each carry their own misconception, and code derives the item's common wrong reasons from the options, so there is nothing left to cross-reference. `OptionDraft` is `{text, is_correct, misconception_key, misconception_text}`: the correct option carries no misconception; each distractor carries a snake_case key and one sentence naming the mistake that makes it tempting. `checks.common_wrong(draft)` is the item's stored `common_wrong_json`: for `mc_reason`, the distractors' misconceptions in the order written (the draft's own `wrong_keys` / `wrong_texts` are never read); for free and teachback, the paired lists as before. `lettered_options` stores each distractor's `misconception_key` as its `wrong_key`, so the stored option keys and the stored wrong reasons are one list by construction. The stored shape is unchanged, so the grader, `agents/tools/check.py`, `services/decisions.py` and PKG-10 read it as before.

Distinct keys are enforced by the schema descriptions and by validation. The rule words `correct_misconception`, `misconception_key` and `misconception_text` replace `correct_key` and `distractor_key`. Code repairs only where no guess is needed. When the correct option carries a misconception, it is cleared. When two distractors stating different misconceptions share a key, or a distractor that states one gives no key, each such distractor is keyed from its own text (`checks.misconception_slug`), with a digest appended on a clash. Two distractors stating the same misconception are rejected, whatever their keys.

The prompt, the schema descriptions, the E2E handler constants, the `WrongReasonCount` evaluator and the schema-budget pin follow. The free and teachback format lines now restate the short closing sentence, because the structure change alone tripled the direct CS101 calls (8 of 44 to 24 of 44) that left "Final answer:" off every free and teachback reference (Deviations). The check_items eval is re-recorded.

## Symbols added

- `backend/learning/checks.py::OptionDraft.misconception_key` / `.misconception_text` — `str | None = None` each; null on the correct option. They replace `OptionDraft.wrong_key`.
- `backend/learning/checks.py::common_wrong(draft) -> list[WrongReason]` — the wrong reasons an item is stored with; for `mc_reason`, from the distractors; for a draft `validate_draft` passed.
- `backend/learning/checks.py::misconception_slug(text) -> str` — deterministic snake_case key from a misconception's text: first `_SLUG_MAX_WORDS` words that are not `_STOPWORDS`, ASCII-folded, apostrophes dropped; `misconception_<digest>` for a text with no Latin letter or digit.
- `backend/learning/checks.py::MC_OPTION_RULES` — now `("option_count", "one_correct", "correct_misconception", "misconception_key", "misconception_text", "option_text", "letter")`.
- `backend/agents/check_items.py::_CLOSING` — the sentence the free and teachback format lines end with.
- `backend/agents/function_handlers_e2e.py::E2E_CHECK_ITEM_OPTIONS` — option objects now carry `misconception_key` / `misconception_text`; the `mc_reason` item lists `wrong_keys: []`, `wrong_texts: []`; `E2E_CHECK_ITEM_MC_WRONG_KEYS` / `_MC_WRONG_TEXTS` are its distractors' misconceptions and its stored common wrong reasons.
- No table, column, route, event or AgentTask is added.

## Constants chosen

- `_SLUG_MAX_WORDS = 6` † and `_SLUG_DIGEST_LEN = 8` † (`learning/checks.py`): key-format literals, not loop tuning knobs, so they are not in `learning/params.py` (the `_MIN_TOKEN_LEN` precedent).
- Unchanged: `CHECK_ITEM_MC_OPTIONS = 4` †, `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS = 20` †, `CHECK_ITEM_MIN_WRONG`.

## Deviations from spec

- Spec §13 A37 (rounds 1–3): "each distractor's `wrong_key` names a DISTINCT entry of the item's `wrong_keys`" (`distractor_key`) → each distractor carries its own misconception, and code derives the `mc_reason` item's wrong reasons from the options (`common_wrong`). Nothing is cross-referenced → series coordinator's design decision for round 4 (structure, not conventions). The third review's ENG150 run stored 1 `mc_reason` item for a concept because the model broke that cross-reference; in the round-4 direct runs of the round-3 draft it dropped 10 of 409 `mc_reason` drafts. Commit 9d1ae78; spec §13 A37 rewritten.
- The decision's example `{text, is_correct: false, misconception: {key, text}}` → two flat scalars on the option, `misconception_key` and `misconception_text` → the #153 schema budget forbids an optional nested model (the correct option has no misconception), and a nested model would take the check_items output to 21 properties against the ceiling of 20. With the flat pair it is exactly 20, which a test pins.
- The decision lists one key repair: duplicate keys with different misconception texts get a deterministic slug from the text → the same repair also keys a distractor that gives a text but no key → the key is only the stated misconception's id, so deriving it guesses nothing. It is in the decision's own "code repair only where no guess is needed". Every distractor sharing a key is re-keyed, so code never chooses which of them the key "belonged" to. A slug another distractor already holds gets the text's 8-hex digest appended. The repair runs only when exactly one option is marked correct, every distractor states a misconception and no two state the same one.
- "Identical misconception texts → reject" → applied whatever the keys: two distractors stating one misconception (compared as option texts are: whitespace, case and closing punctuation aside) are rejected even under different keys (`misconception_text`) → they are not two mistakes, and a stored list of two identical wrong reasons would split one misconception across two keys for PKG-10.
- The prompt, beyond the decision's "update the agent prompt": the free and teachback format lines restate the closing sentence, kept short (`_CLOSING`), commit 30fc52d. Without it, the round-4 prompt and schema made flash-lite write "Final answer:" on the `mc_reason` references only, in 24 of 44 direct CS101 calls (the round-3 draft: 8 of 44). Free and teachback stored fell from 84% to 60% across four subjects. Reverting the other wording did not fix it: the wrong-reason bullet, the schema descriptions, the option docstring, or the whole prompt but the field names each left it at 5 of 8 to 13 of 16. The closing line did: 6 of 32 on CS101 and 0 of 40 elsewhere, with free and teachback stored at 89%. Without "short", 51 of 96 HIST200 free and teachback drafts failed the 20-token cap.
- `WrongReasonCount` (eval) reads an `mc_reason` item's distractors (`common_wrong` after `repair_draft`), not its own lists → the lists are not read or stored for `mc_reason`.
- The `McCorrectNotLongest` gate 0.611 → 0.5 (the round-4 recording: 9 of 17 stored drafts against 11 of 17) → the gate follows the recording, as in rounds 2 and 3. The direct runs show no change: the correct option was strictly the longest in 56 of 135 stored items against 57 of 130 on the round-3 draft (24 calls each, three subjects).
- Hand-off file: rounds 1–3 recorded the lane in HANDOFF-04 Post-hoc changes → round 4 also writes this HANDOFF-a37.md, as the coordinator asked, and adds HANDOFF-04 Post-hoc lines. The four HANDOFF-04 Known gaps and the Open question that round 4 changes are rewritten there.
- Commit subjects: rounds 1–3 used `PKG-04 —` → round 4 uses `PKG-a37 —`, as the coordinator asked.

## Known gaps

- Two distractors stating the same misconception still drop the item, as the decision says. On the round-4 draft this is 6 of 432 `mc_reason` drafts in 72 direct calls, every one of them that case: "This crop moved from the Americas to Afro-Eurasia." on all three HIST200 distractors, and "Confuses the recursive case with the base case." on two CS101 ones. It was 2 of 96 in the live runs. A distractor stating no misconception would drop too; none did. Together with a deliberating reference, it can leave a concept below 2 `mc_reason` items. That happened in 1 of 16 live passes: ENG150 Logical Fallacies, where the difficulty-1 question "which of these is a fallacy?" was set against three appeals whose distractors genuinely share one mistake, and whose passages miss the fallacy chunks (A37 known limit (8)). In the direct runs, a concept fell below 2 in 3 of 120 calls on the final prompt (ENG150 2 of 48, HIST200 1 of 24). A wording asking for distractors wrong in different ways (24 ENG150 calls each) moved none of it: 22 and 23 of 24 against 23 of 24.
- A37 known limit (1) remains at about the round-3 rate. A call that writes no "Final answer:" sentence on its free and teachback references loses them: 6 of 32 direct calls on CS101, 0 of 40 on ENG150, HIST200 and CHEM121. The round-3 draft had 8 of 44 and 1 of 24. This is open for the coordinator (spec §13 A37 (1)). The live check hit it once in 16 passes, in run 1's CS101 pass 2, which kept 1 of 12 free and teachback drafts.
- Keys stay model-invented or code-derived. A derived key (`counts_iterations`) seldom matches the key another item uses for the same misconception, so PKG-10's rollup by `wrong_key` can split one misconception across two keys. Real student wrong reasons are still PKG-10's.
- An `mc_reason` draft's own `wrong_keys` / `wrong_texts` are ignored. A model that fills them anyway spends tokens on data nobody reads; the round-4 recording and live runs had 0 such drafts.
- A37 known limits (2) and (4)–(9) are unchanged: surface-form `option_text`, the 20-token cap on long correct options, unverified content, the grader request limit, the cosmetic ". .", the lexical passage ranking, and options that carry their own reason.
- Flakes observed: none new. See the live check below.

Live check: two fresh-DB `e2e_cycle` mid-hooks on the code of d28fe4a, each replaying 76 migrations, on real gemini-2.5-flash-lite with `LEARNING_LOOP_ENABLED=true`. The probe is `scratchpad/mcfix5/live_probe.py`, not committed. Four lectures were inserted as shared `course_material` with `index_status='pending'` and indexed by `index_document`: CS101 recursion and pointers (`rich-course-cs101`, 18 shared chunks), HIST200 Atlantic world (15), ENG150 argument and fallacies (21, the third review's subject), and a CHEM121 gases lecture, the physical-science one (`rich-course-chem121`, 21). `generate_for_document` then ran twice per subject for two concepts, on the standard tier, retiring the items between passes. Drop reasons were computed from the returned drafts with `repair_draft` + `validate_draft` and matched the stored counts in every pass.

| run | subject | pass | stored / returned | `mc_reason` per concept | drops (drafts) | repairs |
|---|---|---|---|---|---|---|
| 1 | CS101 | 1 | 17/18 | Recursion 2, Pointers and Memory 3 | 1 mc `deliberation` | 1 free `stepwise` |
| 1 | CS101 | 2 | 7/18 | 3, 3 | 11 free/teachback `final_answer` not in reference (known limit (1)) | 5 mc `final_answer` |
| 1 | HIST200 | 1 | 16/18 | Columbian Exchange 2, Mercantilism 3 | 1 mc `misconception_key` + `misconception_text` (one misconception stated twice); 1 free final answer = the concept name | — |
| 1 | HIST200 | 2 | 17/18 | 3, 3 | 1 free final answer = the concept name | — |
| 1 | ENG150 | 1 | 18/18 | Rhetorical Appeals 3, Logical Fallacies 3 | — | — |
| 1 | ENG150 | 2 | **16/18** | 3, **1** | 1 mc: all three distractors "Confuses a logical fallacy with a rhetorical appeal." (`misconception_key` + `misconception_text`); 1 mc `deliberation` | 5 mc `misconception_key` |
| 1 | CHEM121 | 1 | 17/18 | Ideal Gas Law 3, Kinetic Molecular Theory 3 | 1 free final answer of 21 tokens | 4 `stepwise` |
| 1 | CHEM121 | 2 | 18/18 | 3, 3 | — | 4 `stepwise` |
| 2 | CS101 | 1 | 18/18 | 3, 3 | — | — |
| 2 | CS101 | 2 | 18/18 | 3, 3 | — | — |
| 2 | HIST200 | 1 | 17/18 | 3, 3 | 1 free final answer of 21 tokens | — |
| 2 | HIST200 | 2 | 18/18 | 3, 3 | — | — |
| 2 | ENG150 | 1 | 16/18 | 3, 3 | 2 free `final_answer` not in reference | — |
| 2 | ENG150 | 2 | 18/18 | 3, 3 | — | — |
| 2 | CHEM121 | 1 | 15/18 | 3, 3 | 3 free: final answers of 21 and 22 tokens, one printed in the stem | 2 `stepwise` |
| 2 | CHEM121 | 2 | 18/18 | 3, 3 | — | — |

- Requirement "≥ 2 `mc_reason` stored per concept per pass": met in 15 of 16 passes. Run 2 met it in 8 of 8, with 3 + 3 everywhere. Run 1 met it in 7 of 8; ENG150 pass 2 stored 1 for Logical Fallacies.
- Every stored `mc_reason` item passed every check in both runs, 92 of 92 (44 + 48). Each decrypts to exactly one keyless option, at `correct_option` = the keyed slot, whose text is the final answer. Its three distractor keys are distinct and are exactly the keys of its stored `common_wrong`, each with a misconception stated. Its rubric ends with the reason criterion, and the ciphertext is at rest. No stored text carries a marker, no reference is deliberation, and no `mc_reason` draft filled its own `wrong_keys`.
- Letters: A×24, B×24, C×21, D×23.
- Cost: $0.025435 and $0.028831 (8 calls each). Smoke 1 passed and the oracles found 0 findings in both cycles.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q -p no:cacheprovider          → 412 passed
cd backend && venv/bin/python -m pytest tests/test_agent_output_schemas.py tests/test_e2e_function_handlers.py -q -p no:cacheprovider → all passed
grep -c "misconception_key" backend/learning/checks.py                                                    → ≥ 1
grep -c "wrong_key: str" backend/learning/checks.py                                                       → 1 (the stored Option; OptionDraft has none)
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py                           → every evaluator at its baseline (McOptionsValid 1.000, McReasonValid 0.944, DraftValid 0.981, FinalAnswerValid 1.000, WrongReasonCount 1.000, McCorrectNotLongest 0.500)
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -p no:cacheprovider      → 17 passed, 1 skipped
```

## Open questions for the series owner

- A37 known limit (1): a call that leaves "Final answer:" off every free and teachback reference loses those drafts. A34 gives the free and teachback formats no second statement of the answer to repair against. Taken option: the prompt's closing-sentence lines, measured above; a structural fix (for example code closing every reference from the `final_answer` field) would change A34 and is the coordinator's call.
- Should a derived key reuse a key the course already uses for the same misconception text, so that PKG-10's rollup does not split it? That would need a read across items at write time. Taken option: derive from the text alone, deterministically.
- A same-category `mc_reason` question ("which of these is a fallacy?" against three appeals) has distractors that genuinely share one misconception. The decision rejects identical misconception texts, and this is what left ENG150's Logical Fallacies at 1 item in 1 of 16 live passes. Should such an item be stored with its distractors under one key (PKG-10 would then read one misconception for three options)? Taken option: reject, as decided.

## Post-hoc changes

(Appended by later packages that modified this lane's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
