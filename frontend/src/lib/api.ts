import type {
  RoomMessageRow, RoomOverviewData,
  UserProfile, UserSettings, UserRole, UserAchievement, Achievement,
  UserCosmetic, CosmeticType, Role, Cosmetic, RarityTier, AchievementCategory,
  GradebookSummary, GradebookCourse, GradeCategory, GradedAssignment, LetterScaleTier,
  GpaReport,
  ExtractedSyllabusCategory,
  AllowlistEmail, EmailStatus, EmailAudience, EmailAudienceKey, EmailBroadcast, EmailBroadcastPreview,
  AchievementTrigger, AdminAuditEntry, AnalyticsOverview, PaginatedUsers,
  AdminAccountsMeta, AdminSeedAccountResult, AdminWipeAccountResult,
  AdminCopyAccountResult, AccountCopyDirection, AdminAccountSummary, AdminCopyPreview,
  Note, LinkedConcept,
  GraphUpdate, MasteryChange,
  AnalyticsBucket, LlmCostGroupBy,
  UsageSummaryData, UsageByUserData, LlmCostData, ErrorsPageData, LearningLoopKpisData,
  PublicRoom,
  GamificationMe, LeaderboardRow, ActivityData, Friend,
} from '@/lib/types';
import { statusOf } from '@/lib/errorMessage';
import type { WithCrisisSupport } from '@/lib/crisisSupport';
import type { AdminFlag, FlagRule } from '@/lib/adminFlags';
import type {
  ReviewAnswerBody, ReviewAnswerResponse, ReviewNextResponse, ReviewSummaryResponse,
} from '@/lib/reviewTypes';
import { createStreamPacer, type StreamPacer } from '@/lib/streamPacer';
import { REAUTH_REQUIRED, isReauthRequired, notifyReauthRequired } from '@/lib/reauth';
import { ApiError, apiErrorOf, errorFieldsFrom, parseErrorBody } from '@/lib/apiError';
import { askOriginFields, quotedQuestionFields, type AskOrigin, type QuizAskOrigin } from '@/lib/askOrigin';
import { loopBudgetNoticeOf, type LoopBudgetNotice } from '@/lib/loopBudget';
import type { LoopCreditFields } from '@/lib/loopCredit';
import type {
  AdminCheckItemQueue, AdminAuditSample, AdminItemStatsReport, CheckItemAuditVerdict, CheckItemKeyStatus,
} from '@/lib/adminCheckItemTypes';

export const API_URL = '';

// The error every failed response is thrown as lives in lib/apiError.ts, shared
// with the SSE client; re-exported here, where callers have always imported it.
export { ApiError, type ApiErrorFields } from '@/lib/apiError';
export { aiLimitOf, budgetPauseOf, loopPauseOf, type LoopBudgetNotice, type LoopBudgetPause } from '@/lib/loopBudget';

// ── Global 401 (#756) ─────────────────────────────────────────────────────────
// A 401 from any session-authenticated call means the server no longer honours
// this browser's session (expired, signed out elsewhere, account deleted). Until
// #756 nothing noticed until the next profile refetch, so a dead session kept
// its identity — and its analytics identify — in the tab. fetchJSON now tells
// the listeners (UserContext tears the identity down); it still throws, so each
// caller's own error handling is unchanged.

type SessionExpiredListener = () => void;
const sessionExpiredListeners = new Set<SessionExpiredListener>();

/** Subscribe to "a session-authenticated call answered 401". Returns the
 * unsubscribe. */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener);
  return () => {
    sessionExpiredListeners.delete(listener);
  };
}

/** The /pending endpoints authenticate with the pending token in their body,
 * not the session cookie: their 401 says nothing about a session. */
function isSessionAuthenticated(path: string): boolean {
  return !path.startsWith('/api/auth/pending/');
}

function notifySessionExpired(): void {
  for (const listener of [...sessionExpiredListeners]) {
    try {
      listener();
    } catch (err) {
      console.error('[api] session-expired listener failed', err);
    }
  }
}

// Admin step-up 401s (`reauth_required`) go to lib/reauth.ts, not to the
// session-expired listeners above: the session is alive, it is just too old
// for an admin route.

/**
 * The one sanctioned request helper: same-origin `API_URL` so the `sapling_session`
 * cookie rides along (a cross-origin `NEXT_PUBLIC_API_URL` fetch drops it — the
 * 2026-06-30 onboarding-loop bug). Exported since #537 so feature-scoped clients
 * (`lib/quiz/api.ts`) can be thin wrappers over it instead of growing this file.
 */
export async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    const body = parseErrorBody(err);
    if (res.status === 401 && isReauthRequired(body)) {
      notifyReauthRequired();
      throw new ApiError(err, res.status, { ...errorFieldsFrom(body), code: REAUTH_REQUIRED, body });
    }
    if (res.status === 401 && isSessionAuthenticated(path)) notifySessionExpired();
    throw apiErrorOf(res, err);
  }
  return res.json();
}

// Newsletter / beta list
//
// Backed by backend/routes/newsletter.py, which upserts on `email` — so a
// repeat signup is a no-op rather than an error, and the caller can treat
// success as "you're on the list" regardless of whether it was already there.
export const subscribeToNewsletter = (email: string) =>
  fetchJSON<{ ok: boolean }>('/api/newsletter/subscribe', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

// Auth
export interface MeResponse {
  user_id: string;
  is_approved: boolean;
  onboarding_completed: boolean;
  username: string | null;
  name: string;
  avatar_url: string;
  roles: { role: Role; granted_at: string }[];
  equipped_cosmetics: Record<string, unknown>;
  is_admin: boolean;
}

// Cookie-authenticated identity lookup (backend/routes/auth.py::get_me
// resolves the user via get_session_user_id, which reads the `sapling_session`
// cookie — the only session channel; no `user_id` param needed). UserContext's bootstrap falls back to this when localStorage has no
// `sapling_user` entry but the HttpOnly session cookie is still valid
// (#430); the OAuth callback (src/app/auth/callback/page.tsx) already reads
// this same endpoint off the same cookie, though via a bare `fetch` rather
// than this `fetchJSON` wrapper.
export const getMe = () => fetchJSON<MeResponse>('/api/auth/me');

/** #715: the signed-in account's local sample-data seed (backend
 * routes/auth.py::local_seed_status). 404 everywhere but a local backend. */
export type LocalSeedState = 'pending' | 'seeding' | 'ready' | 'failed';
export interface LocalSeedStatus {
  state: LocalSeedState;
  error?: string;
}
export const getLocalSeedStatus = () => fetchJSON<LocalSeedStatus>('/api/auth/local-seed');

/** An unapproved sign-in's waitlist standing, read with the short-lived
 * pending token the backend hands back instead of a session (see
 * `lib/pendingToken.ts`). Both calls 401 when the token is missing, invalid
 * or expired. */
export interface PendingStatus {
  email: string;
  on_waitlist: boolean;
  /** #757: an admin approved the address since this sign-in; a fresh
   * sign-in now gets in (the pending token itself is never a session). */
  approved?: boolean;
}
export const getPendingStatus = (token: string) =>
  fetchJSON<PendingStatus>('/api/auth/pending/status', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
/** Puts the pending account's sign-in email on the waitlist. Idempotent: an
 * account already on it answers the same `on_waitlist: true`. */
export const joinWaitlistFromPending = (token: string) =>
  fetchJSON<PendingStatus>('/api/auth/pending/join', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });

// Graph
export const getGraph = (userId: string, semester?: string) =>
  fetchJSON<{ nodes: any[]; edges: any[]; stats: any }>(
    `/api/graph/${userId}${semester ? `?semester=${encodeURIComponent(semester)}` : ""}`,
  );

export const getRecommendations = (userId: string, semester?: string) =>
  fetchJSON<{ recommendations: any[] }>(
    `/api/graph/${userId}/recommendations${semester ? `?semester=${encodeURIComponent(semester)}` : ""}`,
  );

export interface EnrolledCourse {
  enrollment_id: string;
  course_id: string;
  course_code: string;
  course_name: string;
  school: string;
  department: string;
  color: string | null;
  nickname: string | null;
  node_count: number;
  enrolled_at: string;
  // Human term label of the offering the enrollment hangs off, e.g. "Fall 2025".
  // The backend emits "" when the offering has no term joined — treat it as unknown,
  // never as a past term. This is the REPRESENTATIVE (most-recent) term of a course
  // that the backend collapses to one row per abstract course_id (#449); use `terms`
  // (below) for semester membership so a course enrolled across terms shows on each.
  term: string;
  // Every term label this abstract course is enrolled in (Fall 2025 + Spring 2026 for
  // a re-take), alongside `enrollment_ids`. Present since the get_courses collapse;
  // optional for backward-compat. Filter/scope by membership, not the singular `term`.
  terms?: string[];
  enrollment_ids?: string[];
}

export const getCourses = (userId: string) =>
  fetchJSON<{ courses: EnrolledCourse[] }>(`/api/graph/${userId}/courses`);

export const addCourse = (userId: string, courseId: string, color?: string, nickname?: string, term?: string) =>
  fetchJSON<{ course_id: string; already_existed: boolean; term?: string; error?: string }>(`/api/graph/${userId}/courses`, {
    method: 'POST',
    body: JSON.stringify({ course_id: courseId, ...(color ? { color } : {}), ...(nickname ? { nickname } : {}), ...(term ? { term } : {}) }),
  });

// Drops ONE term's enrollment (#766): `term` is the semester label to drop;
// omitted = the backend's current term. Other terms' gradebooks survive.
export const deleteCourse = (userId: string, courseId: string, term?: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/graph/${userId}/courses/${encodeURIComponent(courseId)}${term ? `?term=${encodeURIComponent(term)}` : ''}`,
    { method: 'DELETE' }
  );

export const updateCourseColor = (userId: string, courseId: string, color: string) =>
  fetchJSON<{ updated: boolean }>(
    `/api/graph/${userId}/courses/${encodeURIComponent(courseId)}/color`,
    { method: 'PATCH', body: JSON.stringify({ color }) }
  );

export const describeConcept = (userId: string, concept: string, courseLabel?: string) =>
  fetchJSON<{ description: string }>(
    `/api/graph/${userId}/concept-description`,
    { method: 'POST', body: JSON.stringify({ concept, course_label: courseLabel ?? null }) }
  );

// Manual add-concept (#330). Returns the CANONICAL node — freshly created,
// or the dedup survivor when the (case/whitespace-insensitive) name already
// existed on this course — plus the merge flag the UI toasts on.
export const addGraphNode = (
  userId: string,
  body: { concept_name: string; course_id: string; anchor_node_id?: string },
) =>
  fetchJSON<{
    node: {
      id: string; concept_name: string; course_id: string | null;
      mastery_score: number; mastery_tier: string;
    };
    already_existed: boolean;
  }>(`/api/graph/${userId}/nodes`, { method: 'POST', body: JSON.stringify(body) });

export const deleteGraphNode = (userId: string, nodeId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/graph/${userId}/nodes/${encodeURIComponent(nodeId)}`,
    { method: 'DELETE' }
  );

// Learn
export type ModelPref = 'smart' | 'fast';

// A session's origin (the quiz's and a study guide's Ask) and a chat turn's
// quoted quiz question: their types and request fields live in ./askOrigin.
export type { AskOrigin, GuideAskOrigin, QuizAskOrigin } from './askOrigin';

export const startSession = (
  userId: string,
  topic: string,
  mode: string,
  courseId?: string,
  useSharedContext = true,
  modelPref?: ModelPref,
  quizAsk?: AskOrigin,
  /** Send to tutor's note, when `topic` is still its title (see startSessionStream). */
  fromNoteId?: string,
) =>
  // A crisis-support answer carries `crisis_support` and no session (session_id null),
  // or, on a note's title, the session with `crisis_support_alongside`.
  fetchJSON<{ session_id: string; initial_message: string; graph_state: any } & WithCrisisSupport>('/api/learn/start-session', {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      topic,
      mode,
      use_shared_context: useSharedContext,
      course_id: courseId,
      ...(modelPref ? { model_pref: modelPref } : {}),
      ...askOriginFields(quizAsk),
      ...(fromNoteId ? { from_note_id: fromNoteId } : {}),
    }),
  });

// One id per student turn (#761/#762): lib/turnId.ts.
export { newTurnId } from '@/lib/turnId';

export const sendChat = (
  sessionId: string,
  userId: string,
  message: string,
  mode: string,
  useSharedContext = true,
  modelPref?: ModelPref,
  turnId?: string,
  /** The quiz question this message quotes (the Ask panel's first message, #866 K12). */
  quote?: QuizAskOrigin,
) =>
  fetchJSON<{ reply: string; graph_update: any; mastery_changes: any[]; replayed?: boolean } & WithCrisisSupport>('/api/learn/chat', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      message,
      mode,
      use_shared_context: useSharedContext,
      ...(modelPref ? { model_pref: modelPref } : {}),
      ...(turnId ? { turn_id: turnId } : {}),
      ...quotedQuestionFields(quote),
    }),
  });

export interface GraphDelta {
  nodes: Record<string, Array<Record<string, unknown>>>;
  mastery_changes: MasteryChange[];
}

export interface ChatResult extends WithCrisisSupport {
  reply: string;
  graph_update: GraphUpdate;
  mastery_changes: MasteryChange[];
  session_id?: string;
  graph_state?: any;
  /** Learning loop (PKG-07): `reply` is the leak-stripped text; true when the
   *  strip changed it. `reply` is always the text to render (spec §13 A46). */
  leak_redacted?: boolean;
  /** The server already had this `turn_id`'s reply and replayed it (#761). */
  replayed?: boolean;
}

interface StreamEvent {
  type: string;
  step: string;
  message: string;
  data?: Record<string, unknown> | null;
}

