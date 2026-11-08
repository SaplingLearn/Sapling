/**
 * When a passive feedback prompt may open.
 *
 * ShellFrame mounts two feedback prompts: FeedbackFlow (the "What's clicking?"
 * pulse, 45s after the shell mounts) and SessionFeedbackGlobal ("How was that
 * session?", when the student leaves /learn after a session's wrap-up). A live
 * walkthrough found both within ~15 minutes of a first session, the pulse
 * landing on top of the check-in. Every rule that decides whether one opens
 * lives here:
 *
 * 1. One on screen at a time: the slot (#762).
 * 2. Never mid-learning. A learning surface holds prompts while one of its
 *    activities is in progress (`useFeedbackHold`: an open loop session from
 *    check-in to feedback, an open check card, a streaming tutor turn, a review
 *    item, a retention check), and a crisis-support card holds them while it is
 *    on screen, on any surface (components/safety/CrisisSupportCard.tsx). A
 *    prompt that comes due meanwhile waits for the release
 *    (`whenFeedbackFree`): the wrap-up, or leaving the surface.
 * 3. At most one per learning session. The ledger keeps the ids of sessions
 *    that already had a prompt. The pulse counts against the session the
 *    student is in or has just wrapped up (`noteLearningSession`); the session
 *    prompt counts against the session it asks about.
 * 4. Cooldowns. The pulse's 3 days and the session prompt's 2 days (both older
 *    than this module), plus a 24h gap between ANY two prompts: the per-kind
 *    cooldowns never looked at each other, so a pulse on the dashboard still
 *    let the session prompt follow minutes later. A day is the unit a student
 *    studies in, so this means at most one ask per study day while the per-kind
 *    cooldowns still let each kind run every 2-3 days.
 *
 * A prompt is recorded when it OPENS, so a dismissal (Not now, Skip, the close
 * button, the backdrop, even closing the tab) counts as shown.
 *
 * Storage is per-browser: localStorage for the pacing record, sessionStorage
 * for the ended-session marker, every access in try/catch. The `feedback`
 * table stores submissions only, not dismissals, so cross-device pacing would
 * need a new server write per prompt shown; this is about not nagging the
 * person at this screen. Storage that cannot be read is treated as "recently
 * asked": no prompt beats a prompt on every page load.
 *
 * Module state (slot, holds, current session) is fine: both prompts live in
 * the one app shell, and the learning surfaces render inside it.
 */
import { useEffect } from "react";

export type FeedbackOwner = "global" | "session";

// ── 1. The slot: one prompt on screen ─────────────────────────────────────

let holder: FeedbackOwner | null = null;

/** Take the slot. True when it was free or already ours. */
export function tryClaimFeedbackSlot(owner: FeedbackOwner): boolean {
  if (holder !== null && holder !== owner) return false;
  holder = owner;
  return true;
}

/** Give the slot back. A no-op for an owner that doesn't hold it. */
export function releaseFeedbackSlot(owner: FeedbackOwner): void {
  if (holder === owner) holder = null;
}

// ── 2. Holds: never mid-learning ──────────────────────────────────────────

const holds = new Set<symbol>();
const listeners = new Set<() => void>();

/** Hold every feedback prompt until the returned release is called. */
export function holdFeedback(): () => void {
  const token = Symbol("feedback-hold");
  holds.add(token);
  return () => {
    if (!holds.delete(token)) return;
    for (const listener of [...listeners]) {
      if (holds.size > 0) return; // still (or again) held: the rest keep waiting
      if (listeners.has(listener)) listener();
    }
  };
}

export function feedbackHeld(): boolean {
  return holds.size > 0;
}

/** Hold feedback prompts while `active` (released when it turns false or the
 *  component unmounts). The caller derives `active` from its own state. */
export function useFeedbackHold(active: boolean): void {
  useEffect(() => (active ? holdFeedback() : undefined), [active]);
}

/** Run `open` once no learning activity holds prompts: now if none does,
 *  otherwise at the release. Returns a cancel for a wait still pending. */
