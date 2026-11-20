// Learning loop (PKG-13): the pure UI state LoopLearn keeps about the loop.
// Every change comes from the SERVER — a route response, a stream event, a
// listed session — so this reducer never advances the phase on its own (spec
// §9: the ZPD gates are server-side). No React import.
import type { LoopBudgetPause, LoopCheckItem, LoopLearnerState, LoopPhase, LoopTurnResult } from "@/lib/api";

export interface LoopUiState {
  phase: LoopPhase;
  /** The current check item's pose (A27); null when no item is current. Never
   *  promptless: a `check` event for an item whose pose is not known yet leaves
   *  it null until done.check (or GET /status) brings the pose. */
  item: LoopCheckItem | null;
  learnerState: Record<string, LoopLearnerState>;
  /** The node the last `learner_state` event named — the turn's concept (the
   *  pose itself never names its node). */
  focusNodeId: string | null;
  /** The tutor hard level (A20/A26): chat paused; practice keeps working. */
  budgetPause: LoopBudgetPause | null;
}

export type LoopUiEvent =
  | { type: "phase"; phase: string }
  | { type: "check"; item: LoopCheckItem | null }
  | { type: "learner_state"; state: LoopLearnerState }
  | { type: "budget"; level: string; resetAt: string | null; sessionCapped?: boolean; aiLimit?: boolean }
  | { type: "budget_clear" }
  | { type: "reset" };

const UI_PHASES: readonly LoopPhase[] = ["probe", "plan", "teach", "check", "feedback", "close"];

/** A turn's phase as the UI shows it: a hint turn runs while the item is
 *  current, so the screen stays in `check`. Unknown strings → null. */
export function uiPhaseOf(phase: string): LoopPhase | null {
  if (phase === "hint") return "check";
  return (UI_PHASES as readonly string[]).includes(phase) ? (phase as LoopPhase) : null;
}

/** K06: an ungraded check is posed — the check card is the one way to answer
 *  it (a chat turn now only re-poses it, ungraded and with no reply). */
export const checkIsOpen = (state: LoopUiState): boolean => state.item !== null && state.phase === "check";

export function initialLoopState(): LoopUiState {
  return {
    phase: "probe",
    item: null,
    learnerState: {},
    focusNodeId: null,
    budgetPause: null,
  };
}

/** What a served hint turn (POST /action) changes here: its phase, its learner
 *  state (#866 K33: the focus concept) and a hard budget notice. */
export function hintTurnEvents(t: LoopTurnResult): LoopUiEvent[] {
  const events: LoopUiEvent[] = t.phase ? [{ type: "phase", phase: t.phase }] : [];
  for (const state of t.learner_state ?? []) events.push({ type: "learner_state", state });
  if (t.budget?.level === "hard") {
    events.push({ type: "budget", level: "hard", resetAt: t.budget.reset_at, sessionCapped: t.budget.session_capped });
  }
  return events;
}

/** A turn's learner state: it focuses its concept and, when measured, records
 *  the concept's skill. #866 K52: an unmeasured one (`measured: false`, the
 *  prior) moves the focus only — the prior is never shown as a skill. */
function withLearnerState(state: LoopUiState, ls: LoopLearnerState): LoopUiState {
  if (ls.measured === false) return { ...state, focusNodeId: ls.node_id };
  return { ...state, learnerState: { ...state.learnerState, [ls.node_id]: ls }, focusNodeId: ls.node_id };
}

export function reduceLoopEvent(state: LoopUiState, ev: LoopUiEvent): LoopUiState {
  switch (ev.type) {
    case "phase": {
      const phase = uiPhaseOf(ev.phase);
      return phase && phase !== state.phase ? { ...state, phase } : state;
    }
    case "check": {
      if (ev.item === null) return state.item === null ? state : { ...state, item: null };
      // The stream's `check` event carries only hash/format/difficulty; keep the
      // pose already known for the same item instead of blanking its prompt.
      const same = state.item?.question_hash === ev.item.question_hash ? state.item : null;
      const prompt = ev.item.prompt ?? same?.prompt;
      // No pose known for this item: nothing to render yet (and a different
      // hash means the server moved on — the old pose is stale).
      if (!prompt) return state.item === null ? state : { ...state, item: null };
      return {
        ...state,
        item: { ...ev.item, prompt, options: ev.item.options ?? same?.options ?? null },
      };
    }
    case "learner_state":
      return withLearnerState(state, ev.state);
    case "budget":
      // soft = the invisible downgrade (spec §3.5): nothing renders
      if (ev.level !== "hard") return state;
      return { ...state, budgetPause: { resetAt: ev.resetAt, sessionCapped: ev.sessionCapped === true, ...(ev.aiLimit ? { aiLimit: true } : {}) } };
    case "budget_clear":
      return state.budgetPause ? { ...state, budgetPause: null } : state;
    case "reset":
      // A daily pause belongs to the student, not the session; a session cap
      // does not follow the student into a new session (A39).
      return {
        ...initialLoopState(),
        budgetPause: state.budgetPause && !state.budgetPause.sessionCapped ? state.budgetPause : null,
      };
  }
}