// Thrown from consumeChatStream on a mid-stream `error` event. Carries the
// backend's `request_id` (ADR 0009, stamped for Logfire correlation) as a
// property — not just baked into the message string — so a caller that
// wants to display or copy it (see DocumentUploadModal's "Reference:"
// pattern) doesn't have to re-parse the message text for it.
//
// `retryable` (#151a): the backend marks an error event retryable:false when
// graph/mastery tool writes already landed for the turn — re-running it (the
// ladder's JSON rung, or a transparent client retry) would re-apply those
// writes. Defaults to true so older backends / events without the field keep
// today's behavior.
export class ChatStreamError extends Error {
  requestId?: string;
  retryable: boolean;
  /** The `error` event's data, as an ApiError keeps its parsed body: a crisis
   *  card a streamed start's error carries rides here (`crisisSupportInError`,
   *  docs/safety/crisis-support.md; #866 K38), and so does a learning-loop turn
   *  the session refused mid-stream (`body.detail`, as an HTTP refusal reads).
   *  #866 K11: `code`/`resetAt` name the daily AI limit (lib/loopBudget.ts::aiLimitOf);
   *  `status` is the refusal's HTTP status when the event names one. */
  body?: Record<string, unknown> | null;
  code?: string;
  resetAt?: string;
  status?: number;
  constructor(message: string, requestId?: string, retryable = true, body?: Record<string, unknown> | null) {
    // Keep the full id here (correlation needs an exact match); a caller
    // that wants a short display form truncates it itself, same as
    // DocumentUploadModal's "Reference: {id.slice(0, 8)}…" pattern.
    super(requestId ? `${message} (ref: ${requestId})` : message);
    this.name = 'ChatStreamError';
    this.requestId = requestId;
    this.retryable = retryable;
    this.body = body;
  }
}

/**
 * The stream ladder's Rung-3 decision (#151a): may this failed stream turn
 * be transparently re-run through the non-streaming JSON route?
 *
 * false when:
 *  - the backend said so (`ChatStreamError.retryable === false` — tool
 *    writes landed; a re-run would double-apply them), or
 *  - the failure was an HTTP 413 (request too large / processing budget),
 *    422 (a request the server refuses, e.g. a message over its length cap)
 *    or 429 (rate limited: the JSON route spends the same per-student
 *    budget) — the JSON route fails the exact same way, so falling back
 *    just doubles the wait before the same error.
 *
 * Everything else (transport failures, idle timeouts, 5xx before any
 * token) stays retryable — the transparent JSON fallback is the whole
 * point of the ladder.
 */
/** Statuses the JSON route answers identically (see shouldFallBackToJson). */
const NO_JSON_FALLBACK = new Set([413, 422, 429]);

export function shouldFallBackToJson(err: unknown): boolean {
  if (err instanceof ChatStreamError) return err.retryable;
  const status = statusOf(err);
  return status === undefined || !NO_JSON_FALLBACK.has(status);
}

export interface StreamChatHandlers {
  onToken?: (delta: string) => void;
  onGraphUpdate?: (delta: GraphDelta) => void;
  /** The tutor started a tool call (`step` = the tool's wire name, e.g.
   *  `search_course_materials`) — what it is doing before any text. */
  onProgress?: (step: string) => void;
  signal?: AbortSignal;
  // Learning-loop stream events (PKG-07; spec §9). The legacy tutor streams
  // never send them, so the legacy callers pass none of these.
  /** A46: discard EVERY token of this reply streamed so far; the full current
   *  text follows as tokens, and `done.reply` is always the final text. */
  onRetract?: (reason: string) => void;
  /** The turn's phase (`teach` | `check` | `hint` | `feedback`). */
  onPhase?: (phase: string) => void;
  onCheck?: (item: LoopCheckItem) => void;
  onHintOffer?: (rung: number) => void;
  onLearnerState?: (state: LoopLearnerState) => void;
  onBudget?: (notice: LoopBudgetNotice) => void;
}

const STREAM_IDLE_MS = 45_000;

/** The `ChatStreamError` a mid-stream `error` event throws. */
function streamErrorOf(ev: StreamEvent): ChatStreamError {
  const requestId = typeof ev.data?.request_id === 'string' ? ev.data.request_id : undefined;
  // Only an explicit false clears the flag — absent/other values keep
  // the default-true contract with older backends.
  const retryable = ev.data?.retryable !== false;
  const err = new ChatStreamError(ev.message || 'The tutor was interrupted.', requestId, retryable, ev.data);
  const { code, reset_at: resetAt, status, detail } = ev.data ?? {};
  if (typeof code === 'string') err.code = code;
  if (typeof resetAt === 'string') err.resetAt = resetAt;
  if (typeof status === 'number' && typeof detail === 'string') err.status = status;
  return err;
}

type StreamEventHandler = (ev: StreamEvent, pacer: StreamPacer, h: StreamChatHandlers) => void;

/** Every event but `done` (which ends the turn): what each one does. An event
 *  type not listed here is ignored. */
const STREAM_EVENT_HANDLERS = new Map<string, StreamEventHandler>([
  ['token', (ev, pacer) => pacer.push(String(ev.data?.delta ?? ''))],
  ['graph_update', (ev, _p, h) => h.onGraphUpdate?.(ev.data as unknown as GraphDelta)],
  ['progress', (ev, _p, h) => h.onProgress?.(ev.step)],
  ['retract', (ev, pacer, h) => {
    // Learning loop (PKG-07): the server withdrew what it streamed (a
    // caught leak). Text still queued in the pacer must never reach the
    // screen after the retract, so it is DROPPED, not flushed.
    pacer.discard();
    h.onRetract?.(String(ev.data?.reason ?? ''));
  }],
  ['phase', (ev, _p, h) => h.onPhase?.(String(ev.data?.phase ?? ''))],
  ['check', (ev, _p, h) => h.onCheck?.(ev.data as unknown as LoopCheckItem)],
  ['hint_offer', (ev, _p, h) => h.onHintOffer?.(Number(ev.data?.rung))],
  ['learner_state', (ev, _p, h) => h.onLearnerState?.(ev.data as unknown as LoopLearnerState)],
  ['budget', (ev, _p, h) => h.onBudget?.(loopBudgetNoticeOf(ev.data))],
  ['error', ev => { throw streamErrorOf(ev); }],
]);

async function consumeChatStream(
  path: string,
  payload: Record<string, unknown>,
  handlers: StreamChatHandlers,
  /** #866 K10 (the loop routes): Stop pressed after `done` arrived — while the
   *  saved reply is still typing out — resolves with it instead of rejecting:
   *  the server sends `done` only after the turn is saved, so it is the result. */
  { keepDoneOnStop = false }: { keepDoneOnStop?: boolean } = {},
): Promise<ChatResult> {
  const { signal } = handlers;
  const { streamSSE } = await import('./sse');
  // Tokens go out through the pacer, so a reply the model sends in one burst
  // still types out (lib/streamPacer.ts). It is drained before `done`
  // resolves, because callers swap the streamed bubble for the final message
  // then. Any other exit flushes it first, so a caller's partial-text
  // handling (ADR 0020) sees every token that arrived.
  const pacer = createStreamPacer(delta => handlers.onToken?.(delta));
  let result: ChatResult | null = null;

  try {
    for await (const e of streamSSE<StreamEvent>(
      `${API_URL}${path}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
        signal,
      },
      { idleTimeoutMs: STREAM_IDLE_MS },
    )) {
      const ev = e.data;
      if (ev.type === 'done') result = ev.data as unknown as ChatResult;
      else STREAM_EVENT_HANDLERS.get(ev.type)?.(ev, pacer, handlers);
    }
  } catch (err) {
    pacer.flush();
    throw err;
  }

  if (!result) {
    pacer.flush();
    throw new Error('Chat stream ended without a done event.');
  }
  // Stop pressed while a burst is still being revealed ends the reveal now
  // and rejects like a mid-stream abort, so the caller's Stop path runs.
  const onAbort = () => pacer.flush();
  signal?.addEventListener('abort', onAbort, { once: true });
  try {
    await pacer.drain();
  } finally {
    signal?.removeEventListener('abort', onAbort);
  }
  if (!keepDoneOnStop) signal?.throwIfAborted();
  return result;
}

export const streamChat = (
  sessionId: string,
  userId: string,
  message: string,
  mode: string,
  useSharedContext = true,
  modelPref?: ModelPref,
  handlers: StreamChatHandlers = {},
  turnId?: string,
  /** The quiz question this message quotes (the Ask panel's first message, #866 K12). */
  quote?: QuizAskOrigin,
): Promise<ChatResult> => {
  return consumeChatStream(
    '/api/learn/chat/stream',
    {
      session_id: sessionId,
      user_id: userId,
      message,
      mode,
      use_shared_context: useSharedContext,
      ...(modelPref ? { model_pref: modelPref } : {}),
      ...(turnId ? { turn_id: turnId } : {}),
      ...quotedQuestionFields(quote),
    },
    handlers,
  );
};

export const startSessionStream = (
  userId: string,
  topic: string,
  mode: string,
  useSharedContext = true,
  courseId?: string,
  modelPref?: ModelPref,
  handlers: StreamChatHandlers = {},
  quizAsk?: AskOrigin,
  /**
   * Send to tutor's note (docs/safety/crisis-support.md), when `topic` is
   * still that note's title: the backend checks it against the student's own
   * note and, on a crisis match, starts the session with the card beside it
   * (`crisis_support_alongside`) instead of answering with the card alone.
   */
  fromNoteId?: string,
): Promise<ChatResult> => {
  return consumeChatStream(
    '/api/learn/start-session/stream',
    {
      user_id: userId,
      topic,
      mode,
      use_shared_context: useSharedContext,
      course_id: courseId,
      ...(modelPref ? { model_pref: modelPref } : {}),
      ...askOriginFields(quizAsk),
      ...(fromNoteId ? { from_note_id: fromNoteId } : {}),
    },
    handlers,
  );
};

/** PKG-14b (spec §11.2): the three always-empty lists are gone from the wire. */
export interface SessionSummaryData {
  concepts_covered: string[];
  time_spent_minutes: number;
}

export const endSession = (sessionId: string, userId: string) =>
  fetchJSON<{ summary: SessionSummaryData }>('/api/learn/end-session', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId }),
  });

export const learnAction = (
  sessionId: string,
  userId: string,
  actionType: 'hint' | 'confused' | 'skip',
  mode: string,
  useSharedContext = true,
  modelPref?: ModelPref,
) =>
  fetchJSON<{ reply: string; graph_update: any }>('/api/learn/action', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      action_type: actionType,
      mode,
      use_shared_context: useSharedContext,
      ...(modelPref ? { model_pref: modelPref } : {}),
    }),
  });

export interface Session {
  id: string;
  topic: string;
  mode: string;
  course_id: string | null;
  started_at: string;
  ended_at: string | null;
  message_count: number;
  is_active: boolean;
  /** A learning-loop session the student can still resume (no close yet). */
  loop_open?: boolean;
}

export const getSessions = (userId: string, limit = 10) =>
  fetchJSON<{ sessions: Session[] }>(`/api/learn/sessions/${userId}?limit=${limit}`);

export const switchMode = (sessionId: string, userId: string, newMode: string) =>
  fetchJSON<{ reply: string }>('/api/learn/mode-switch', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId, new_mode: newMode }),
  });

export const deleteSession = (sessionId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/learn/sessions/${sessionId}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' }
  );

export const renameSession = (sessionId: string, userId: string, topic: string) =>
  fetchJSON<{ updated: boolean; session: { id: string; topic: string } }>(
    `/api/learn/sessions/${sessionId}`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, topic }) }
  );

export const resumeSession = (sessionId: string) =>
  fetchJSON<{
    session: { id: string; user_id: string; topic: string; mode: string; course_id: string | null; started_at: string; ended_at: string | null; loop?: boolean };
    messages: { id: string; role: string; content: string; created_at: string }[];
  }>(`/api/learn/sessions/${sessionId}/resume`);

// Quiz lives in `lib/quiz/api.ts` — its own client over all six quiz endpoints.

// Calendar
export interface Assignment {
  id: string;
  user_id: string;
  title: string;
  due_date: string | null;
  assignment_type?: string;
  notes?: string;
  google_event_id?: string;
  course_id?: string;
  course_code?: string;
  course_name?: string;
}

export const getUpcomingAssignments = (userId: string) =>
  fetchJSON<{ assignments: Assignment[] }>(`/api/calendar/upcoming/${userId}`);

export const getAllAssignments = (userId: string) =>
  fetchJSON<{ assignments: Assignment[] }>(`/api/calendar/all/${userId}`);

export const extractSyllabus = (formData: FormData, userId?: string): Promise<any> => {
  if (userId) formData.set('user_id', userId);
  return fetch(`${API_URL}/api/calendar/extract`, { method: 'POST', body: formData, credentials: 'include' })
    .then(async r => { const data = await r.json(); if (!r.ok) throw new Error(String(data?.detail || `HTTP ${r.status}`)); return data; });
};

export const saveAssignments = (userId: string, assignments: Array<{ title: string; course_id?: string; due_date: string; assignment_type?: string | null; notes?: string | null }>) =>
  fetchJSON<{ saved_count: number }>('/api/calendar/save', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, assignments }),
  });

export const updateAssignment = (
  assignmentId: string,
  userId: string,
  patch: Partial<Pick<Assignment, 'title' | 'course_id' | 'due_date' | 'assignment_type' | 'notes'>>,
) =>
  fetchJSON<{ updated: boolean }>(`/api/calendar/assignments/${encodeURIComponent(assignmentId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, ...patch }),
  });

export const deleteAssignment = (assignmentId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/calendar/assignments/${encodeURIComponent(assignmentId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const getCalendarStatus = (userId: string) =>
  fetchJSON<{ connected: boolean; expires_at?: string }>(`/api/calendar/status/${userId}`);

export const disconnectCalendar = (userId: string) =>
  fetchJSON<{ disconnected: boolean }>(`/api/calendar/disconnect/${userId}`, { method: 'DELETE' });

export const syncCalendar = (userId: string) =>
  fetchJSON<{ synced_count: number }>('/api/calendar/sync', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export interface GoogleEvent {
  google_event_id: string;
  title: string;
  description?: string;
  start_date: string;
  end_date: string;
  start_datetime?: string | null;
  end_datetime?: string | null;
  all_day: boolean;
  html_link?: string;
  location?: string;
}

export const importGoogleEvents = (userId: string, daysAhead = 60) =>
  fetchJSON<{ events: GoogleEvent[]; count: number }>(
    `/api/calendar/import/${encodeURIComponent(userId)}?days_ahead=${daysAhead}`,
  );

/** The Google Calendar consent flow: a backend route that redirects to Google,
 * so open it with a full page load (`window.location`), never the in-app
 * router. `next` is where the callback lands after a successful connect; the
 * backend honours only its allowlist (/dashboard, /gradebook, /calendar). */
export const calendarAuthUrl = (userId: string, next?: string) =>
  `${API_URL}/api/calendar/auth-url?user_id=${encodeURIComponent(userId)}${
    next ? `&next=${encodeURIComponent(next)}` : ''
  }`;

export const exportToGoogleCalendar = (userId: string, assignmentIds: string[]) =>
  fetchJSON<{ exported_count: number; skipped_count: number }>('/api/calendar/export', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, assignment_ids: assignmentIds }),
  });

// Social
export const createRoom = (
  userId: string,
  roomName: string,
  opts?: { topic?: string; course?: string; is_public?: boolean },
) =>
  fetchJSON<{ room_id: string; invite_code: string }>('/api/social/rooms/create', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, room_name: roomName, ...opts }),
  });

