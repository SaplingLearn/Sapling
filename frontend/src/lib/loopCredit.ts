// What a correct learning-loop check answer earned (#866 K07): the weight the
// backend journaled for it (services/loop/checkpoint.py::_credited, through
// learning/evidence.py::evidence_weight), never a rule rebuilt on the client.

/** `full`, `partial` (a reduced weight: see LoopCreditReason) or `none` (a
 *  worked example or a shown answer before it, H4-H6). */
export type LoopCredit = 'full' | 'partial' | 'none';

/** learning/evidence.py::weight_factors: what reduced a partial credit, in the
 *  order the weight multiplies them. `hint` = help H1-H3; `recheck` = a
 *  same-session re-check (the concept's answer was shown, or this question was
 *  already checked, this session); `low_confidence` = the grader's low
 *  confidence; `multi_concept` = a multi-concept item's apex. */
export type LoopCreditReason = 'hint' | 'recheck' | 'low_confidence' | 'multi_concept';

/** The check-answer response fields (present on a correct verdict only;
 *  `credit_reasons` only on a partial one). */
export interface LoopCreditFields {
  credit?: LoopCredit;
  credit_reasons?: LoopCreditReason[];
}