export function whenFeedbackFree(open: () => void): () => void {
  if (!feedbackHeld()) {
    open();
    return () => {};
  }
  const listener = () => {
    listeners.delete(listener);
    open();
  };
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

// ── 3. The learning session a prompt counts against ───────────────────────

let learningSession: string | null = null;

/** The session the student is in (or just wrapped up). Kept after they leave
 *  /learn, so a prompt that waited out that session still counts against it. */
export function noteLearningSession(sessionId: string): void {
  learningSession = sessionId;
}

export function currentLearningSession(): string | null {
  return learningSession;
}

/** The session the student last wrapped up: what "How was that session?" asks
 *  about when they leave /learn. Written at the wrap-up, dropped when they move
 *  into another session, consumed when they leave. */
export const ENDED_SESSION_KEY = "sapling_last_session_context";

export interface EndedSession {
  sessionId?: string;
  topic?: string;
}

export function rememberEndedSession(ended: EndedSession): void {
  try {
    sessionStorage.setItem(ENDED_SESSION_KEY, JSON.stringify(ended));
  } catch {}
}

export function forgetEndedSession(): void {
  try {
    sessionStorage.removeItem(ENDED_SESSION_KEY);
  } catch {}
}

/** Read and remove the ended session: left in place it would label a later
 *  prompt with a session from long before (#762). */
export function takeEndedSession(): EndedSession | null {
  try {
    const raw = sessionStorage.getItem(ENDED_SESSION_KEY);
    sessionStorage.removeItem(ENDED_SESSION_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? (parsed as EndedSession) : null;
  } catch {
    return null;
  }
}

// ── 4. The pacing record ──────────────────────────────────────────────────

const DAY_MS = 24 * 60 * 60 * 1000;
export const PULSE_COOLDOWN_MS = 3 * DAY_MS;
export const SESSION_PROMPT_COOLDOWN_MS = 2 * DAY_MS;
export const ANY_PROMPT_GAP_MS = DAY_MS;

/** When each kind last opened (ms since epoch). The keys predate this module. */
export const LAST_PROMPT_KEY: Record<FeedbackOwner, string> = {
  global: "sapling_last_feedback",
  session: "sapling_last_session_feedback",
};
/** The most recent learning sessions that had a prompt (JSON string[]). */
export const PROMPTED_SESSIONS_KEY = "sapling_feedback_sessions";
const PROMPTED_SESSIONS_LIMIT = 20;

const COOLDOWN_MS: Record<FeedbackOwner, number> = {
  global: PULSE_COOLDOWN_MS,
  session: SESSION_PROMPT_COOLDOWN_MS,
};

function readTime(key: string): number {
  const value = Number(localStorage.getItem(key) ?? "0");
  return Number.isFinite(value) ? value : 0;
}

function readPromptedSessions(): string[] {
  const parsed: unknown = JSON.parse(localStorage.getItem(PROMPTED_SESSIONS_KEY) ?? "[]");
  return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === "string") : [];
}

const within = (last: number, window: number, now: number) => last > 0 && now - last <= window;

/** May a prompt of `kind` open now, counted against `sessionId` (null: none)?
 *  Holds and the slot are checked separately. */
export function mayPrompt(kind: FeedbackOwner, sessionId: string | null, now = Date.now()): boolean {
  try {
    if (within(readTime(LAST_PROMPT_KEY[kind]), COOLDOWN_MS[kind], now)) return false;
    const lastAny = Math.max(readTime(LAST_PROMPT_KEY.global), readTime(LAST_PROMPT_KEY.session));
    if (within(lastAny, ANY_PROMPT_GAP_MS, now)) return false;
    return !sessionId || !readPromptedSessions().includes(sessionId);
  } catch {
    return false;
  }
}

/** Record that a prompt of `kind` opened, counted against `sessionId`. */
export function recordPrompt(kind: FeedbackOwner, sessionId: string | null, now = Date.now()): void {
  try {
    localStorage.setItem(LAST_PROMPT_KEY[kind], String(now));
    if (!sessionId) return;
    let ids: string[] = [];
    try {
      ids = readPromptedSessions();
    } catch {}
    const next = [sessionId, ...ids.filter((id) => id !== sessionId)].slice(0, PROMPTED_SESSIONS_LIMIT);
    localStorage.setItem(PROMPTED_SESSIONS_KEY, JSON.stringify(next));
  } catch {}
}

export function __resetFeedbackPacingForTests(): void {
  holder = null;
  holds.clear();
  listeners.clear();
  learningSession = null;
}