// #405 public rooms: is_public=true rooms are listed (no invite_code in the
// payload, by construction) and joinable without an invite.
export const listPublicRooms = (userId: string) =>
  fetchJSON<{ rooms: PublicRoom[] }>(`/api/social/public-rooms?user_id=${encodeURIComponent(userId)}`);

export const joinPublicRoom = (userId: string, roomId: string) =>
  fetchJSON<{ joined: boolean; room_id: string }>(
    `/api/social/public-rooms/${encodeURIComponent(roomId)}/join`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );

export const joinRoom = (userId: string, inviteCode: string) =>
  fetchJSON<{ room: any }>('/api/social/rooms/join', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, invite_code: inviteCode }),
  });

export const getUserRooms = (userId: string) =>
  fetchJSON<{ rooms: any[] }>(`/api/social/rooms/${userId}`);

export const getRoomOverview = (roomId: string) =>
  fetchJSON<RoomOverviewData>(`/api/social/rooms/${roomId}/overview`);

export const getRoomActivity = (roomId: string) =>
  fetchJSON<{ activities: any[] }>(`/api/social/rooms/${roomId}/activity`);

export const findStudyMatches = (roomId: string, userId: string) =>
  fetchJSON<{ matches: any[] }>(`/api/social/rooms/${roomId}/match`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const getRoomMessages = (roomId: string, opts?: { before?: string; limit?: number }) => {
  const params = new URLSearchParams();
  if (opts?.before) params.set('before', opts.before);
  if (opts?.limit) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return fetchJSON<{ messages: RoomMessageRow[]; has_more?: boolean }>(
    `/api/social/rooms/${roomId}/messages${qs ? `?${qs}` : ''}`,
  );
};

export const sendRoomMessage = (
  roomId: string, userId: string, userName: string, text: string,
  imageUrl?: string, replyToId?: string,
  /** Intrinsic pixel size of imageUrl, so the transcript can reserve the box
   *  before the lazily-loaded image arrives (#315). */
  imageSize?: { width: number; height: number },
) =>
  fetchJSON<{ message: any }>(`/api/social/rooms/${roomId}/messages`, {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId, user_name: userName, text: text || null,
      image_url: imageUrl || null,
      image_width: imageSize?.width ?? null,
      image_height: imageSize?.height ?? null,
      reply_to_id: replyToId || null,
    }),
  });

export const toggleRoomReaction = (roomId: string, messageId: string, userId: string, emoji: string) =>
  fetchJSON<{ added: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}/reactions`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, emoji }),
  });

export const editRoomMessage = (roomId: string, messageId: string, userId: string, text: string) =>
  fetchJSON<{ edited: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, text }),
  });

export const deleteRoomMessage = (roomId: string, messageId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });

export const leaveRoom = (roomId: string, userId: string) =>
  fetchJSON<{ left: boolean }>(`/api/social/rooms/${roomId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const kickMember = (roomId: string, memberId: string, requesterId: string) =>
  fetchJSON<{ kicked: boolean }>(
    `/api/social/rooms/${roomId}/members/${encodeURIComponent(memberId)}?requester_id=${encodeURIComponent(requesterId)}`,
    { method: 'DELETE' },
  );

export interface StudentRow {
  user_id: string;
  name: string;
  streak: number;
  courses: string[];
  // Per-concept mastery (stats/top_concepts) was removed from this endpoint in
  // #342: it is academic-performance data that belongs on the profile page, not
  // in a browsable directory. The directory is now name + courses + streak only.
}

export const getStudents = () =>
  fetchJSON<{ students: StudentRow[] }>(`/api/social/students`);

export const schoolMatch = (userId: string) =>
  fetchJSON<{ matches: any[] }>('/api/social/school-match', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

// Documents
export const getDocuments = (userId: string) =>
  fetchJSON<{ documents: any[] }>(`/api/documents/user/${userId}`);

export const deleteDocument = (documentId: string, userId?: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/documents/doc/${documentId}${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`, { method: 'DELETE' });

export const uploadDocument = (formData: FormData, signal?: AbortSignal): Promise<any> => {
  // Non-streaming JSON upload. Hits /upload/sync (legacy contract) so callers
  // that don't care about progress events stay one-line. The streaming /upload
  // route is exposed separately via uploadDocumentStream below.
  return fetch(`${API_URL}/api/documents/upload/sync`, { method: 'POST', body: formData, signal, credentials: 'include' })
    .then(async r => { if (!r.ok) { const e = await r.text(); throw new Error(e || `HTTP ${r.status}`); } return r.json(); });
};

// Streaming upload — emits SaplingEvent SSE events while the orchestrator runs.
// Event types match backend/services/agent_events.py::SaplingEvent.
export type UploadEventType = 'status' | 'progress' | 'result' | 'error';

export interface UploadEvent {
  type: UploadEventType;
  step: string;
  message: string;
  data?: Record<string, unknown> | null;
}

/**
 * How an upload stream ended (#759) — a function of the server's terminal
 * events alone:
 *   - `error:failed` (with or without an earlier `result`) → `failed`, with
 *     the server's message. A post-result failure means nothing was saved.
 *   - `result` then `status:done` carrying a `document_id` → `processed`.
 *   - `status:done` without a saved document → `failed`.
 * `result` is the `result` event's data: a DocumentProcessingResult dump
 * (an idempotent replay sends the same shape plus `id`/`replayed`).
 */
export interface UploadResultData {
  id?: string;
  replayed?: boolean;
  classification?: { category?: string; is_syllabus?: boolean };
  summary?: { abstract?: string };
  concepts?: { concepts?: Array<{ name?: string; description?: string }> };
  [key: string]: unknown;
}

export type UploadOutcome =
  | { kind: 'processed'; documentId: string; result: UploadResultData }
  | { kind: 'failed'; message: string; requestId?: string; afterResult: boolean };

/**
 * Streams POST /api/documents/upload. Resolves to an UploadOutcome whenever
 * the server reached a terminal event; rejects only on transport failure
 * (HTTP error before the stream opened, network drop, abort) or a stream
 * that closed with no terminal event.
 */
export async function uploadDocumentStream(
  formData: FormData,
  onEvent: (event: UploadEvent) => void,
  signal?: AbortSignal,
  requestId?: string,
): Promise<UploadOutcome> {
  const { streamSSE } = await import('./sse');
  let result: UploadResultData | null = null;
  let failure: { message: string; requestId?: string } | null = null;
  let done = false;
  let documentId: string | undefined;
  const headers: Record<string, string> = {};
  if (requestId) headers['X-Request-ID'] = requestId;
  for await (const e of streamSSE<UploadEvent>(
    `${API_URL}/api/documents/upload`,
    { method: 'POST', body: formData, signal, credentials: 'include', headers },
  )) {
    onEvent(e.data);
    const data = (e.data.data ?? {}) as Record<string, unknown>;
    if (e.event === 'result') {
      result = data as UploadResultData;
    } else if (e.event === 'error' && e.data.step === 'failed') {
      failure = {
        message: e.data.message,
        requestId: typeof data.request_id === 'string' ? data.request_id : undefined,
      };
    } else if (e.event === 'status' && e.data.step === 'done') {
      done = true;
      if (typeof data.document_id === 'string' && data.document_id) {
        documentId = data.document_id;
      }
    }
  }
  if (failure) {
    return {
      kind: 'failed',
      message: failure.message || 'Document processing failed. Please try again.',
      requestId: failure.requestId,
      afterResult: result !== null,
    };
  }
  if (result && documentId) return { kind: 'processed', documentId, result };
  if (done) {
    return {
      kind: 'failed',
      message: 'The server finished without saving the document. Please try again.',
      afterResult: result !== null,
    };
  }
  throw new Error('Upload stream ended before the server finished.');
}

export const updateDocumentCategory = (documentId: string, userId: string, category: string) =>
  fetchJSON<{ id: string; category: string }>(`/api/documents/doc/${documentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, category }),
  });

export interface ScanConceptsResponse {
  concepts: string[];
  added: number;
  existing: number;
}

export const scanDocumentConcepts = (documentId: string, userId: string) =>
  fetchJSON<ScanConceptsResponse>(`/api/documents/doc/${documentId}/scan-concepts`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const scanCourseConcepts = (courseId: string, userId: string) =>
  fetchJSON<ScanConceptsResponse>(`/api/documents/course/${courseId}/scan-concepts`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

// Flashcards
export interface GenerateFlashcardsResponse {
  flashcards: any[];
  context_used?: { documents_found: number; weak_concepts_found: number };
  /** Cards held back for giving away an open learning check's answer (spec §13 A125). */
  withheld?: number;
}

// `semester` (term label, #141) grounds generation in that term's course
// documents; omitted = every term. `courseId` (#829) scopes the documents to
// the selected course by id — without it the backend matches `topic` against
// the student's enrolled courses. JSON.stringify drops either when unset.
export const generateFlashcards = (
  userId: string,
  topic: string,
  count = 5,
  semester?: string,
  courseId?: string,
) =>
  // docs/safety/crisis-support.md: a crisis answer carries `crisis_support` and no cards.
  fetchJSON<GenerateFlashcardsResponse & WithCrisisSupport>('/api/flashcards/generate', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, topic, count, semester, course_id: courseId }),
  });

// `semester` scopes the list to that term's offerings (term-less cards stay
// visible); ""/undefined = All semesters, the unscoped default (#141).
export const getFlashcards = (userId: string, topic?: string, semester?: string) => {
  const params = new URLSearchParams();
  if (topic) params.set('topic', topic);
  if (semester) params.set('semester', semester);
  const qs = params.toString();
  return fetchJSON<{ flashcards: any[] }>(
    `/api/flashcards/user/${userId}${qs ? `?${qs}` : ''}`
  );
};

export const rateFlashcard = (userId: string, cardId: string, rating: number) =>
  fetchJSON<{ ok: boolean }>('/api/flashcards/rate', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, card_id: cardId, rating }),
  });

