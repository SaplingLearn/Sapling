// Learning loop (PKG-13): the pure UI state LoopLearn keeps about the loop.
// Every change comes from the SERVER — a route response, a stream event, a
// listed session — so this reducer never advances the phase on its own (spec
// §9: the ZPD gates are server-side). No React import.
import type { LoopBudgetPause, LoopCheckItem, LoopLearnerState, LoopPhase } from "@/lib/api";

export interface LoopUiState {
  phase: LoopPhase;
  /** The current check item's pose (A27); null when no item is current. */
  item: LoopCheckItem | null;
  /** The rung a `hint_offer` event offered (novice band only, spec §3.3). */
  hintOffer: number | null;
  learnerState: Record<string, LoopLearnerState>;
  /** The node the last `learner_state` event named — the turn's concept (the
   *  pose itself never names its node). */
  focusNodeId: string | null;
  leakRedacted: boolean;
  /** The tutor hard level (A20/A26): chat paused; practice keeps working. */
  budgetPause: LoopBudgetPause | null;
}

export type LoopUiEvent =
  | { type: "phase"; phase: string }
  | { type: "check"; item: LoopCheckItem | null }
  | { type: "hint_offer"; rung: number }
  | { type: "learner_state"; state: LoopLearnerState }
  | { type: "done"; leakRedacted: boolean }
  | { type: "budget"; level: string; resetAt: string | null; sessionCapped?: boolean }
  | { type: "budget_clear" }
  | { type: "reset" };

const UI_PHASES: readonly LoopPhase[] = ["probe", "plan", "teach", "check", "feedback", "close"];

/** A turn's phase as the UI shows it: a hint turn runs while the item is
 *  current, so the screen stays in `check`. Unknown strings → null. */
export function uiPhaseOf(phase: string): LoopPhase | null {
  if (phase === "hint") return "check";
  return (UI_PHASES as readonly string[]).includes(phase) ? (phase as LoopPhase) : null;
}

export function initialLoopState(): LoopUiState {
  return {
    phase: "probe",
    item: null,
    hintOffer: null,
    learnerState: {},
    focusNodeId: null,
    leakRedacted: false,
    budgetPause: null,
  };
}

export function reduceLoopEvent(state: LoopUiState, ev: LoopUiEvent): LoopUiState {
  switch (ev.type) {
    case "phase": {
      const phase = uiPhaseOf(ev.phase);
      return phase && phase !== state.phase ? { ...state, phase } : state;
    }
    case "check": {
      if (ev.item === null) return { ...state, item: null, hintOffer: null };
      // The stream's `check` event carries only hash/format/difficulty; keep the
      // pose already known for the same item instead of blanking its prompt.
      const same = state.item?.question_hash === ev.item.question_hash ? state.item : null;
      return {
        ...state,
        item: {
          ...ev.item,
          prompt: ev.item.prompt ?? same?.prompt,
          options: ev.item.options ?? same?.options ?? null,
        },
        hintOffer: same ? state.hintOffer : null,
      };
    }
    case "hint_offer":
      return { ...state, hintOffer: Number.isFinite(ev.rung) ? ev.rung : null };
    case "learner_state":
      return {
        ...state,
        learnerState: { ...state.learnerState, [ev.state.node_id]: ev.state },
        focusNodeId: ev.state.node_id,
      };
    case "done":
      return { ...state, leakRedacted: ev.leakRedacted };
    case "budget":
      // soft = the invisible downgrade (spec §3.5): nothing renders
      if (ev.level !== "hard") return state;
      return { ...state, budgetPause: { resetAt: ev.resetAt, sessionCapped: ev.sessionCapped === true } };
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
