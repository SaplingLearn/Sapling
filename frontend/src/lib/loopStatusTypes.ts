/**
 * GET /api/learn/loop/status's wire type (backend/services/loop/sessions.py
 * `status`). lib/api.ts's getLoopSessionStatus reads it and re-exports it, so
 * callers import it from "@/lib/api" as before. Kept in its own file so the
 * resume contract can grow without pushing lib/api.ts past its size ceiling
 * (max-lines-baseline.json).
 */
import type {
  LoopCheckItem, LoopLearningScope, LoopPendingGrade, LoopPlanMoved, LoopPrequestion, LoopSelfExplain,
} from '@/lib/api';

/** GET /status for one session (read-only): where it stands and, while an item
 *  takes answers, its pose. The resume restore and the post-submission reconcile. */
export interface LoopSessionStatus extends LoopLearningScope, LoopPlanMoved {
  active: boolean;
  session_id: string;
  /** PKG-08's phase: probe | plan | teach | close. */
  loop_phase: string;
  /** PKG-07's teach refinement: teach | check | feedback. */
  phase: string;
  active_question_hash?: string | null;
  check?: LoopCheckItem | null;
  pending_grade?: LoopPendingGrade | null;
  /** Spec §13 A138: the open segment-opening guess (absent when none). */
  prequestion?: LoopPrequestion | null;
  /** Spec §13 A139: the open self-explanation prompt (absent when none). */
  self_explain?: LoopSelfExplain | null;
  /** W3.2: the concepts graded (and measured) this session — ids only, absent
   *  when none — so the map's practiced outlines survive a reload. */
  practiced_node_ids?: string[];
  // approved_plan (LoopPlanMoved): the approved plan, in order, with its cursor
  // (absent before approval) — always, on /status
}