export const deleteFlashcard = (userId: string, cardId: string) =>
  fetchJSON<{ ok: boolean }>(
    `/api/flashcards/${encodeURIComponent(cardId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

// Learning loop (PKG-12): the daily review queue (backend/routes/learn_loop.py
// /review/*). Every route 404s while the loop is off for this student (spec §7),
// so callers treat a 404 as "inactive", never as an error. Its wire types live in
// lib/reviewTypes.ts and are re-exported here.
export type {
  ReviewAnswerBody, ReviewAnswerResponse, ReviewItemPayload, ReviewNextResponse, ReviewSr, ReviewSummaryResponse,
} from '@/lib/reviewTypes';

const reviewQuery = (userId: string, courseId?: string) => {
  const params = new URLSearchParams({ user_id: userId });
  if (courseId) params.set('course_id', courseId);
  return params.toString();
};
/** #866 K17: the review queue keeps the student's LOCAL day (one session and one
 *  daily budget per day), from JS getTimezoneOffset, as the Daily Goal panel does. */
const localTzOffset = () => new Date().getTimezoneOffset();
const reviewDayQuery = (userId: string, courseId?: string) =>
  `${reviewQuery(userId, courseId)}&tz_offset_min=${localTzOffset()}`;

export const getReviewNext = (userId: string, courseId?: string) =>
  fetchJSON<ReviewNextResponse>(`/api/learn/loop/review/next?${reviewDayQuery(userId, courseId)}`);

export const answerReview = (body: ReviewAnswerBody) =>
  fetchJSON<ReviewAnswerResponse>('/api/learn/loop/review/answer', {
    method: 'POST',
    body: JSON.stringify({ ...body, tz_offset_min: localTzOffset() }),
  });

export const getReviewSummary = (userId: string, courseId?: string) =>
  fetchJSON<ReviewSummaryResponse>(`/api/learn/loop/review/summary?${reviewDayQuery(userId, courseId)}`);

/** Is the learning loop on for this student? Probes GET /review/active — a
 *  gate-only route that builds nothing (PKG-07's /status needs a loop session id).
 *  It answers `{active}` with 200 either way (PKG-13 fix round: a 404 for "off"
 *  logged an error.4xx on every legacy visit); a 404 from an older backend still
 *  reads as inactive. Any other failure rejects — the caller decides (useLoopStatus
 *  times out and retries). */
export const getLoopStatus = async (userId: string): Promise<{ active: boolean }> => {
  try {
    return await fetchJSON<{ active: boolean }>(
      `/api/learn/loop/review/active?${reviewQuery(userId)}`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return { active: false };
    throw err;
  }
};

// ── Learning loop (PKG-13) ──────────────────────────────────────────────────
// Clients for the loop tutor routes (backend/routes/learn_loop.py; shapes from
// the code and HANDOFF-07/08/09, which override the PKG-13 prompt's table).
// Every route 404s while the loop is off for the student (spec §7); only
// getLoopStatus (above) swallows that. No loop client takes or sends
// model_pref: the tier is chosen in code (spec §13 A15/A26). The attempt box
// submits ONLY through streamLoopCheckAnswer, never as a chat turn (A16).
export type LoopPhase = 'probe' | 'plan' | 'teach' | 'check' | 'feedback' | 'close';
export type LoopBand = 'novice' | 'develop' | 'profic';
export type LoopFormat = 'free' | 'teachback' | 'mc_reason';
/** Explicit learner-confirmed concepts; null means exploring the whole course. */
export interface LoopGoal { text: string; target_node_ids: string[] }
export interface LoopDiagnosisSkill {
  node_id: string;
  status: 'bracketed' | 'partial' | 'above_range' | 'below_range' | 'untested' | 'inconsistent';
  floor_difficulty: number | null;
  ceiling_difficulty: number | null;
  independent_correct: number;
  independent_incorrect: number;
  independent_observations: number;
  observations: number;
  tested_difficulties: number[];
  available_difficulties: number[];
  contradictory_difficulties: number[];
}
export interface LoopDiagnosis {
  status: 'bracketed' | 'limited' | 'in_progress' | 'not_assessed';
  stop_reason: string | null;
  skills: LoopDiagnosisSkill[];
}
export interface LoopLearningScope {
  goal_version?: number;
  goal?: LoopGoal | null;
  diagnosis?: LoopDiagnosis | null;
  goal_progress?: LoopGoalProgress | null;
  /** Goal-frontier concepts without a fresh, non-reserved practice item.
   *  These remain unresolved; teaching/source review does not assess them. */
  practice_unavailable_node_ids?: string[];
}
export interface LoopGoalProgress {
  status: 'continue_available' | 'needs_more_practice' | 'session_plan_finished';
  target_node_ids: string[];
  remaining_target_node_ids: string[];
  unresolved_prerequisite_ids: string[];
  attempted_node_ids: string[];
}
export interface LoopGoalResult extends LoopLearningScope, WithCrisisSupport { phase: LoopPhase }

/** A served option (A22): stored letter + text, never marked correct. */
export interface LoopOption { letter: string; text: string }
/** The check pose (`_pose_payload`). The `check` stream event carries only
 *  `question_hash`/`format`/`difficulty`; `done.check` and `/check/next` carry
 *  the whole pose. The pose never names its concept node. */
export interface LoopCheckItem {
  question_hash: string;
  format: LoopFormat;
  difficulty: number;
  prompt?: string;
  options?: LoopOption[] | null;
  /** Spec §13 A122: the item opens on its worked example (a novice without the
   *  prerequisite) and it is still owed — ask for it at once: /hint grants H4
   *  with no attempt first, the hint turn serves it. Present only when true. */
  worked_first?: boolean;
  /** W4.4: the bank already confirmed this item's key (canonical_verified /
   *  blind-key or audit). Present only when true — calm "Key verified" chrome
   *  on the check card; never invented client-side. */
  key_verified?: boolean;
  /** W4.1a: optional figure slot on the pose. `withheld` = visual surface with
   *  no drawable asset yet (honest empty). Never invents SVG client-side. */
  figure?: { status: "withheld" | "illustrative" };
}
export interface LoopProbeItem extends LoopCheckItem {
  check_item_id: string;
  node_id: string;
  prompt: string;
}
/** Spec §13 A138 (`segment_prequestion` on): the ungraded guess that opens a
 *  teaching segment — a vetted item of the concept, asked before any teaching
 *  on it; "No idea" is always allowed and nothing is graded. Served options
 *  are never marked correct (A22). `text` is the exact assistant row the
 *  server saved for the pose: the log hides that row while the card shows it.
 *  `answered` (GET /status only): the guess is saved and its explanation is
 *  still owed — the card offers to show it. */
export interface LoopPrequestion {
  question_hash: string;
  format: 'mc_reason' | 'free';
  difficulty: number;
  prompt: string;
  options: LoopOption[] | null;
  text: string;
  answered?: boolean;
}
/** A guess at the prequestion. `no_idea` sends no answer fields; once a guess
 *  is saved the server ignores these and re-serves the explanation. */
export interface LoopPrequestionGuess {
  answer?: string;
  option?: string;
  reason?: string;
  no_idea: boolean;
}
/** Spec §13 A139 (`self_explanation_prompts` on): the turn's single question is
 *  a "why does this follow?" prompt at a juncture code chose. `prompt` is the
 *  turn's last line (already in the turn's reply text). The reply is stored for
 *  diagnosis only: never graded, never evidence. */
export interface LoopSelfExplain {
  prompt_id: string;
  juncture: 'worked_example' | 'released_solution' | 'first_correct';
  prompt: string;
}
/** POST /self-explain: the reply (or skip) recorded; `prequestion` is the next
 *  segment's guess when the closed prompt was holding it back (A138/A139: one
 *  open prompt at a time). */
export type LoopSelfExplainResult = WithCrisisSupport & (
  | { recorded: true; status: 'replied' | 'skipped'; prequestion?: LoopPrequestion | null }
  // docs/safety/crisis-support.md: the card instead of a recorded reply
  | { recorded: false });
/** Opaque saved grading result; never includes the answer, key or checkpoint. */
export interface LoopPendingGrade { kind: 'check' | 'probe'; question_hash: string }
export type LoopProbeNext = LoopLearningScope & (
  | ({ done: false } & LoopProbeItem)
  | { done: false; pending_grade: LoopPendingGrade }
  // A128: `preparing` (present only when true) — none yet: the student's upload is being drafted
  | { done: true; phase: LoopPhase; no_check_items?: boolean; preparing?: boolean });
export type LoopProbeAnswerResult = LoopLearningScope & WithCrisisSupport & (
  | { graded: true; correct: boolean; p_known: number; probe_done: boolean; novice_floor: boolean; reference_answer?: string; feedback_dwell_ms?: number }
  // unavailable → counted as not asked; refused (A33) → the item stays posed;
  // recorded: false → graded but lost to a stale claim (the probe moved on)
  | { graded: false; unavailable?: boolean; refused?: boolean; recorded?: boolean });
/** `measured: false` (#866 K52; present only then): the concept has no stored
 *  state yet — p_known/band are the prior, never shown as the student's skill. */
export interface LoopLearnerState { node_id: string; p_known: number; band: LoopBand; measured?: false }
export interface LoopPlanConcept {
  node_id: string;
  concept_name: string;
  /** One kind per concept (`learning/planner.py::PlanKind`): `started` is new
   *  material the student has already made progress on (a map tier past
   *  unexplored). `string`: a kind this client does not know shows no badge. */
  kind: 'review' | 'new' | 'started' | 'sibling' | string;
  p_known: number;
  /** Sent only in a goal session: 'goal' | 'prerequisite'. 'review' and
   *  'related' are what servers before #866 sent outside a goal; they stay in
   *  the union for deploy skew and are never shown (`planGoalReason`). */
  reason?: 'goal' | 'prerequisite' | 'review' | 'related';
  target_node_ids?: string[];
}
/** W3.1: prereq pairs among today's plan proposal ∪ goal targets (GET /plan). */
export interface LoopPlanPrereqEdge {
  prerequisite: string;
  dependent: string;
}
export interface LoopPlan extends LoopLearningScope {
  concepts: LoopPlanConcept[];
  order: string[];
  /** Nothing to plan: the server moved the session straight to `teach`. */
  empty?: boolean;
  phase?: LoopPhase;
  /** Planner-aligned prerequisite edges for PlanPanel dependency view (W3.1). */
  prereq_edges?: LoopPlanPrereqEdge[];
}
export interface LoopOpenSession { session_id: string; topic: string; started_at: string; phase: LoopPhase }
export interface LoopStartResult extends LoopLearningScope, WithCrisisSupport {
  session_id: string;
  initial_message: string;
  graph_state?: unknown;
  /** Present at the hard level: the opener is then a template, never a 429 (A27). */
  budget?: LoopBudgetNotice | null;
  /** A128: the opener's course-material retrieval failed (present only when true). */
  materials_unavailable?: boolean;
  /** W4.3: the opener's prompt included course passages (present only when true). */
  materials_grounded?: boolean;
}
/** #866 K08: the approved plan as GET /status lists it, sent by a turn or
 *  "Check me" only when that request moved it (its cursor, or band repair's
 *  list); absent, nothing moved. */
export interface LoopPlanMoved { approved_plan?: { concepts: LoopPanelConcept[]; cursor: number } }
/** A loop turn's `done.data` / JSON body (HANDOFF-07 §Symbols). */
export interface LoopTurnResult extends ChatResult, LoopPlanMoved, LoopCreditFields { // #866 K07: credit
  phase?: string;
  check?: LoopCheckItem | null;
  budget?: LoopBudgetNotice | null;
  learner_state?: LoopLearnerState[];
  hint_offer?: { rung: number } | null;
  /** A128: this turn's course-material retrieval failed — present (true) on the
   *  session's FIRST such turn only; the UI shows one calm note from it. */
  materials_unavailable?: boolean;
  /** W4.3: this turn's prompt included retrieved course passages — present
   *  (true) only then; the UI's calm "Grounded in your materials" chrome. */
  materials_grounded?: boolean;
  // submissions (/check/answer) add these
  graded?: boolean;
  verdict?: string | null;
  unavailable?: boolean;
  answer_released?: boolean;
  refused?: boolean;
  /** PKG-14: present (true) on the graded check that reached ZPD_RATING_EVERY_N_CHECKS. */
  ask_rating?: boolean;
  /** W2.5: ms Continue must wait after high-confidence wrong feedback (present only then). */
  feedback_dwell_ms?: number;
  /** Spec §13 A138: this turn opened a new segment on its ungraded guess (present only then). */
  prequestion?: LoopPrequestion | null;
  /** Spec §13 A139: this turn's question is a self-explanation prompt (present only then). */
  self_explain?: LoopSelfExplain | null;
  /** Spec §13 A138: the prequestion answer route's turn (its guess is saved). */
  prequestion_answered?: boolean;
}
/** #866 K07: what a correct check answer earned — lib/loopCredit.ts. */
export type { LoopCredit, LoopCreditReason } from '@/lib/loopCredit';
/** The perceived-difficulty answer (spec §3.4, §6 zpd.rating). */
export type LoopRating = 'too_easy' | 'appropriate' | 'too_hard';
export interface LoopCheckNext extends LoopLearningScope, LoopPlanMoved {
  phase: LoopPhase;
  check?: LoopCheckItem | null;
  pending_grade?: LoopPendingGrade | null;
  plan_done?: boolean;
  /** A128: no check yet because the student's upload is still being drafted. */
  preparing?: boolean;
  /** With `check` null: the plan's concepts that have no check question yet
   *  (nothing was checked on them) — "Check me" names them. */
  checks_unavailable_node_ids?: string[];
}
/** POST /hint moves the rung only: `{denied}` or `{rung, intent}`; the hint TEXT
 *  is the next `[ACTION: hint]` turn (requestLoopHintTurn). */
/** `lifts: 'attempt'` (#866 K32; an `h6_gate` denial only): another genuine try opens it. */
export interface LoopHintResponse { denied?: string; rung?: number; intent?: string; lifts?: 'attempt' }
/** `wait_s` (#866 K32): present when only the independent-time gate kept a real attempt from counting. */
export interface LoopAttemptResult extends WithCrisisSupport { genuine: boolean; counted: boolean; attempts: number; independent_s: number; wait_s?: number }
/** A60: `close_json` as stored — no student answer to `self_eval`/`if_then`. */
/** Spec §13 A117 (backend learning/session_close.py::Baseline): where a concept's
 *  reported change starts. `pre_session` — the estimate it had before the session;
 *  `check_in` / `teaching` — no evidence before the session, so its first
 *  measurement this session (never the BKT prior). */
export type LoopCloseBaseline = 'pre_session' | 'check_in' | 'teaching';
export interface LoopCloseConcept {
  node_id: string;
  /** Where the reported change starts (see `baseline`). */
  p_before: number;
  p_after: number;
  /** Absent on a close stored before A117: read it as `pre_session`. */
  baseline?: LoopCloseBaseline;
}
export interface LoopCloseRecord {
  summary: string;
  self_eval: string;
  if_then: string;
  concepts: LoopCloseConcept[];
  misconceptions: string[];
  model_written: boolean;
}
export interface LoopCloseResponse { close: LoopCloseRecord; model_written: boolean; close_phase: string | null }
/** Spec §13 A127: the student's stated confidence ("Guessing" / "Fairly sure" /
 *  "Sure") — the answer bodies' enum (backend learning.evidence.StudentConfidence).
 *  Optional: a skip sends nothing, never a default. */
export type StudentConfidence = 'guessing' | 'fairly_sure' | 'sure';
/** PKG-07's LoopCheckAnswerBody answer fields (the probe takes the same ones).
 *  `reasoning` is W2.3's optional free/teachback "show your reasoning" — check
 *  submit only; never graded / never evidence. */
export interface LoopCheckAnswer {
  answer?: string;
  option?: string;
  reason?: string;
  reasoning?: string;
  idk: boolean;
  /** A127: sent only when chosen, and never with an idk (which states none). */
  confidence?: StudentConfidence | null;
}

const loopPost = <T>(path: string, body: Record<string, unknown>) =>
  fetchJSON<T>(`/api/learn/loop${path}`, { method: 'POST', body: JSON.stringify(body) });

const loopAnswerFields = (a: LoopCheckAnswer): Record<string, unknown> => ({
  ...(a.idk ? {} : a.option !== undefined ? { option: a.option, reason: a.reason ?? '' } : { answer: a.answer ?? '' }),
  idk: a.idk,
  ...(!a.idk && a.confidence ? { confidence: a.confidence } : {}),
  ...(!a.idk && a.reasoning?.trim() ? { reasoning: a.reasoning.trim() } : {}),
});


/** The student's open loop sessions for a course, newest first (PKG-13's
 *  GET /sessions; read-only, never rate-limited). */
export const listLoopSessions = async (userId: string, courseId: string): Promise<LoopOpenSession[]> => {
  const params = new URLSearchParams({ user_id: userId, course_id: courseId });
  const r = await fetchJSON<{ sessions: LoopOpenSession[] }>(`/api/learn/loop/sessions?${params}`);
  return r.sessions ?? [];
};

/** An open loop session `?resume=` named, wherever it lives (another course,
 *  past the list limit): the listed shape plus its abstract course. */
export interface LoopResumeSession extends LoopOpenSession { course_id: string }
/** `complete` (#866 K29): the list holds every open session of the course — it
 *  is the newest few, so false means an older open one is not in it. */
export interface LoopSessionList { sessions: LoopOpenSession[]; resume: LoopResumeSession | null; complete: boolean }

/** GET /sessions plus, for a `/learn?resume=<id>` deep link, that session when
 *  it is the student's open loop session in ANY course (null: a legacy or closed
 *  one — shown read-only). */
export const listLoopSessionsFor = async (
  userId: string, courseId: string, resumeId: string | null,
): Promise<LoopSessionList> => {
  const params = new URLSearchParams({ user_id: userId, course_id: courseId });
  if (resumeId) params.set('resume', resumeId);
  const r = await fetchJSON<{ sessions?: LoopOpenSession[]; resume?: LoopResumeSession | null; complete?: boolean }>(
    `/api/learn/loop/sessions?${params}`,
  );
  return { sessions: r.sessions ?? [], resume: r.resume ?? null, complete: r.complete !== false };
};

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
  // approved_plan (LoopPlanMoved): the approved plan, in order, with its cursor
  // (absent before approval) — always, on /status
}
/** A concept as the Tutor's session panel lists it. */
export interface LoopPanelConcept { node_id: string; concept_name: string; kind: string; reason?: LoopPlanConcept['reason'] }
export const getLoopSessionStatus = (sessionId: string, userId: string) =>
  fetchJSON<LoopSessionStatus>(`/api/learn/loop/status?${new URLSearchParams({ user_id: userId, session_id: sessionId })}`);

/** The teaching modes StartSessionBody.mode knows (the legacy deep links' ?mode=). */
export const LOOP_DEEP_LINK_MODES = ['socratic', 'expository', 'teachback'] as const;

/** `fromNoteId`: Send to tutor's note, sent only while `topic` is still that
 *  note's title — the backend screens the note as stored material, so a crisis
 *  match puts the card beside the session (`crisis_support_alongside`) instead
 *  of in place of it (docs/safety/crisis-support.md). */
export const startLoopSession = (userId: string, courseId: string, topic: string, mode?: string | null, goal?: LoopGoal | null, fromNoteId?: string | null) =>
  loopPost<LoopStartResult>('/start-session', {
    user_id: userId,
    topic,
    course_id: courseId,
    ...(mode && (LOOP_DEEP_LINK_MODES as readonly string[]).includes(mode) ? { mode } : {}),
    ...(goal !== undefined ? { goal } : {}),
    ...(fromNoteId ? { from_note_id: fromNoteId } : {}),
  });

export const setLoopGoal = (sessionId: string, userId: string, goal: LoopGoal | null) =>
  loopPost<LoopGoalResult>('/goal', { session_id: sessionId, user_id: userId, goal });

export const nextLoopProbe = (sessionId: string, userId: string) =>
  loopPost<LoopProbeNext>('/probe/next', { session_id: sessionId, user_id: userId });

export const answerLoopProbe = (sessionId: string, userId: string, questionHash: string, a: LoopCheckAnswer) =>
  loopPost<LoopProbeAnswerResult>('/probe/answer', {
    session_id: sessionId, user_id: userId, question_hash: questionHash, ...loopAnswerFields(a),
  });

export const getLoopPlan = (sessionId: string, userId: string) =>
  fetchJSON<LoopPlan>(`/api/learn/loop/plan?${new URLSearchParams({ session_id: sessionId, user_id: userId })}`);

export const approveLoopPlan = (sessionId: string, userId: string, conceptIds: string[], goalVersion?: number) =>
  // spec §13 A138: `prequestion` — the first segment opens on an ungraded guess
  loopPost<{ phase: LoopPhase; concept_ids: string[]; prequestion?: LoopPrequestion | null }>('/plan/approve', {
    session_id: sessionId, user_id: userId, concept_ids: conceptIds,
    ...(goalVersion !== undefined ? { goal_version: goalVersion } : {}),
  });

/** #866 K10: a loop turn's `done` is its saved result, kept when Stop comes after it. */
const LOOP_STREAM = { keepDoneOnStop: true };

export const streamLoopChat = (sessionId: string, userId: string, message: string, handlers: StreamChatHandlers = {}) =>
  consumeChatStream(
    '/api/learn/loop/chat/stream', { session_id: sessionId, user_id: userId, message }, handlers, LOOP_STREAM,
  ) as Promise<LoopTurnResult>;

/** The attempt box's ONLY submit path (spec §13 A16): an explicit answer, never a chat message. */
export const streamLoopCheckAnswer = (
  sessionId: string, userId: string, questionHash: string, a: LoopCheckAnswer, handlers: StreamChatHandlers = {},
) =>
  consumeChatStream('/api/learn/loop/check/answer/stream', {
    session_id: sessionId, user_id: userId, question_hash: questionHash, ...loopAnswerFields(a),
  }, handlers, LOOP_STREAM) as Promise<LoopTurnResult>;

/** Spec §13 A138: the guess at a segment's ungraded prequestion, then — in the
 *  same stream — its explanation turn (the answer first, from code). Nothing is
 *  graded. `answer` only for a free item, `option` (+ an optional `reason`) only
 *  for multiple choice, `no_idea: true` with no answer fields. */
export const streamLoopPrequestionAnswer = (
  sessionId: string, userId: string, questionHash: string, guess: LoopPrequestionGuess,
  handlers: StreamChatHandlers = {},
) =>
  consumeChatStream('/api/learn/loop/prequestion/answer/stream', {
    session_id: sessionId,
    user_id: userId,
    question_hash: questionHash,
    ...(guess.no_idea
      ? {}
      : guess.option !== undefined
        ? { option: guess.option, ...(guess.reason ? { reason: guess.reason } : {}) }
        : guess.answer !== undefined ? { answer: guess.answer } : {}),
    no_idea: guess.no_idea,
  }, handlers, LOOP_STREAM) as Promise<LoopTurnResult>;

/** Spec §13 A139: the student's reply to a self-explanation prompt, or a skip.
 *  Stored for diagnosis only — never graded, never evidence. */
export const postLoopSelfExplain = (
  sessionId: string, userId: string, promptId: string, body: { reply?: string; skip: boolean },
) =>
  loopPost<LoopSelfExplainResult>('/self-explain', {
    session_id: sessionId,
    user_id: userId,
    prompt_id: promptId,
    ...(body.skip ? {} : { reply: body.reply ?? '' }),
    skip: body.skip,
  });

/** Records a genuine attempt for hint unlocking only (never stored, never graded). */
export const postLoopAttempt =(sessionId: string, userId: string, questionHash: string, attemptText: string) =>
  loopPost<LoopAttemptResult>('/step/attempt', {
    session_id: sessionId, user_id: userId, question_hash: questionHash, attempt_text: attemptText,
  });

/** "Check me" (A27): activates the current concept's next item and returns its pose.
 *  It WRITES (activation) — a resume restores through getLoopSessionStatus instead. */
export const nextLoopCheck = (sessionId: string, userId: string) =>
  loopPost<LoopCheckNext>('/check/next', { session_id: sessionId, user_id: userId });

export const requestLoopHint = (sessionId: string, userId: string, questionHash: string) =>
  loopPost<LoopHintResponse>('/hint', { session_id: sessionId, user_id: userId, question_hash: questionHash });

/** The hint's text: the `[ACTION: hint]` turn at the item's (new) rung (JSON; may 429). */
export const requestLoopHintTurn = (sessionId: string, userId: string) =>
  loopPost<LoopTurnResult>('/action', { session_id: sessionId, user_id: userId, action_type: 'hint' });

/** PKG-14: the perceived-difficulty rating the loop asks for every N checks; the
 *  user is the session cookie's. Emits zpd.rating and resets the counter. */
export const submitLoopRating = (sessionId: string, rating: LoopRating) =>
  fetchJSON<{ ok: true }>('/api/learn/loop/rating', { method: 'POST', body: JSON.stringify({ session_id: sessionId, rating }) });

/** Ends the session with its close (idempotent; A60). 409 while a close or a grade is in flight. */
export const closeLoopSession = (sessionId: string, userId: string) =>
  loopPost<LoopCloseResponse>('/close', { session_id: sessionId, user_id: userId });

/** "Report this question" (spec §13 A113; #695): enums only — no free text is
 *  ever sent or stored. Behind the `item_reports` flag (404 while it is off). */
export type LoopReportReason = 'wrong_answer' | 'unclear' | 'not_from_my_course';
export type LoopReportBody =
  // the loop's check card: the session's posed check, by its hash
  | { surface: 'loop'; user_id: string; session_id: string; question_hash: string; reason: LoopReportReason }
  // Study's review queue: today's review session's served item, by its id
  | { surface: 'review'; user_id: string; session_id: string; item_id: string; course_id?: string; reason: LoopReportReason };
/** `first` false: already reported (nothing new recorded); `quarantined`:
 *  this report withheld the question from the whole course until staff decide
 *  (spec §13 A123 — a report never deletes a question). */
export interface LoopReportResult { reported: true; first: boolean; quarantined: boolean }
export const reportCheckItem = (body: LoopReportBody) =>
  // #866 K17: a review report names the student's day, as /review/next keeps it
  loopPost<LoopReportResult>('/report', body.surface === 'review' ? { ...body, tz_offset_min: localTzOffset() } : body);

export interface RetentionItem extends LoopCheckItem { node_id: string }
export type RetentionAnswerResult = WithCrisisSupport & (
  | { graded: false; refused: true }
  | { correct: boolean; confidence: number }
  // docs/safety/crisis-support.md: the card instead of a grade (nothing recorded)
  | { graded: false; crisis_support: NonNullable<WithCrisisSupport['crisis_support']> });
/** Explicitly opening commits a delayed pose; never call during page load. */
export const startRetentionCheck = (userId: string, courseId: string) =>
  loopPost<{ items: RetentionItem[] }>('/posttest/start', { user_id: userId, course_id: courseId });
/** `hidden_count` / `hidden_s` (spec §13 A126): how often and how long the page
 *  was hidden while the item was on screen — telemetry the server clamps and
 *  never grades. */
export const answerRetentionCheck = (body: {
  user_id: string; node_id: string; question_hash: string;
  answer?: string; selected_option?: string; reason?: string; idk: boolean;
  hidden_count?: number; hidden_s?: number;
}) => loopPost<RetentionAnswerResult>('/posttest/answer', body);
/** A126: the item is on screen — the server stamps its first display (the
 *  answer's latency is measured from it). Writes nothing else. */
export const markRetentionShown = (body: { user_id: string; node_id: string; question_hash: string }) =>
  loopPost<{ served: boolean }>('/posttest/shown', body);
/** A126: whether a retention check is due now (read-only, cached by the
 *  server; 404 while the `retention_due_badge` flag is off). */
export interface RetentionDue { due: boolean; course_ids: string[] }
export const fetchRetentionDue = (userId: string) =>
  fetchJSON<RetentionDue>(`/api/learn/loop/posttest/due?${new URLSearchParams({ user_id: userId })}`);

// Flashcard import
export interface ImportCard { front: string; back: string }
// `withheld` (spec §13 A125): cards held back for giving away an open learning
// check's answer; on cleanup, the whole cleanup was held back.
export interface ImportParseResponse { cards: ImportCard[]; errors: { row: number; message: string }[]; withheld?: number }
export interface ImportCommitResponse { inserted: number; skipped_duplicates: number }
export interface ImportGenerateResponse { cards: ImportCard[]; withheld?: number }

export const importParse = (
  userId: string,
  source: "anki" | "xlsx" | "url" | "ocr",
  payload: string,
  options: Record<string, unknown> = {},
) =>
  fetchJSON<ImportParseResponse>(`/api/flashcards/import/parse`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, source, payload, options }),
  });

export const importCommit = (
  userId: string,
  courseId: string | null,
  topic: string,
  cards: ImportCard[],
  dedup = true,
) =>
  fetchJSON<ImportCommitResponse>(`/api/flashcards/import/commit`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, course_id: courseId, topic, cards, dedup }),
  });

export const importGenerate = (
  userId: string,
  args:
    | { source: "paste"; text: string; count: number; difficulty: "recall" | "application" | "conceptual" }
    | { source: "library_doc"; documentId: string; count: number; difficulty: "recall" | "application" | "conceptual" },
) =>
  fetchJSON<ImportGenerateResponse & WithCrisisSupport>(`/api/flashcards/import/generate`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      source: args.source,
      text: args.source === "paste" ? args.text : undefined,
      document_id: args.source === "library_doc" ? args.documentId : undefined,
      count: args.count,
      difficulty: args.difficulty,
    }),
  });

export const importCleanup = (userId: string, cards: ImportCard[]) =>
  fetchJSON<{ cards: ImportCard[]; withheld?: number }>(`/api/flashcards/import/cleanup`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, cards }),
  });

export const importCloze = (userId: string, paragraph: string) =>
  fetchJSON<{ cards: ImportCard[]; withheld?: number } & WithCrisisSupport>(`/api/flashcards/import/cloze`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, paragraph }),
  });

// Feedback
export const submitFeedback = (data: {
  user_id: string; type: 'global' | 'session'; rating: number;
  selected_options: string[]; comment?: string; session_id?: string; topic?: string;
}) => fetchJSON<{ ok: boolean }>('/api/feedback', { method: 'POST', body: JSON.stringify(data) });

export const submitIssueReport = (data: {
  user_id: string; topic: string; description: string; screenshot_urls: string[];
}) => fetchJSON<{ ok: boolean }>('/api/issue-reports', { method: 'POST', body: JSON.stringify(data) });

// Onboarding
export interface OnboardingCourse {
  id: string;
  course_code: string;
  course_name: string;
}

export const onboardingCoursesSearch = (q: string) =>
  fetchJSON<{ courses: OnboardingCourse[] }>(
    `/api/onboarding/courses${q ? `?q=${encodeURIComponent(q)}` : ''}`,
  );

export interface OnboardingProfilePayload {
  user_id: string;
  first_name: string;
  last_name: string;
  year: string;
  /** Catalog course ids; empty when the student will add their courses later. */
  course_ids: string[];
  /** Under 18: the account starts with a private profile and class sharing off. */
  under_18: boolean;
  /** The Terms and Privacy Policy versions agreed to (lib/legal/versions.ts).
   * Anything but the current ones is a 422 `legal_outdated`. */
  accepted_terms_version: string;
  accepted_privacy_version: string;
}

export interface OnboardingProfileResult {
  ok: boolean;
  user_id: string;
  /** How many of `course_ids` the student was enrolled in. */
  courses_linked: number;
}

/** 409 when the account finished onboarding already; 403 `not_approved` (in
 * `detail.code`); 422 `legal_outdated` / `no_known_courses` (in `detail.code`)
 * save nothing; a malformed body is a plain validation 422 (`detail: [...]`). */
export const submitOnboardingProfile = (
  payload: OnboardingProfilePayload,
  init?: { signal?: AbortSignal },
) =>
  fetchJSON<OnboardingProfileResult>('/api/onboarding/profile', {
    method: 'POST',
    // Deploy-skew shim (PKG-14b): the pre-launch backend still REQUIRES
    // `learning_style` (a bare str), the post-launch one ignores it. Sending ""
    // keeps onboarding working whichever deploys first (the frontend worker or
    // Railway). Remove once both run PKG-14b.
    body: JSON.stringify({ ...payload, learning_style: '' }),
    signal: init?.signal,
  });

// Profile
export const fetchPublicProfile = (userId: string) =>
  fetchJSON<UserProfile>(`/api/profile/${userId}`);

export const checkUsername = (username: string, userId?: string) =>
  fetchJSON<{ available: boolean; reason?: 'taken' | 'invalid' | 'self' }>(
    `/api/profile/username/check?username=${encodeURIComponent(username)}${userId ? `&user_id=${encodeURIComponent(userId)}` : ''}`,
  );

export const setFeaturedAchievements = (userId: string, achievementIds: string[]) =>
  fetchJSON<{ updated: boolean }>(`/api/profile/${userId}/featured-achievements?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ achievement_ids: achievementIds }),
  });

