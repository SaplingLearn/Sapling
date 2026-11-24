# W2.4 Low-trust next-probe hint

Optional routing hint from reason-before-submit / self-explain prose: may only
choose **which eligible check to pose next**. Never evidence. Never mastery.

## Mechanism

| Layer | Role |
|---|---|
| `learning/next_probe_hint.py::prefer` | Pure: plaintext + `(question_hash, searchable_text)` candidates → preferred hash or `None` (keyword overlap; sealed ciphertext rejected) |
| `learning/check_reason.py::open` / `latest_plaintext` | W2.4b: open nested `reasoning_encrypted` under the session bind; pick the most recently graded step |
| `services/loop/next_probe_hint.py::preferred_next_question_hash` | Flag gate: off → `None` immediately (no decrypt); on → `latest_plaintext` then `prefer` |
| `services/loop/practice.py::_activate_next_item` | Single call site among the eligible pool; threads `session_id` + state; when the hint returns a still-eligible hash it wins that format pass |

## Flag

- Key: `next_probe_hint` (`off` \| `on`, default **off**, server-only)
- Loop-gated: in `learning/gate.py::LOOP_FLAGS` (requires `learning_loop`)
- Kill switch: `SAPLING_FLAG_NEXT_PROBE_HINT=off`

## Hard invariants

| Rule | How |
|---|---|
| Never `apply_graph_update` / never bump `p_known` | Pure + gate modules ban mastery symbols; `test_inv_32_*` + `test_learning_next_probe_hint` |
| No LLM | Deterministic token overlap only |
| Eligible pool only | Caller supplies already-filtered candidates; hint cannot widen the set |
| Decrypt only when flag on | Gate returns before `latest_plaintext`; wrong-session bind opens as `None` |

## Non-goals

- Self-explain / reasoning → mastery (plan W / W2.6)
- Self-explain table reply decrypt into the same hint (reason-before-submit path only for W2.4b)
