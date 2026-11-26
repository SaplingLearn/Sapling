// The learning loop's budget pauses (spec §3.5 hard level, §13 A20/A26/A39),
// read off a response or a failed request. Re-exported from lib/api.ts, which
// every caller imports them from.
import { ApiError } from '@/lib/apiError';

/** `budget` stream event / JSON `budget` key (06b j): level + reset + scope + session_capped. */
export interface LoopBudgetNotice {
  level: 'soft' | 'hard' | string;
  reset_at: string | null;
  scope: string | null;
  session_capped: boolean;
  /** #866 K35: the hard level holds checks on novice-band concepts too. */
  pause_novice?: boolean;
}

/** A pause the screen shows. `aiLimit` (#866 K11): the per-student daily limit on
 *  EVERY AI feature (backend services/llm_budget.py), not the loop's own tutor
 *  budget — so checks pause with the tutor; present only when true. */
/** `scope`: the cap that paused (the 429's binding scope, #866 K18), when the body names one;
 *  `pauseNovice`: the hard level holds checks on novice-band concepts too (#866 K35). */
export interface LoopBudgetPause { resetAt: string | null; sessionCapped: boolean; aiLimit?: boolean; scope?: string; pauseNovice?: boolean }

export function loopBudgetNoticeOf(data: unknown): LoopBudgetNotice {
  const d = (data ?? {}) as Record<string, unknown>;
  return {
    level: String(d.level ?? ''),
    reset_at: typeof d.reset_at === 'string' ? d.reset_at : null,
    scope: typeof d.scope === 'string' ? d.scope : null,
    session_capped: d.session_capped === true, // A39: a missing field reads as false
    ...(d.pause_novice === true ? { pause_novice: true } : {}), // #866 K35
  };
}

/** A20/A26/A39: the 429 body `{"detail": "ai budget reached", "reset_at", "scope",
 *  "session_capped"}` from a JSON route (ApiError.body) or a stream route (sse.ts:
 *  Error.message = raw body, `.status` set). Any other error → null. */
export const budgetPauseOf = (err: unknown): LoopBudgetPause | null => {
  const status = (err as { status?: number } | null)?.status;
  if (status !== 429) return null;
  let body: unknown = err instanceof ApiError ? err.body : undefined;
  if (body === undefined && err instanceof Error) {
    try { body = JSON.parse(err.message); } catch { return null; }
  }
  const b = body as { detail?: unknown; reset_at?: unknown; session_capped?: unknown; scope?: unknown; pause_novice?: unknown } | null;
  if (!b || b.detail !== 'ai budget reached') return null;
  return {
    resetAt: typeof b.reset_at === 'string' ? b.reset_at : null, sessionCapped: b.session_capped === true,
    ...(typeof b.scope === 'string' ? { scope: b.scope } : {}), ...(b.pause_novice === true ? { pauseNovice: true } : {}),
  };
};

/** The backend's code for a run the per-student daily AI limit refused (services/llm_budget.py::ERROR_CODE). */
export const LLM_BUDGET_EXCEEDED = 'LLM_BUDGET_EXCEEDED';

/** #866 K11: the daily AI limit, as the pause it is, from a stream's terminal
 *  `error` event (`ChatStreamError.code` / `.resetAt`) or a JSON route's 429
 *  envelope (`error.code` / `error.reset_at`); null for anything else. */
export const aiLimitOf = (err: unknown): LoopBudgetPause | null => {
  const e = (err ?? {}) as { code?: unknown; resetAt?: unknown; body?: unknown };
  const coded = (e.body as { error?: { code?: unknown; reset_at?: unknown } } | undefined)?.error;
  const code = e.code ?? coded?.code;
  if (code !== LLM_BUDGET_EXCEEDED) return null;
  const resetAt = e.resetAt ?? coded?.reset_at;
  return { resetAt: typeof resetAt === 'string' ? resetAt : null, sessionCapped: false, aiLimit: true };
};

/** Tutor V2's pause behind a failed request (#866 K11): the loop's own tutor
 *  budget (`budgetPauseOf`), else the daily AI limit (`aiLimitOf`). */
export const loopPauseOf = (err: unknown): LoopBudgetPause | null => budgetPauseOf(err) ?? aiLimitOf(err);