export const setFeaturedRole = (userId: string, roleId: string | null) =>
  fetchJSON<{ updated: boolean }>(`/api/profile/${userId}/featured-role?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ role_id: roleId }),
  });

export const exportData = (userId: string) =>
  fetchJSON<Record<string, unknown>>(`/api/profile/${userId}/export?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
  });

export const updateProfile = (userId: string, data: Partial<UserProfile>) =>
  fetchJSON<{ updated: boolean }>(`/api/profile/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const fetchSettings = (userId: string) =>
  fetchJSON<UserSettings>(`/api/profile/${userId}/settings?user_id=${encodeURIComponent(userId)}`);

export const updateSettings = (userId: string, data: Partial<UserSettings>) =>
  fetchJSON<UserSettings>(`/api/profile/${userId}/settings?user_id=${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const equipCosmetic = (userId: string, slot: CosmeticType, cosmeticId: string | null) =>
  fetchJSON<{ equipped: boolean }>(`/api/profile/${userId}/equip?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ slot, cosmetic_id: cosmeticId }),
  });

export const fetchAchievements = (userId: string) =>
  fetchJSON<{ earned: UserAchievement[]; available: Achievement[] }>(`/api/profile/${userId}/achievements`);

export const fetchCosmetics = (userId: string) =>
  fetchJSON<{ cosmetics: Record<CosmeticType, UserCosmetic[]>; equipped: Record<string, any> }>(
    `/api/profile/${userId}/cosmetics?user_id=${encodeURIComponent(userId)}`
  );

export interface CatalogCosmetic extends Cosmetic {
  unlock_source?: string | null;
  owned: boolean;
}

export const fetchCosmeticsCatalog = (userId: string) =>
  fetchJSON<{ catalog: Record<CosmeticType, CatalogCosmetic[]> }>(
    `/api/profile/${userId}/cosmetics/catalog?user_id=${encodeURIComponent(userId)}`
  );

export const fetchRoles = (userId: string) =>
  fetchJSON<{ roles: UserRole[] }>(`/api/profile/${userId}/roles`);

export const deleteAccount = (userId: string, confirmation: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/profile/${userId}/account?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmation }),
  });

// Admin — users
export const adminFetchUsers = (params?: { q?: string; page?: number; page_size?: number }) => {
  const qp = new URLSearchParams();
  if (params?.q) qp.set('q', params.q);
  if (params?.page) qp.set('page', String(params.page));
  if (params?.page_size) qp.set('page_size', String(params.page_size));
  const suffix = qp.toString() ? `?${qp.toString()}` : '';
  return fetchJSON<PaginatedUsers>(`/api/admin/users${suffix}`);
};

// Remove access: the account leaves Admin → Users and its email goes back on
// the waitlist as a signup (Admin → Allowlist). Data is kept. The route keeps
// its historical `/unapprove` path; 409 on your own account.
export const adminRemoveUserAccess = (userId: string) =>
  fetchJSON<{ unapproved: boolean }>(`/api/admin/users/${userId}/unapprove`, { method: 'PATCH' });

// Admin — account tools (backend routes/admin_accounts.py; spec
// docs/superpowers/specs/2026-11-08-admin-account-tools-design.md). Each write
// sends the action word as `confirm` — the backend 400s without it; the UI
// first shows a review (summary / copy-preview: what will be deleted) and
// makes the admin type the account's email before calling these.
export const adminAccountsMeta = () =>
  fetchJSON<AdminAccountsMeta>('/api/admin/accounts/meta');

/** Read-only: what the account holds on this environment (the seed/wipe review). 404 unknown. */
export const adminAccountSummary = (userId: string) =>
  fetchJSON<AdminAccountSummary>(`/api/admin/accounts/${encodeURIComponent(userId)}/summary`);

/** Read-only: both sides of a copy (the copy review). 503 unconfigured, 502 peer down. */
export const adminCopyPreview = (userId: string, direction: AccountCopyDirection) =>
  fetchJSON<AdminCopyPreview>(
    `/api/admin/accounts/${encodeURIComponent(userId)}/copy-preview?direction=${direction}`,
  );

/** Wipe-then-seed the account with `major`'s mock semester (replaces, never stacks). */
export const adminSeedAccount = (userId: string, major: string) =>
  fetchJSON<AdminSeedAccountResult>(`/api/admin/accounts/${encodeURIComponent(userId)}/seed`, {
    method: 'POST',
    body: JSON.stringify({ major, confirm: 'SEED' }),
  });

/** Remove the account's academic/study data; the account itself is kept. */
export const adminWipeAccount = (userId: string) =>
  fetchJSON<AdminWipeAccountResult>(`/api/admin/accounts/${encodeURIComponent(userId)}/wipe`, {
    method: 'POST',
    body: JSON.stringify({ confirm: 'WIPE' }),
  });

/** push = overwrite the peer env's copy with ours; pull = overwrite ours with the peer's. */
export const adminCopyAccount = (userId: string, direction: AccountCopyDirection) =>
  fetchJSON<AdminCopyAccountResult>(`/api/admin/accounts/${encodeURIComponent(userId)}/copy`, {
    method: 'POST',
    body: JSON.stringify({ direction, confirm: 'COPY' }),
  });

// Admin — feedback (#520; decrypted server-side, admin-only)
export type AdminFeedbackEntry = {
  id: string; user_id: string; user_name: string; type: string; rating: number;
  selected_options: string[]; comment: string | null; session_id: string | null;
  topic: string | null; created_at: string;
};
export type AdminIssueReport = {
  id: string; user_id: string; user_name: string; topic: string;
  description: string; screenshot_urls: string[]; created_at: string;
};
export const adminListFeedback = () =>
  fetchJSON<{ feedback: AdminFeedbackEntry[] }>('/api/admin/feedback');
export const adminListIssueReports = () =>
  fetchJSON<{ reports: AdminIssueReport[] }>('/api/admin/issue-reports');

// Admin — roles
export const adminAssignRole = (userId: string, roleId: string) =>
  fetchJSON<{ assigned: boolean }>('/api/admin/roles/assign', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, role_id: roleId }),
  });

export const adminRevokeRole = (userId: string, roleId: string) =>
  fetchJSON<{ revoked: boolean }>('/api/admin/roles/revoke', {
    method: 'DELETE',
    body: JSON.stringify({ user_id: userId, role_id: roleId }),
  });

export const adminListRoles = () =>
  fetchJSON<{ roles: Role[] }>('/api/admin/roles');

export const adminCreateRole = (payload: {
  name: string; slug: string; color: string; icon?: string | null;
  description?: string | null; is_staff_assigned?: boolean;
  is_earnable?: boolean; display_priority?: number;
}) =>
  fetchJSON<{ role: Role }>('/api/admin/roles', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteRole = (roleId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' });

// Admin — feature flags (#620, ADR 0029); the shapes live in @/lib/adminFlags
export type { AdminFlag, AdminFlagTarget, FlagRule } from '@/lib/adminFlags';

export const adminListFlags = () => fetchJSON<{ flags: AdminFlag[] }>('/api/admin/flags');

export const adminUpdateFlag = (
  key: string,
  body: { default_variant?: string; rollout_percent?: number; rollout_variant?: string | null },
) =>
  fetchJSON<{ flag: AdminFlag }>(`/api/admin/flags/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });

export const adminUpsertFlagTarget = (
  key: string,
  body: { target_type: 'user' | 'role'; target_id: string; variant: string },
) =>
  fetchJSON<{ flag: AdminFlag }>(`/api/admin/flags/${encodeURIComponent(key)}/targets`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const adminDeleteFlagTarget = (key: string, type: 'user' | 'role', id: string) =>
  fetchJSON<{ flag: AdminFlag }>(
    `/api/admin/flags/${encodeURIComponent(key)}/targets/${type}/${encodeURIComponent(id)}`,
    { method: 'DELETE' },
  );

export const adminExplainFlag = (key: string, userId: string) =>
  fetchJSON<FlagRule>(
    `/api/admin/flags/${encodeURIComponent(key)}/explain?user_id=${encodeURIComponent(userId)}`,
  );

export const adminListRoleCosmetics = (roleId: string) =>
  fetchJSON<{ links: { role_id: string; cosmetic_id: string }[] }>(
    `/api/admin/roles/${encodeURIComponent(roleId)}/cosmetics`,
  );

export const adminLinkRoleCosmetic = (roleId: string, cosmeticId: string) =>
  fetchJSON<{ linked: boolean }>('/api/admin/roles/cosmetics', {
    method: 'POST',
    body: JSON.stringify({ role_id: roleId, cosmetic_id: cosmeticId }),
  });

export const adminUnlinkRoleCosmetic = (roleId: string, cosmeticId: string) =>
  fetchJSON<{ unlinked: boolean }>('/api/admin/roles/cosmetics', {
    method: 'DELETE',
    body: JSON.stringify({ role_id: roleId, cosmetic_id: cosmeticId }),
  });

// Admin — achievements
export const adminListAchievements = () =>
  fetchJSON<{ achievements: Achievement[] }>('/api/admin/achievements');

export const adminCreateAchievement = (payload: {
  name: string; slug: string; description?: string | null; icon?: string | null;
  category: AchievementCategory; rarity: RarityTier; is_secret?: boolean;
}) =>
  fetchJSON<{ achievement: Achievement }>('/api/admin/achievements', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteAchievement = (achievementId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/achievements/${encodeURIComponent(achievementId)}`, { method: 'DELETE' });

export const adminGrantAchievement = (userId: string, achievementId: string) =>
  fetchJSON<{ granted: boolean }>('/api/admin/achievements/grant', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, achievement_id: achievementId }),
  });

export const adminListTriggers = (achievementId: string) =>
  fetchJSON<{ triggers: AchievementTrigger[] }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/triggers`,
  );

export const adminCreateTrigger = (payload: {
  achievement_id: string; trigger_type: string; trigger_threshold: number;
}) =>
  fetchJSON<{ trigger: AchievementTrigger }>('/api/admin/achievements/triggers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminUpdateTrigger = (triggerId: string, patch: Partial<{ trigger_type: string; trigger_threshold: number }>) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/achievements/triggers/${encodeURIComponent(triggerId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const adminDeleteTrigger = (triggerId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/achievements/triggers/${encodeURIComponent(triggerId)}`, { method: 'DELETE' });

export const adminListAchievementCosmetics = (achievementId: string) =>
  fetchJSON<{ links: { achievement_id: string; cosmetic_id: string }[] }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/cosmetics`,
  );

export const adminLinkAchievementCosmetic = (achievementId: string, cosmeticId: string) =>
  fetchJSON<{ linked: boolean }>('/api/admin/achievements/cosmetics', {
    method: 'POST',
    body: JSON.stringify({ achievement_id: achievementId, cosmetic_id: cosmeticId }),
  });

export const adminUnlinkAchievementCosmetic = (achievementId: string, cosmeticId: string) =>
  fetchJSON<{ unlinked: boolean }>('/api/admin/achievements/cosmetics', {
    method: 'DELETE',
    body: JSON.stringify({ achievement_id: achievementId, cosmetic_id: cosmeticId }),
  });

// Admin — cosmetics
export const adminListCosmetics = () =>
  fetchJSON<{ cosmetics: Cosmetic[] }>('/api/admin/cosmetics');

export const adminCreateCosmetic = (payload: {
  type: CosmeticType; name: string; slug: string;
  asset_url?: string | null; css_value?: string | null;
  rarity: RarityTier; unlock_source?: string | null;
}) =>
  fetchJSON<{ cosmetic: Cosmetic }>('/api/admin/cosmetics', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteCosmetic = (cosmeticId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/cosmetics/${encodeURIComponent(cosmeticId)}`, { method: 'DELETE' });

// Admin — allowlist
export const adminListAllowlist = () =>
  fetchJSON<{ emails: AllowlistEmail[] }>('/api/admin/allowlist');

export const adminApproveAllowlist = (email: string) =>
  fetchJSON<{ email: AllowlistEmail }>('/api/admin/allowlist/approve', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

export const adminRevokeAllowlist = (email: string) =>
  fetchJSON<{ email: AllowlistEmail }>('/api/admin/allowlist/revoke', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

/** Approve 1..500 addresses at once; each gets the "you're in" email server-side. */
export const adminApproveAllowlistBulk = (emails: string[]) =>
  fetchJSON<{ approved: number; emails: AllowlistEmail[] }>('/api/admin/allowlist/approve-bulk', {
    method: 'POST',
    body: JSON.stringify({ emails }),
  });

// Admin — email (Resend)
export const adminEmailStatus = () =>
  fetchJSON<EmailStatus>('/api/admin/email/status');

export const adminEmailAudiences = () =>
  fetchJSON<{ audiences: EmailAudience[] }>('/api/admin/email/audiences');

/** Renders the draft exactly as it would go out; sends and records nothing. */
export const adminPreviewBroadcast = (payload: { subject: string; body: string }) =>
  fetchJSON<EmailBroadcastPreview>('/api/admin/email/broadcasts/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

/** Sends the draft to the signed-in admin only. */
export const adminSendTestBroadcast = (payload: { subject: string; body: string }) =>
  fetchJSON<{ status: string; to: string }>('/api/admin/email/broadcasts/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

/** 202: the broadcast row comes back as `sending`; delivery continues in the background. */
export const adminSendBroadcast = (payload: { subject: string; body: string; audience: EmailAudienceKey }) =>
  fetchJSON<{ broadcast: EmailBroadcast }>('/api/admin/email/broadcasts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

/** Newest first. */
export const adminListBroadcasts = () =>
  fetchJSON<{ broadcasts: EmailBroadcast[] }>('/api/admin/email/broadcasts');

/** Re-run a stalled/failed/partial broadcast through the per-recipient dedupe (202). */
export const adminResumeBroadcast = (id: string) =>
  fetchJSON<{ broadcast: EmailBroadcast }>(`/api/admin/email/broadcasts/${encodeURIComponent(id)}/resume`, {
    method: 'POST',
  });

// Admin — audit
export const adminAuditLog = (params?: {
  page?: number; page_size?: number; action?: string; target_type?: string; actor_id?: string;
}) => {
  const qp = new URLSearchParams();
  if (params?.page) qp.set('page', String(params.page));
  if (params?.page_size) qp.set('page_size', String(params.page_size));
  if (params?.action) qp.set('action', params.action);
  if (params?.target_type) qp.set('target_type', params.target_type);
  if (params?.actor_id) qp.set('actor_id', params.actor_id);
  const suffix = qp.toString() ? `?${qp.toString()}` : '';
  return fetchJSON<{ entries: AdminAuditEntry[]; total: number; page: number; page_size: number }>(
    `/api/admin/audit${suffix}`,
  );
};

// Admin — analytics
export const adminAnalyticsOverview = () =>
  fetchJSON<AnalyticsOverview>('/api/admin/analytics/overview');

// Admin — analytics rollups (#121, over the #120 API). Params the caller
// leaves unset are omitted so the backend defaults stay server-owned
// (last 30 days, group_by=feature, no series).
const analyticsQuery = (params?: Record<string, string | number | undefined>) => {
  const qp = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== '') qp.set(k, String(v));
  }
  const s = qp.toString();
  return s ? `?${s}` : '';
};

export const adminUsageSummary = (params?: { from?: string; to?: string; bucket?: AnalyticsBucket }) =>
  fetchJSON<UsageSummaryData>(`/api/admin/analytics/usage/summary${analyticsQuery(params)}`);

export const adminUsageByUser = (params?: { from?: string; to?: string; limit?: number; offset?: number }) =>
  fetchJSON<UsageByUserData>(`/api/admin/analytics/usage/by-user${analyticsQuery(params)}`);

export const adminLlmCost = (params?: {
  from?: string; to?: string; group_by?: LlmCostGroupBy; bucket?: AnalyticsBucket;
}) =>
  fetchJSON<LlmCostData>(`/api/admin/analytics/llm/cost${analyticsQuery(params)}`);

export const adminErrors = (params?: {
  from?: string; to?: string; limit?: number; offset?: number; bucket?: AnalyticsBucket;
}) =>
  fetchJSON<ErrorsPageData>(`/api/admin/analytics/errors${analyticsQuery(params)}`);

// spec §10 / A110: the learning loop's KPIs, gates and BKT calibration
export const adminLearningLoopKpis = (params?: { from?: string; to?: string }) =>
  fetchJSON<LearningLoopKpisData>(`/api/admin/analytics/learning-loop${analyticsQuery(params)}`);

// Admin — learning-loop check-item review queue (spec §13 A113), the human
// audit of its keys (A124) and the empirical item statistics (A131); the wire
// types and what each field means live in adminCheckItemTypes.ts.
export type * from '@/lib/adminCheckItemTypes';
export const adminCheckItemQueue = () =>
  fetchJSON<AdminCheckItemQueue>('/api/admin/check-items/queue');
/** `restored`: the item was held (a quarantine, A123, or a key hold, A124)
 *  and the approval serves it to students again. */
export const adminApproveCheckItem = (itemId: string) =>
  fetchJSON<{ id: string; status: 'approved'; restored: boolean }>(
    `/api/admin/check-items/${encodeURIComponent(itemId)}/approve`,
    { method: 'POST' },
  );
/** Spec §13 A123: a retire voids every student's results on the question
 *  (`voided` rows, `students` recomputed), then deletes it (`items` rows). */
export const adminRetireCheckItem = (itemId: string) =>
  fetchJSON<{ id: string; status: 'retired'; items: number; students: number; voided: number }>(
    `/api/admin/check-items/${encodeURIComponent(itemId)}/retire`,
    { method: 'POST' },
  );

export const adminCheckItemAuditSample = (courseId: string, n?: number) =>
  fetchJSON<AdminAuditSample>(
    `/api/admin/check-items/audit/sample?course_id=${encodeURIComponent(courseId)}` +
      (n ? `&n=${n}` : ''),
  );
export const adminAuditCheckItem = (itemId: string, verdict: CheckItemAuditVerdict) =>
  fetchJSON<{ id: string; verdict: CheckItemAuditVerdict; key_status: CheckItemKeyStatus; held: boolean }>(
    `/api/admin/check-items/${encodeURIComponent(itemId)}/audit`,
    { method: 'POST', body: JSON.stringify({ verdict }) },
  );

export const adminCheckItemStats = (courseId: string) =>
  fetchJSON<AdminItemStatsReport>(`/api/admin/check-items/stats?course_id=${encodeURIComponent(courseId)}`);

// Careers
export const submitJobApplication = async (data: {
  position: string;
  full_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  portfolio_link?: string;
  resume?: File | null;
}): Promise<{ ok: boolean; id: string | null }> => {
  const formData = new FormData();
  formData.append('position', data.position);
  formData.append('full_name', data.full_name);
  formData.append('email', data.email);
  formData.append('phone', data.phone);
  formData.append('linkedin_url', data.linkedin_url);
  if (data.portfolio_link) formData.append('portfolio_link', data.portfolio_link);
  if (data.resume) formData.append('resume', data.resume);

  const res = await fetch(`${API_URL}/api/careers/apply`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
};

/**
 * Read a File as a base64 string (no data-URL prefix). Resolves with
 * just the encoded bytes so the JSON payload is the smallest possible
 * shape the server needs.
 */
function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is a data URL like "data:image/png;base64,iVBORw0K..."
      const result = reader.result as string;
      const comma = result.indexOf(',');
      resolve(comma === -1 ? result : result.slice(comma + 1));
    };
    reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

// Mirrors backend/config.py::MAX_AVATAR_SIZE. Kept as a const so the
// guard below doesn't depend on Settings.tsx remembering to check
// size first — every caller of uploadAvatar gets the same protection.
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

export const uploadAvatar = async (userId: string, file: File): Promise<{ avatar_url: string }> => {
  // Size-check BEFORE the base64 encode. Reading a 50 MB file just to
  // throw it out is wasted CPU + memory. Settings.tsx already
  // pre-checks size for the toast UX, but a future caller (admin
  // bulk tool, recovery script) could easily bypass that and we'd
  // still want the guard.
  if (file.size > MAX_AVATAR_BYTES) {
    throw new Error(
      `That file is ${(file.size / 1024 / 1024).toFixed(1)} MB — max is ${MAX_AVATAR_BYTES / 1024 / 1024} MB.`,
    );
  }
  // POST as JSON+base64 instead of multipart/form-data. The multipart
  // path was silently failing in some browser configurations with
  // `TypeError: Failed to fetch` (no response, request aborted before
  // reaching the server). JSON requests work in every environment
  // that already runs the rest of the profile API successfully, so
  // routing the avatar through the same shape eliminates the failure
  // class entirely.
  const file_b64 = await readFileAsBase64(file);
  return fetchJSON<{ avatar_url: string }>(`/api/profile/${encodeURIComponent(userId)}/avatar`, {
    method: 'POST',
    body: JSON.stringify({ file_b64, content_type: file.type || 'image/png' }),
  });
};

// ── Semesters ────────────────────────────────────────────────────────────────

export interface Semester {
  id: string;
  term: string;
  year: number;
  label: string;
  start_date: string;
  end_date: string;
  // year * 10 + term ordinal (Spring=1, Summer=2, Fall=3, Winter=4) — the
  // canonical ordering key; the backend serves terms sort_key-descending.
  sort_key: number;
}

export const getSemesters = () =>
  // current_term_id: the server's current term (#766) — prefer it over the
  // browser clock (lib/semesters.ts::currentTerm).
  fetchJSON<{ semesters: Semester[]; current_term_id?: string | null }>('/api/semesters');

// ── Gradebook ────────────────────────────────────────────────────────────────

export const getGradebookSummary = (userId: string, semester: string) =>
  fetchJSON<GradebookSummary>(
    `/api/gradebook/summary?user_id=${encodeURIComponent(userId)}&semester=${encodeURIComponent(semester)}`,
  );

// `semester` pins which enrollment of the course to load (a course can be
// taken in several terms, #139); omitted = the backend resolves the current
// term with its single-offering fallback.
export const getGradebookCourse = (userId: string, courseId: string, semester?: string) =>
  fetchJSON<GradebookCourse>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}?user_id=${encodeURIComponent(userId)}` +
      (semester ? `&semester=${encodeURIComponent(semester)}` : ''),
  );

// Credit-weighted GPA. Without `semester`: the cumulative/transcript report
// across all terms (scope "cumulative"); with it: that one term.
export const getGpa = (userId: string, semester?: string) =>
  fetchJSON<GpaReport>(
    `/api/gradebook/gpa?user_id=${encodeURIComponent(userId)}` +
      (semester ? `&semester=${encodeURIComponent(semester)}` : ''),
  );

// Course-keyed gradebook MUTATIONS below take the same optional `semester`
// (term-label body field, matching the backend body models) as
// getGradebookCourse: the backend resolves (course, semester) to ONE
// enrollment, and without the term a write from an archived term's page
// would silently land on the current term's enrollment (#139/#468).
// Id-keyed calls (deleteCategory, update/deleteGradedAssignment) resolve by
// row ownership and don't need it. `JSON.stringify` drops an undefined
// `semester`, so the wire format is unchanged when unset.
export const createCategory = (
  userId: string,
  courseId: string,
  name: string,
  weight: number,
  semester?: string,
) =>
  fetchJSON<{ category: GradeCategory }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/categories`,
    { method: 'POST', body: JSON.stringify({ user_id: userId, semester, name, weight }) },
  );

export const bulkUpdateCategories = (
  userId: string,
  courseId: string,
  categories: { id?: string; name: string; weight: number; sort_order: number; drop_lowest: number }[],
  semester?: string,
) =>
  fetchJSON<{ categories: GradeCategory[] }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/categories`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, semester, categories }) },
  );

export const deleteCategory = (userId: string, categoryId: string) =>
  fetchJSON<{ deleted: true }>(
    `/api/gradebook/categories/${encodeURIComponent(categoryId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const createGradedAssignment = (
  userId: string,
  courseId: string,
  fields: Partial<Omit<GradedAssignment, 'id' | 'course_id' | 'source'>> & { title: string },
  semester?: string,
) =>
  fetchJSON<{ assignment: GradedAssignment }>('/api/gradebook/assignments', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, course_id: courseId, semester, ...fields }),
  });

export const updateGradedAssignment = (
  userId: string,
  assignmentId: string,
  fields: Partial<Omit<GradedAssignment, 'id' | 'course_id' | 'source'>>,
) =>
  fetchJSON<{ updated: boolean }>(
    `/api/gradebook/assignments/${encodeURIComponent(assignmentId)}`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, ...fields }) },
  );

