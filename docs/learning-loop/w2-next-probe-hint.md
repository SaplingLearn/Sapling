# W2.4 Low-trust next-probe hint

Optional routing hint from reason-before-submit prose: may only
choose **which eligible check to pose next**. Never evidence. Never mastery.

## Mechanism

| Layer | Role |
|---|---|
| `learning/next_probe_hint.py::prefer` | Pure: plaintext + `(question_hash, searchable_text)` candidates → preferred hash or `None` (keyword overlap; sealed ciphertext rejected) |
| `learning/check_reason.py::open` / `latest_plaintext` | W2.4b: open nested `reasoning_encrypted` under the session bind; pick the most recently graded step, then its reasoning. That step has none → `None` (no hint): prose on an older step never speaks for a newer grade. An ungraded step is never picked |
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
| Eligible pool only | Caller supplies already-filtered candidates (`select_item`'s pool: not excluded, `is_servable`); hint cannot widen the set. `_activate_next_item` is driven with the flag on in `test_learning_next_probe_hint` |
| Decrypt only when flag on | Gate returns before `latest_plaintext`; wrong-session bind opens as `None` |

## Non-goals

- Self-explain / reasoning → mastery (plan W / W2.6)
- Self-explain table reply decrypt into the same hint (reason-before-submit path only)