export const deleteGradedAssignment = (userId: string, assignmentId: string) =>
  fetchJSON<{ deleted: true }>(
    `/api/gradebook/assignments/${encodeURIComponent(assignmentId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const setLetterScale = (
  userId: string,
  courseId: string,
  scale: LetterScaleTier[] | null,
  semester?: string,
) =>
  fetchJSON<{ updated: true; letter_scale: LetterScaleTier[] | null }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/scale`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, semester, scale }) },
  );

export async function setCurveSettings(
  userId: string,
  courseId: string,
  settings: {
    curve_mode?: "raw" | "curved";
    curve_avg_target?: number | null;
    curve_sd_delta?: number | null;
    curve_final_mean?: number | null;
    curve_final_sd?: number | null;
  },
  semester?: string,
): Promise<{ updated: boolean }> {
  return fetchJSON(`/api/gradebook/courses/${encodeURIComponent(courseId)}/curve`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, semester, ...settings }),
  });
}

export const applySyllabus = (payload: {
  userId: string;
  courseId: string;
  docId: string;
  categories: { name: string; weight: number; sort_order: number }[];
  assignments: { title: string; due_date: string | null; assignment_type: string | null; notes: string | null }[];
}) =>
  fetchJSON<{ course: GradebookCourse }>('/api/gradebook/syllabus/apply', {
    method: 'POST',
    body: JSON.stringify({
      user_id: payload.userId,
      course_id: payload.courseId,
      doc_id: payload.docId,
      categories: payload.categories,
      assignments: payload.assignments,
    }),
  });

// Typed helper for syllabus uploads — wraps the existing FormData-based
// uploadDocument and narrows the response. Existing callers of uploadDocument
// remain untouched.
export interface UploadSyllabusResponse {
  id: string;
  doc_id?: string;
  category: string;
  summary: string | null;
  categories: ExtractedSyllabusCategory[];
  assignments: { title: string; due_date: string | null; assignment_type: string | null; notes: string | null }[];
}
export const uploadSyllabus = (input: {
  userId: string;
  courseId: string;
  file: File;
}): Promise<UploadSyllabusResponse> => {
  const fd = new FormData();
  fd.append('user_id', input.userId);
  fd.append('course_id', input.courseId);
  fd.append('category', 'syllabus');
  fd.append('file', input.file);
  return uploadDocument(fd);
};

// ── Gradescope sync ────────────────────────────────────────────────────────

export type GradescopeAuthMode = 'password' | 'cookies';

/** How the stored Gradescope session was obtained. A password is used for one
 *  sign-in and never kept, so a `password` user re-enters it when the session
 *  expires (components/Gradebook/gradescopeState.ts words that). */
export type GradescopeConnectedVia = 'password' | 'bu_sso' | 'cookies';

/** #770: `disconnected` = no saved credentials (course links may survive);
 *  `needs_reauth` = saved, but Gradescope rejected them on the last login. */
export type GradescopeConnectionState = 'disconnected' | 'needs_reauth' | 'connected';

/** Machine code for the last sync attempt's failure (null = it succeeded). */
export type GradescopeSyncError = 'auth_failed' | 'fetch_failed' | 'write_failed' | 'partial_write';

export interface GradescopeStatus {
  has_credentials: boolean;
  auth_mode: GradescopeAuthMode | null;
  /** Optional: a backend before 2026-11-16 does not send it. */
  connected_via?: GradescopeConnectedVia | null;
  last_synced_at: string | null;
  credentials_updated_at?: string | null;
  // Optional so a backend without the #770 migration still type-checks; read
  // it through components/Gradebook/gradescopeState.ts, which derives it.
  state?: GradescopeConnectionState;
  connected?: boolean;
  needs_reauth?: boolean;
  last_attempt_at?: string | null;
  last_sync_error?: GradescopeSyncError | null;
}

export type GradescopeConnectInput =
  | { auth_mode: 'password'; email: string; password: string }
  | {
      auth_mode: 'cookies';
      gradescope_session: string;
      signed_token?: string;
    };

export interface GradescopeCourse {
  id: string;
  name: string;
  full_name: string;
  semester: string;
  year: string;
  num_assignments: string;
}

export interface GradescopeLink {
  id: string;
  sapling_course_id: string;
  gradescope_course_id: string;
  last_synced_at: string | null;
}

export interface GradescopeSyncResult {
  inserted: number;
  updated: number;
  skipped: number;
  failed: number;
}

export const getGradescopeStatus = (userId: string) =>
  fetchJSON<GradescopeStatus>(`/api/gradescope/status?user_id=${encodeURIComponent(userId)}`);

export const saveGradescopeCredentials = (
  userId: string,
  input: GradescopeConnectInput,
) =>
  fetchJSON<{ ok: true }>(`/api/gradescope/credentials`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, ...input }),
  });

/** Live BU SSO + Duo via headless Chromium on the backend. Long-running:
 *  the request stays open until the user taps Approve on their phone, or
 *  the server-side timeout fires (default 120s). */
export const connectGradescopeViaBuSso = (
  userId: string,
  buUsername: string,
  buPassword: string,
  duoTimeoutSeconds = 120,
) =>
  fetchJSON<{ ok: true }>(`/api/gradescope/credentials/bu-sso`, {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      bu_username: buUsername,
      bu_password: buPassword,
      duo_timeout_seconds: duoTimeoutSeconds,
    }),
  });

export const deleteGradescopeCredentials = (userId: string) =>
  fetchJSON<{ ok: true }>(
    `/api/gradescope/credentials?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const listGradescopeCourses = (userId: string) =>
  fetchJSON<{ courses: GradescopeCourse[] }>(
    `/api/gradescope/courses?user_id=${encodeURIComponent(userId)}`,
  );

export const listGradescopeLinks = (userId: string, semester?: string) =>
  fetchJSON<{ links: GradescopeLink[] }>(
    `/api/gradescope/links?user_id=${encodeURIComponent(userId)}${semester ? `&semester=${encodeURIComponent(semester)}` : ''}`,
  );

export const linkGradescopeCourse = (
  userId: string,
  saplingCourseId: string,
  gradescopeCourseId: string,
  semester?: string,
) =>
  fetchJSON<{ link: GradescopeLink | null }>(`/api/gradescope/link`, {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      sapling_course_id: saplingCourseId,
      gradescope_course_id: gradescopeCourseId,
      ...(semester ? { semester } : {}),
    }),
  });

export const unlinkGradescopeCourse = (userId: string, saplingCourseId: string, semester?: string) =>
  fetchJSON<{ ok: true }>(
    `/api/gradescope/link/${encodeURIComponent(saplingCourseId)}?user_id=${encodeURIComponent(userId)}${semester ? `&semester=${encodeURIComponent(semester)}` : ''}`,
    { method: 'DELETE' },
  );

/** A Gradescope sync still running on the job queue (#116, `jobs_queue` on):
 *  POST /sync answers 202 with this once it outlasts the server's wait, and
 *  so does GET /sync/{course}/status until the sync ends. */
export interface GradescopeSyncPending {
  pending: true;
  sync_id: string;
  stage: string;
  detail?: string;
}

export const isGradescopeSyncPending = (value: unknown): value is GradescopeSyncPending =>
  typeof value === 'object' && value !== null && (value as { pending?: unknown }).pending === true;

const gradescopeSyncPath = (userId: string, saplingCourseId: string, semester?: string, suffix = '') =>
  `/api/gradescope/sync/${encodeURIComponent(saplingCourseId)}${suffix}?user_id=${encodeURIComponent(userId)}${semester ? `&semester=${encodeURIComponent(semester)}` : ''}`;

/** The latest queued sync of a course: pending while it runs, then exactly
 *  what the POST would have answered (the counts, or the same typed error). */
export const getGradescopeSyncStatus = (userId: string, saplingCourseId: string, semester?: string) =>
  fetchJSON<GradescopeSyncResult | GradescopeSyncPending>(
    gradescopeSyncPath(userId, saplingCourseId, semester, '/status'),
  );

export const GRADESCOPE_SYNC_POLL_MS = 3000;
/** ~10 minutes of polling before giving up with the "still running" error. */
const GRADESCOPE_SYNC_MAX_POLLS = 200;

export interface GradescopeSyncOptions {
  /** Called once when the server says the sync is still running (a 202, or
   *  its 504 "still running" answer); polling for the outcome follows. */
  onPending?: () => void;
  pollMs?: number;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Sync a linked course. Inline (flag off) this is one POST, unchanged. A
 *  queued sync that outlasts the server's wait answers 202 (or 504); the sync
 *  keeps running, so this polls the status route until it ends and resolves
 *  or rejects exactly as the POST would have. */
export async function syncGradescopeCourse(
  userId: string,
  saplingCourseId: string,
  semester?: string,
  options: GradescopeSyncOptions = {},
): Promise<GradescopeSyncResult> {
  let stillRunning: ApiError;
  try {
    const res = await fetchJSON<GradescopeSyncResult | GradescopeSyncPending>(
      gradescopeSyncPath(userId, saplingCourseId, semester),
      { method: 'POST' },
    );
    if (!isGradescopeSyncPending(res)) return res;
    const detail = res.detail || 'This Gradescope sync is taking longer than usual.';
    stillRunning = new ApiError(JSON.stringify({ detail }), 504, { body: { detail } });
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 504) throw err;
    stillRunning = err;
  }
  options.onPending?.();
  const pollMs = options.pollMs ?? GRADESCOPE_SYNC_POLL_MS;
  for (let i = 0; i < GRADESCOPE_SYNC_MAX_POLLS; i++) {
    await sleep(pollMs);
    let status: GradescopeSyncResult | GradescopeSyncPending;
    try {
      status = await getGradescopeSyncStatus(userId, saplingCourseId, semester);
    } catch (err) {
      if (!(err instanceof ApiError)) continue; // a network blip: poll again
      // Nothing staged (a proxy timeout on the inline path): keep the 504.
      if (err.status === 404) throw stillRunning;
      throw err; // the sync's own outcome, answered as the POST would have
    }
    if (!isGradescopeSyncPending(status)) return status;
  }
  throw stillRunning;
}

// ── Notes ──────────────────────────────────────────────────────────────────

export const listNotes = (userId: string, courseId?: string) => {
  const qs = courseId ? `?course_id=${encodeURIComponent(courseId)}` : '';
  return fetchJSON<{ notes: Note[] }>(`/api/notes/user/${userId}${qs}`);
};

export const createNote = (
  userId: string,
  courseId: string,
  title = '',
  body = '',
  tags: string[] = [],
) =>
  fetchJSON<Note>('/api/notes', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, course_id: courseId, title, body, tags }),
  });

export const getNote = (noteId: string, userId: string) =>
  fetchJSON<Note>(`/api/notes/${noteId}?user_id=${encodeURIComponent(userId)}`);

export const patchNote = (
  noteId: string,
  userId: string,
  patch: Partial<Pick<Note, 'title' | 'body' | 'tags' | 'course_id'>>,
  // `keepalive` lets a final autosave survive a page unload (tab close /
  // navigation) instead of being cancelled mid-flight.
  opts?: { keepalive?: boolean },
) =>
  fetchJSON<Note>(`/api/notes/${noteId}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, ...patch }),
    keepalive: opts?.keepalive,
  });

export const deleteNote = (noteId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/notes/${noteId}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const listNoteConcepts = (noteId: string, userId: string) =>
  fetchJSON<{ concepts: LinkedConcept[] }>(
    `/api/notes/${noteId}/concepts?user_id=${encodeURIComponent(userId)}`,
  );

export const linkNoteConcept = (noteId: string, userId: string, conceptNodeId: string) =>
  fetchJSON<{ linked: boolean }>(`/api/notes/${noteId}/concepts`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, concept_node_id: conceptNodeId }),
  });

export const unlinkNoteConcept = (noteId: string, userId: string, conceptNodeId: string) =>
  fetchJSON<{ unlinked: boolean }>(
    `/api/notes/${noteId}/concepts/${encodeURIComponent(conceptNodeId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const summarizeNote = (noteId: string, userId: string) =>
  // docs/safety/crisis-support.md: a crisis answer carries `crisis_support` and no summary.
  fetchJSON<{ summary?: string } & WithCrisisSupport>(`/api/notes/${noteId}/summarize`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const extractNoteConcepts = (noteId: string, userId: string) =>
  // `withheld` (spec §13 A125): names held back for giving away an open check's answer;
  // a crisis-support response carries the card instead (no concepts, nothing linked),
  // or beside the result on a crisis line in the note (`crisis_support_alongside`)
  fetchJSON<{ concepts?: string[]; linked?: number; withheld?: number } & WithCrisisSupport>(
    `/api/notes/${noteId}/extract-concepts`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );

export const noteChat = (noteId: string, userId: string, message: string) =>
  fetchJSON<{ reply: string } & WithCrisisSupport>(`/api/notes/${noteId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, message }),
  });

export const sendNoteToTutor = (noteId: string, userId: string) =>
  fetchJSON<{ topic?: string; course_id?: string; preface?: string } & WithCrisisSupport>(
    `/api/notes/${noteId}/send-to-tutor`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );

export const generateQuizFromNote = (noteId: string, userId: string) =>
  fetchJSON<{ concept_node_id: string; concept_name: string }>(
    `/api/notes/${noteId}/generate-quiz`,
    { method: 'POST', body: JSON.stringify({ user_id: userId }) },
  );

// ── Gamification ─────────────────────────────────────────────────────────────
export const fetchGamificationMe = (userId: string) =>
  fetchJSON<GamificationMe>(`/api/gamification/me?user_id=${encodeURIComponent(userId)}`);

export const fetchLeaderboard = (userId: string, scope: 'everyone' | 'friends' | 'school') =>
  fetchJSON<{ rows: LeaderboardRow[]; you: LeaderboardRow | null; resets_at: string }>(
    `/api/gamification/leaderboard?user_id=${encodeURIComponent(userId)}&scope=${scope}`);

export const fetchActivity = (userId: string) =>
  fetchJSON<ActivityData>(`/api/gamification/activity?user_id=${encodeURIComponent(userId)}`);

// ── Friends ──────────────────────────────────────────────────────────────────
export const fetchFriends = (userId: string) =>
  fetchJSON<{ friends: Friend[] }>(`/api/social/friends/${encodeURIComponent(userId)}`);

export const fetchFriendRequests = (userId: string) =>
  fetchJSON<{
    incoming: { id: string; from_user_id: string; name: string; created_at: string }[];
    outgoing: { id: string; to_user_id: string; name: string; created_at: string }[];
  }>(`/api/social/friends/requests?user_id=${encodeURIComponent(userId)}`);

export const sendFriendRequest = (fromUserId: string, toUserId: string) =>
  fetchJSON<{ request: { id: string } }>('/api/social/friends/request', {
    method: 'POST',
    body: JSON.stringify({ from_user_id: fromUserId, to_user_id: toUserId }),
  });

export const acceptFriendRequest = (requestId: string, userId: string) =>
  fetchJSON<{ accepted: boolean }>(
    `/api/social/friends/requests/${encodeURIComponent(requestId)}/accept?user_id=${encodeURIComponent(userId)}`,
    { method: 'POST' });

export const declineFriendRequest = (requestId: string, userId: string) =>
  fetchJSON<{ declined: boolean }>(
    `/api/social/friends/requests/${encodeURIComponent(requestId)}/decline?user_id=${encodeURIComponent(userId)}`,
    { method: 'POST' });

export const removeFriend = (friendId: string, userId: string) =>
  fetchJSON<{ removed: boolean }>(
    `/api/social/friends/${encodeURIComponent(friendId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' });

// ── Admin — XP rules and icons ───────────────────────────────────────────────
export const adminListXpRules = () =>
  fetchJSON<{ rules: { key: string; label: string; amount: number; enabled: boolean }[] }>(
    '/api/admin/xp-rules');

export const adminUpdateXpRule = (key: string, patch: { amount?: number; enabled?: boolean }) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/xp-rules/${encodeURIComponent(key)}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  });

export const adminUpdateAchievement = (
  achievementId: string,
  patch: Partial<Pick<Achievement, 'name' | 'description' | 'category' | 'rarity' | 'is_secret'>>
    & { xp_reward?: number; sort_order?: number; status?: 'draft' | 'live' },
) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/achievements/${encodeURIComponent(achievementId)}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  });

export const adminUploadAchievementIcon = (
  achievementId: string, fileBase64: string, contentType: string,
) =>
  fetchJSON<{ icon_url: string }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/icon`, {
      method: 'POST',
      body: JSON.stringify({ file_base64: fileBase64, content_type: contentType }),
    });

// Mirrors backend/services/storage_service.py::ALLOWED_CONTENT_TYPES.
export const COSMETIC_ASSET_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];

/**
 * Upload an avatar-frame/banner image through the backend
 * (`POST /api/admin/cosmetics/assets`, admin-only, service-role storage).
 * The admin screen used to write to a storage bucket from the browser with
 * the public anon key; nothing in the browser writes to storage now.
 */
export const adminUploadCosmeticAsset = async (file: File): Promise<{ asset_url: string }> => {
  if (file.size > MAX_AVATAR_BYTES) {
    throw new Error(
      `That file is ${(file.size / 1024 / 1024).toFixed(1)} MB — max is ${MAX_AVATAR_BYTES / 1024 / 1024} MB.`,
    );
  }
  if (!COSMETIC_ASSET_TYPES.includes(file.type)) {
    throw new Error('Unsupported image type. Use JPEG, PNG, WebP or GIF.');
  }
  const file_base64 = await readFileAsBase64(file);
  return fetchJSON<{ asset_url: string }>('/api/admin/cosmetics/assets', {
    method: 'POST',
    body: JSON.stringify({ file_base64, content_type: file.type }),
  });
};

// #764: the sender withdraws a pending friend request.
export const cancelFriendRequest = (requestId: string, userId: string) =>
  fetchJSON<{ cancelled: boolean }>(
    `/api/social/friends/requests/${encodeURIComponent(requestId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' });
