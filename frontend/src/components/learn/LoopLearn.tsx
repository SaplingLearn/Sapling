"use client";
// Learning loop (PKG-13): the loop-path Learn screen (build phase: the
// staff/QA toggle; after launch: every student — spec §13 A14). The flow is
// probe → plan → teach ⇄ check → feedback → close, and the phase is
// SERVER-DRIVEN: every change comes from a loop route's response, a stream
// event, a listed session or GET /status (`reduceLoopEvent` never advances it
// on its own). No model toggle and no tier preference is sent (A15/A26).
// Resume before probe: a reload of /learn never starts a probe while an open
// loop session exists (§11.3), and a resume only READS (GET /status restores a
// check's pose). The attempt box grades only through /check/answer/stream,
// never as a chat turn (A16). Spec:
// docs/superpowers/specs/2026-09-26-learning-loop-design.md §9, §11.3; routes:
// backend/routes/learn_loop.py.
import React, { useCallback, useEffect, useId, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { FullHeightScreen } from "../FullHeightScreen";
import { DisclaimerModal } from "../DisclaimerModal";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { ChatPanel, PageTurn, type ChatMsg } from "../chat/ChatPanel";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { extractErrorDetail, humanizeError } from "@/lib/errorMessage";
import { apiToGraphNode, type GraphEdge, type GraphNode } from "@/lib/data";
import type { GraphEdge as ApiEdge, GraphNode as ApiNode } from "@/lib/types";
import {
  answerLoopProbe,
  approveLoopPlan,
  budgetPauseOf,
  closeLoopSession,
  getCourses,
  getGraph,
  getLoopPlan,
  getLoopSessionStatus,
  listLoopSessionsFor,
  nextLoopCheck,
  nextLoopProbe,
  postLoopAttempt,
  postLoopSelfExplain,
  reportCheckItem,
  requestLoopHint,
  requestLoopHintTurn,
  resumeSession,
  setLoopGoal,
  startLoopSession,
  streamLoopChat,
  streamLoopCheckAnswer,
  streamLoopPrequestionAnswer,
  submitLoopRating,
  type EnrolledCourse,
  type LoopCheckAnswer,
  type LoopCheckItem,
  type LoopCloseResponse,
  type LoopGoal,
  type LoopGoalProgress,
  type LoopDiagnosis,
  type LoopLearningScope,
  type LoopOpenSession,
  type LoopPanelConcept,
  type LoopPendingGrade,
  type LoopPhase,
  type LoopPlanConcept,
  type LoopPrequestion,
  type LoopPrequestionGuess,
  type LoopProbeItem,
  type LoopProbeAnswerResult,
  type LoopRating,
  type LoopReportReason,
  type LoopSelfExplain,
  type LoopSessionStatus,
  type LoopTurnResult,
  type StreamChatHandlers,
  type StudentConfidence,
} from "@/lib/api";
import { useFlag } from "@/context/FlagsContext";
import { useStudyNavShown } from "../useRetentionNav";
import { forgetEndedSession, noteLearningSession, useFeedbackHold } from "@/lib/feedbackPacing";
import { BudgetPausedBanner, tutorPauseMessage } from "./BudgetPausedBanner";
import { checkIsOpen, initialLoopState, reduceLoopEvent } from "./loopState";
import { hasDeepLink, readDeepLink } from "./deepLink";
import styles from "./LoopLearn.module.css";
import { DiagnosisSummary, GoalEditor } from "./LearningScope";
import { planGoalReason, planKind } from "./planLabels";
import { ReportQuestion } from "./ReportQuestion";
import { CrisisSupportCard, useCrisisSupport } from "../safety/CrisisSupportCard";
import { crisisSupportIn, crisisSupportInError, takeNoteCardShown, type CrisisSupport } from "@/lib/crisisSupport";
import { ConfidenceControl } from "./ConfidenceControl";
import { OptionList } from "./OptionList";
import { PrequestionCard, renderGuess } from "./PrequestionCard";
import { SelfExplainCard } from "./SelfExplainCard";
import { retentionHref, useRetentionDue } from "@/context/RetentionDueContext";
import { Icon } from "../Icon";
import { TutorSidebar } from "./tutor/TutorSidebar";
import { LoadFailed, TutorAllSessions, TutorCourse, TutorHome, type SessionFilter } from "./tutor/TutorPages";
import { SessionPanel, type PanelConcept } from "./tutor/SessionPanel";
import { SessionMap } from "./tutor/SessionMap";
import { PhaseStepper } from "./tutor/PhaseStepper";
import { TutorDrawer } from "./tutor/TutorDrawer";
import { useTutorLayout } from "./tutor/useTutorLayout";
import { useTutorLists } from "./tutor/useTutorLists";
import { SidebarGlyph } from "./tutor/TutorIcons";
import { listedOpenTitle, mergeSessions, sessionTitle, sessionToLeave, type TutorSessionRow } from "./tutor/sessions";
import tutorStyles from "./tutor/tutor.module.css";
import { CenteredCard } from "./CenteredCard";
import { ClosePanel } from "./ClosePanel";
import { RatingPrompt } from "./RatingPrompt";
import { claimWrapUpAsk } from "./WrapUpRating";
import { checkMeNote, PREPARING_COPY } from "./checkNote";
import { withPlanHistory } from "./loopHistory";
import { dropInterruptedTurn } from "./chatRetry";
import { modalOpen } from "./modalOpen";

// ── Copy ─────────────────────────────────────────────────────────────────
const NO_CHECK_ITEMS_COPY =
  "No check items for this course yet. You can still learn with the tutor; nothing is graded until the course has items.";
// spec §13 A128: the session's course-material retrieval failed (an outage, not
// an empty result). Shown once per session, from the turn's response field —
// never a prompt change.
const MATERIALS_UNAVAILABLE_COPY =
  "Your course materials are temporarily unavailable, so answers may be less specific to your class.";
const NO_FRESH_PRACTICE_COPY = "Fresh practice questions are unavailable for these concepts in this session. You can review source material with the tutor; source review does not assess or complete your goal. Starting another session will not replenish these questions.";
const PROBE_UNAVAILABLE_COPY = "Couldn't grade that one — here's another.";
const PROBE_REFUSED_COPY = "Answer in your own words — that read as instructions to the grader.";
const CLOSED_ELSEWHERE_COPY = "This session was closed — start a new one to keep learning.";
const CONTINUE_MESSAGE = "Let's continue.";
const FEEDBACK_PENDING_DETAIL = "feedback pending; retry feedback before another check";
const FEEDBACK_PENDING_COPY = "Your answer is recorded. Retry feedback before another check.";
// spec §13 A113 (#695): the check card's "Report this question" went through
const REPORTED_COPY = "Thanks — that question is reported and won't be shown to you again. Use Check me for another.";
const WITHDRAWN_DETAIL = "check item withdrawn";
// spec §13 A139: a self-explanation reply was saved (a polite live region)
const SELF_EXPLAIN_SAVED_COPY = "Saved — thanks.";
/** Spec §13 A138: the composer's placeholder while the guess card is open. */
const PREQUESTION_COMPOSER_COPY ="Answer the question above first, or choose “No idea”.";
/** K06: a chat while a check is open only re-poses it (never graded, no reply), so the check's card is the way to answer. */
const CHECK_OPEN_COMPOSER_COPY = "Answer the question above, ask for a hint, or choose “I don't know”.";
/** routes/learn_loop.py: the prompt was superseded (a later turn closed it). */
const SELF_EXPLAIN_GONE_DETAIL = "no open self-explanation prompt";

/** Plain-English lines for POST /hint's denial reasons (routes/learn_loop.py::hint). */
const HINT_DENIED_COPY: Record<string, string> = {
  no_genuine_attempt: "Give it a real try first — write what you think in the answer box, then ask again.",
  dwell: "Stay with this step a little longer before the next hint.",
  ceiling: "That's all the help this question allows right now. Give it your best answer — you'll see the full answer after.",
  h6_gate: "The worked answer unlocks once you've tried the question yourself.",
  no_active_item: "There's no open question to hint on right now.",
};
const HINT_DENIED_FALLBACK = "No hint right now — keep working on it.";

/** 409s from POST /close while a claim is live (A60): the student retries. */
const CLOSE_RETRY_COPY: Record<string, string> = {
  "a check is being graded; close again in a moment": "A check is still being graded — close again in a moment.",
  "session close in progress": "This session is already closing — try again in a moment.",
};
/** routes/learn_loop.py `_SESSION_CLOSED`: every teaching route after the close (A60). */
const SESSION_CLOSED_DETAIL = "this session is closed";
/** routes/learn_loop.py `_ALREADY_GRADED`: the submission was graded (maybe by an earlier request). */
const ALREADY_GRADED_DETAIL = "already graded";
/** POST /check/answer(/stream) 409s (#866 A1/A2): the check this answer was for
 *  is closed and nothing was recorded (a late grade found it moved past, or the
 *  store refused the saved grade for good); the server's next step is another
 *  check, so the client selects one (/check/next). */
const CHECK_CLOSED_COPY: Record<string, string> = {
  "This check was closed while your answer was graded. Select another check to continue.":
    "That check closed while your answer was being graded, so nothing was recorded.",
  "This answer could not be recorded. Select another check to continue.":
    "Your answer to that check couldn't be recorded.",
};
/** What to tell the student when a submission's error is one of those 409s, else null. */
function checkClosedCopy(submission: boolean, status: number | undefined, detail: string | undefined): string | null {
  if (!submission || status !== 409 || !detail) return null;
  return CHECK_CLOSED_COPY[detail] ?? null;
}
/** setTimeout's ceiling (2^31 − 1 ms): a later reset time is never armed early. */
const MAX_TIMER_MS = 2_147_483_647;

const BAND_LABEL: Record<string, string> = { novice: "Getting started", develop: "Developing", profic: "Proficient" };
const TEACHING: readonly LoopPhase[] = ["teach", "check", "feedback"];

const FIELD_STYLE: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  fontSize: 14,
  lineHeight: 1.45,
  border: "1px solid var(--border)",
  borderRadius: "var(--r-md)",
  background: "var(--bg-input)",
  resize: "vertical",
  boxSizing: "border-box",
};

let msgSeq = 0;
const msgId = (prefix: string) => `${prefix}-${Date.now()}-${++msgSeq}`;
const asMsg = (role: "user" | "assistant", content: string): ChatMsg => ({ id: msgId(role), role, content });
const toChat = (rows: { id: string; role: string; content: string }[] | undefined): ChatMsg[] =>
  (rows ?? [])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content }));
/** An answer being written. `confidence` (spec §13 A127) is the student's stated
 *  confidence — null until chosen, and a skip sends none. */
type Draft = { answer: string; option: string; reason: string; confidence: StudentConfidence | null };
const EMPTY_DRAFT: Draft = { answer: "", option: "", reason: "", confidence: null };

/** The answer fields a draft submits: `confidence` only when chosen (A127). */
function draftAnswer(draft: Draft, format: string): LoopCheckAnswer {
  const a: LoopCheckAnswer = format === "mc_reason"
    ? { option: draft.option, reason: draft.reason, idk: false }
    : { answer: draft.answer, idk: false };
  return draft.confidence ? { ...a, confidence: draft.confidence } : a;
}
type HintView = { denied: string } | { reply: string } | null;
/** The Tutor's main column: a session (T4–T15), the Tutor home (T1), a course
 *  page (T2) or every session (T3). */
type TutorView = "session" | "home" | "course" | "all";


/** The phase GET /status reports for a document, in the UI's vocabulary. */
const statusPhase = (st: LoopSessionStatus) => (st.loop_phase === "teach" ? st.phase : st.loop_phase);

// ── Keyboard focus (spec §13 A135) ────────────────────────────────────────
// Every focus move runs in a layout effect, synchronously with the commit that
// shows the new content. A passive effect could still be pending when the next
// input event arrives; React then flushes it inside that event, and the focus
// change it makes dispatches a nested event that restores the controlled field
// before its new value has rendered.
/** Focus the first answer control of a check-in or check card: the textarea, or
 *  the options' tab stop (each is marked `data-answer-start`). */
const focusAnswerStart = (card: HTMLElement | null) => card?.querySelector<HTMLElement>("[data-answer-start]")?.focus();
/** Where focus goes once an action settles without new content of its own (see
 *  `focusAfter` in LoopLearn): after an answer (Continue, else the card's
 *  answer, else Check me), after a tutor turn (the chat composer), after Check
 *  me found nothing (Check me), after the plan is approved ("Start with …", else
 *  the composer), and after a check-in answer that left the item up (its answer). */
type FocusAfter = "answered" | "turn" | "check-me" | "teaching" | "probe-answer";

/** True when any flag is set: the screen's busy and visibility unions. */
const anyOf = (...flags: boolean[]): boolean => flags.some(Boolean);
/** True when every flag is set. */
const allOf = (...flags: boolean[]): boolean => flags.every(Boolean);

export function LoopLearn() {
  const { userId } = useUser();
  const toast = useToast();
  // docs/safety/crisis-support.md: an action with no conversation to answer in
  // (a session start, a goal, a probe answer, a hint attempt) shows the card here
  const {
    intercept: interceptCrisis,
    dialog: crisisDialog,
    support: crisisDialogSupport,
  } = useCrisisSupport();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const isMobile = useIsMobile();
  // spec §13 A113 (#695): "Report this question" on the check card
  const reportsOn = useFlag("item_reports") === "on";
  const [state, dispatch] = useReducer(reduceLoopEvent, undefined, initialLoopState);
  const [deepLink] = useState(() => readDeepLink(searchParams));

  // The Tutor shell (wireframes T1–T3, T17): which page the main column shows,
  // the tutor sidebar, the session panel, and the sessions they list.
  const [view, setView] = useState<TutorView>("session");
  const [courseView, setCourseView] = useState<string | null>(null);
  const [sideQuery, setSideQuery] = useState("");
  const [allQuery, setAllQuery] = useState("");
  const [allFilter, setAllFilter] = useState<SessionFilter>("all");
  const { courseIds: dueCourseIds } = useRetentionDue();
  // A link to a page a `hide_*` flag hides would only land on the dashboard
  // (NavFeatureGate): with Study or the Library hidden, those links are not shown.
  // Study reads the nav's own answer (useStudyNavShown, as TopNav and the
  // Dashboard do): no Study link until the flags are in.
  const studyVisible = useStudyNavShown();
  const libraryVisible = useFlag("hide_library") !== "on";
  const treeVisible = useFlag("hide_tree") !== "on";
  // A session picked in another course: resumed once that course's sessions list.
  const pendingResume = useRef<string | null>(null);

  // Course + sessions
  const [courses, setCourses] = useState<EnrolledCourse[] | null>(null);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [openSessions, setOpenSessions] = useState<LoopOpenSession[] | null>(null); // null = loading
  const [sessionsError, setSessionsError] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState<{ id: string; topic: string; messages: ChatMsg[] } | null>(null);
  const [starting, setStarting] = useState(false);
  // A route the current view is waiting on failed (not a budget pause): the
  // panel offers a retry instead of sitting empty.
  const [loadError, setLoadError] = useState<"start" | "probe" | "plan" | null>(null);
  // docs/safety/crisis-support.md: a session start answered with the card (no
  // session was opened) shows it where the session would be
  const [startCrisis, setStartCrisis] = useState<CrisisSupport | null>(null);
  // A chat message the budget pause answered (no reply) comes back to the
  // composer: ChatPanel applies `text` whenever `key` changes.
  const [chatDraft, setChatDraft] = useState<{ text: string; key: number }>({ text: "", key: 0 });

  // Goals are session-owned. New sessions start whole-course; typed topic text
  // never silently selects targets, and nothing is inherited across courses.
  const [goal, setGoal] = useState<LoopGoal | null>(null);
  const [goalProgress, setGoalProgress] = useState<LoopGoalProgress | null>(null);
  const [practiceUnavailable, setPracticeUnavailable] = useState<string[]>([]);
  const [diagnosis, setDiagnosis] = useState<LoopDiagnosis | null>(null);
  const [scopeReady, setScopeReady] = useState(false);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [scopeError, setScopeError] = useState(false);
  const [goalEditor, setGoalEditor] = useState(false);
  const [goalBusy, setGoalBusy] = useState(false);
  const [goalError, setGoalError] = useState<string | null>(null);
  const goalButton = useRef<HTMLButtonElement>(null);

  // Probe
  const [probeItem, setProbeItem] = useState<LoopProbeItem | null>(null);
  const [probeDraft, setProbeDraft] = useState<Draft>(EMPTY_DRAFT);
  const [probeReference, setProbeReference] = useState<string | null>(null);
  const [probeNote, setProbeNote] = useState<string | null>(null);
  const [probeCount, setProbeCount] = useState(0);
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeFinished, setProbeFinished] = useState(false); // the last answer ended the probe
  // A26: the course has no check items — or (A128) none YET: the student's upload is being drafted
  const [noCheckItems, setNoCheckItems] = useState<"none" | "preparing" | null>(null);
  // A128: this session's course materials could not be retrieved (served once per session)
  const [materialsNote, setMaterialsNote] = useState(false);

  // Plan
  const [plan, setPlan] = useState<LoopPlanConcept[] | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [planGoalVersion, setPlanGoalVersion] = useState<number | undefined>(undefined);
  const [planJustApproved, setPlanJustApproved] = useState(false);
  // The approved plan as GET /status reports it: the session panel's list after a reload
  const [approvedPlan, setApprovedPlan] = useState<{ concepts: LoopPanelConcept[]; cursor: number } | null>(null);

  // Teach / check / feedback
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<Draft>(EMPTY_DRAFT);
  const [attemptBusy, setAttemptBusy] = useState(false);
  const [hint, setHint] = useState<HintView>(null);
  const [hintBusy, setHintBusy] = useState(false);
  const [hintRetry, setHintRetry] = useState(false);
  const [checkNote, setCheckNote] = useState<string | null>(null);
  const [checkBusy, setCheckBusy] = useState(false);
  const [feedbackPending, setFeedbackPending] = useState(false);
  const [pendingGrade, setPendingGrade] = useState<LoopPendingGrade | null>(null);
  // PKG-14: the session a graded check asked to rate (done.ask_rating); one click hides it
  const [askRating, setAskRating] = useState<string | null>(null);
  // Wireframe T9: the last graded check's verdict, shown over the feedback turn
  const [verdict, setVerdict] = useState<{ verdict: string; nodeId: string | null } | null>(null);
  // Spec §13 A138: the open segment-opening guess; A139: the open "why" prompt.
  // Both are server-driven: a served turn closes them and may open new ones.
  const [prequestion, setPrequestion] = useState<LoopPrequestion | null>(null);
  /** Spec §13 A138 (review fix): an unanswered guess card holds the composer. */
  const guessCardOpen = !!prequestion && !prequestion.answered;
  const [prequestionBusy, setPrequestionBusy] = useState(false);
  const [selfExplain, setSelfExplain] = useState<LoopSelfExplain | null>(null);
  const [selfExplainBusy, setSelfExplainBusy] = useState(false);
  const [explainDraft, setExplainDraft] = useState(false); // Z60: unsent "why" text holds the chat
  const [selfExplainSaved, setSelfExplainSaved] = useState(false);

  // Close
  const [close, setClose] = useState<LoopCloseResponse | null>(null);
  const [closeBusy, setCloseBusy] = useState(false);
  const [closeNote, setCloseNote] = useState<string | null>(null);
  // The wrap-up that asks "How was that session?" (claimWrapUpAsk), and its topic
  const [wrapUpAsk, setWrapUpAsk] = useState<{ sessionId: string; topic?: string } | null>(null);

  // Knowledge map
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState(false);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({ nodes: [], edges: [] });

  // A visible session id is not readiness: resume still reads its scope and
  // may pose a probe or materialise its plan. Let those operations settle before
  // wrapping up that session, rather than racing them against /close.
  const sessionTransitionBusy = anyOf(starting, scopeLoading, probeBusy, planLoading, planBusy, goalBusy, closeBusy, !!pendingGrade);

  // A session "generation": bumped whenever the screen switches session, so a
  // response for the previous one is dropped instead of landing on the new one.
  const gen = useRef(0);
  const bootKey = useRef<string | null>(null);
  const resumePending = useRef(true); // the deep link's ?resume= is honoured once
  const topicStarted = useRef(false); // the deep link's ?topic= starts a session once
  const lastStart = useRef<{ topic?: string; mode?: string; goal?: boolean }>({}); // the start card's "Try again" repeats it
  const sessionRef = useRef<string | null>(null);
  const streamAbort = useRef<AbortController | null>(null);
  const turnEpoch = useRef(0); // a late recovery snapshot cannot undo a newer turn
  const countedAttempt = useRef<string | null>(null); // `${qh}:${text}` the server counted
  const hintEpoch = useRef(0);
  const earnedHint = useRef<{ sessionId: string; questionHash: string; rung: number } | null>(null);
  const mounted = useRef(true);
  const graphRequest = useRef(0);
  // spec §13 A135: where keyboard focus goes once an action settles (FocusAfter)
  const focusAfter = useRef<FocusAfter | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  // The sidebar and the session panel: collapse when the conversation would
  // be too narrow, keep the student's own Show/Hide, return focus (U5, F6).
  const layout = useTutorLayout(rootRef, isMobile, allOf(view === "session", !!sessionId, !readOnly));
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const continueRef = useRef<HTMLButtonElement>(null);
  const checkMeRef = useRef<HTMLButtonElement>(null);
  const teachStartRef = useRef<HTMLButtonElement>(null);
  // spec §13 A139: the reply box of a "why" prompt that replaced the Continue row
  const selfExplainRef = useRef<HTMLTextAreaElement>(null);
  const invalidateHint = useCallback(() => {
    ++hintEpoch.current;
    earnedHint.current = null;
    setHintRetry(false);
    setHintBusy(false);
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      streamAbort.current?.abort();
    };
  }, []);
  useEffect(() => {
    sessionRef.current = sessionId;
  }, [sessionId]);

  // The deep link is consumed at mount: drop it from the URL so a reload, or a
  // later session/course switch, never re-applies it (it was sticky).
  const urlCleaned = useRef(false);
  useEffect(() => {
    if (urlCleaned.current || !hasDeepLink(deepLink)) return;
    urlCleaned.current = true;
    router.replace(pathname || "/learn", { scroll: false });
  }, [deepLink, router, pathname]);

  const course = useMemo(() => courses?.find((c) => c.course_id === courseId) ?? null, [courses, courseId]);

  // Feedback pacing (lib/feedbackPacing.ts): the session on screen is the one a
  // feedback prompt counts against, and its wrap-up is what "How was that
  // session?" asks about once the student leaves /learn. Moving into another
  // session drops that marker. The row's topic is kept while it is listed: the
  // close drops it from the picker in the same render that shows the wrap-up.
  const listedTopic = openSessions?.find((s) => s.session_id === sessionId)?.topic || null;
  const lastListedTopic = useRef<{ sessionId: string; topic: string } | null>(null);
  useEffect(() => {
    if (sessionId && listedTopic) lastListedTopic.current = { sessionId, topic: listedTopic };
  }, [sessionId, listedTopic]);
  const courseName = course?.course_name;
  // The wrap-up asks "How was that session?" on its own screen (U9), so no ended
  // session is left for the shell to ask about after the student leaves /learn.
  useEffect(() => {
    if (!sessionId || readOnly) return;
    noteLearningSession(sessionId);
    forgetEndedSession();
  }, [sessionId, readOnly]);
  /** The wrap-up arrived: show it, and decide (once) whether it asks for a rating. */
  const showClose = useCallback((sid: string, r: LoopCloseResponse) => {
    setClose(r);
    const listed = lastListedTopic.current;
    const topic = (listed?.sessionId === sid ? listed.topic : courseName) || undefined;
    setWrapUpAsk(claimWrapUpAsk(sid) ? { sessionId: sid, topic } : null);
  }, [courseName]);

  const applyLearningScope = useCallback((payload: LoopLearningScope | null | undefined) => {
    if (!payload) return;
    if (payload.goal !== undefined) setGoal(payload.goal);
    if (payload.diagnosis !== undefined) setDiagnosis(payload.diagnosis);
    if (payload.goal_progress !== undefined) setGoalProgress(payload.goal_progress);
    if (payload.goal === null) setPracticeUnavailable([]);
    else if (payload.practice_unavailable_node_ids !== undefined) setPracticeUnavailable(payload.practice_unavailable_node_ids);
  }, []);
  const paused = state.budgetPause;
  const item = state.item;
  const checkOpen = checkIsOpen(state);
  const exhaustedPracticeAttempt = practiceUnavailable.some((id) => goalProgress?.attempted_node_ids.includes(id));

  // A daily (or per-minute) pause lifts at its reset time — never earlier, and
  // a session cap never (a new session starts fresh, A39). Owner question in
  // HANDOFF-13: whether a pause with no reset time should re-check on a timer.
  useEffect(() => {
    if (!paused || paused.sessionCapped || !paused.resetAt) return;
    const ms = Date.parse(paused.resetAt) - Date.now();
    if (Number.isNaN(ms) || ms > MAX_TIMER_MS) return;
    const t = setTimeout(() => dispatch({ type: "budget_clear" }), Math.max(0, ms));
    return () => clearTimeout(t);
  }, [paused]);

  // ── Knowledge map ──────────────────────────────────────────────────────
  const refreshGraph = useCallback(async () => {
    if (!userId) return;
    const request = ++graphRequest.current;
    setGraphLoading(true);
    setGraphError(false);
    try {
      const g = await getGraph(userId);
      if (!mounted.current || request !== graphRequest.current) return;
      const nodes = ((g.nodes ?? []) as ApiNode[]).map((n) => apiToGraphNode(n, courses ?? []));
      const edges = ((g.edges ?? []) as ApiEdge[]).map((e) => ({
        source: e.source as string, target: e.target as string, strength: e.strength,
      }));
      setGraph({ nodes, edges });
    } catch {
      if (mounted.current && request === graphRequest.current) setGraphError(true);
    } finally {
      if (mounted.current && request === graphRequest.current) setGraphLoading(false);
    }
  }, [userId, courses]);

  const dropFromPicker = useCallback((sid: string) => {
    setOpenSessions((prev) => (prev ?? []).filter((s) => s.session_id !== sid));
  }, []);

  /** The session is closed (a 409 from any teaching route, or /status): show its
   *  stored close — POST /close is idempotent (A60) — and drop it from the picker. */
  const enterClosed = useCallback(async (sid: string) => {
    // A terminal close invalidates pre-close status/plan/hint requests too,
    // not only the active stream. Their snapshots must never reopen it.
    const g = ++gen.current;
    invalidateHint();
    streamAbort.current?.abort();
    setStarting(false);
    setScopeLoading(false);
    setProbeBusy(false);
    setPlanLoading(false);
    setPlanBusy(false);
    setGoalBusy(false);
    setCloseBusy(false);
    setFeedbackPending(false);
    setPendingGrade(null);
    setPrequestion(null);
    setSelfExplain(null);
    dispatch({ type: "check", item: null });
    dispatch({ type: "phase", phase: "close" });
    dropFromPicker(sid);
    try {
      const r = await closeLoopSession(sid, userId);
      if (g === gen.current) showClose(sid, r);
    } catch {
      if (g === gen.current) setCloseNote(CLOSED_ELSEWHERE_COPY);
    }
  }, [userId, dropFromPicker, invalidateHint, showClose]);

  // ── Error routing: a budget 429 is the banner, a closed session is the
  // close, anything else a toast ─────────────────────────────────────────
  const reportError = useCallback((err: unknown, fallback: string) => {
    const pause = budgetPauseOf(err);
    if (pause) {
      dispatch({ type: "budget", level: "hard", resetAt: pause.resetAt, sessionCapped: pause.sessionCapped });
      return;
    }
    const { status, detail } = extractErrorDetail(err);
    const sid = sessionRef.current;
    if (status === 409 && detail === SESSION_CLOSED_DETAIL && sid) {
      void enterClosed(sid);
      return;
    }
    toast.error(humanizeError(err, fallback));
  }, [toast, enterClosed]);

  /** Apply GET /status: the phase, and the open item's pose or none. */
  const applyStatus = useCallback((sid: string, st: LoopSessionStatus) => {
    invalidateHint();
    applyLearningScope(st);
    if (st.approved_plan) setApprovedPlan(st.approved_plan);
    setPendingGrade(st.pending_grade ?? null);
    if (st.loop_phase === "close") {
      void enterClosed(sid);
      return;
    }
    dispatch({ type: "check", item: st.check ?? null });
    dispatch({ type: "phase", phase: statusPhase(st) });
    setFeedbackPending(statusPhase(st) === "feedback");
    // spec §13 A138/A139: an open guess or "why" prompt is restored read-only
    // (its pose row is already in the transcript)
    setPrequestion(st.prequestion ?? null);
    setSelfExplain(st.self_explain ?? null);
  }, [enterClosed, applyLearningScope, invalidateHint]);

  /** After a submission that did not settle (a 409, a stream error, Stop): the
   *  server may already have graded it, so re-read where the session stands.
   *  Read-only. If even that fails, the item is cleared (fail closed): "Check
   *  me" re-poses it while it is still open (/check/next is idempotent then). */
  const reconcile = useCallback(async (sid: string, g: number, epoch = turnEpoch.current) => {
    const current = () => g === gen.current && epoch === turnEpoch.current && sid === sessionRef.current;
    try {
      const st = await getLoopSessionStatus(sid, userId);
      if (current()) applyStatus(sid, st);
    } catch {
      if (current()) dispatch({ type: "check", item: null });
    }
  }, [userId, applyStatus]);

  // ── Session lifecycle ──────────────────────────────────────────────────
  const clearSessionView = useCallback(() => {
    ++turnEpoch.current;
    invalidateHint();
    streamAbort.current?.abort();
    streamAbort.current = null;
    dispatch({ type: "reset" });
    setReadOnly(null);
    setGoal(null);
    setGoalProgress(null);
    setPracticeUnavailable([]);
    setDiagnosis(null);
    setScopeReady(false);
    setScopeLoading(false);
    setScopeError(false);
    setGoalEditor(false);
    setGoalBusy(false);
    setGoalError(null);
    setStarting(false);
    setLoadError(null);
    setStartCrisis(null);
    setProbeItem(null);
    setProbeDraft(EMPTY_DRAFT);
    setProbeReference(null);
    setProbeNote(null);
    setProbeCount(0);
    setProbeBusy(false);
    setProbeFinished(false);
    setNoCheckItems(null);
    setMaterialsNote(false);
    setPlan(null);
    setPlanJustApproved(false);
    setApprovedPlan(null);
    setPlanGoalVersion(undefined);
    setPlanBusy(false);
    setPlanLoading(false);
    setMessages([]);
    setStreamingText(null);
    setAttempt(EMPTY_DRAFT);
    setAttemptBusy(false);
    setHint(null);
    setHintBusy(false);
    setCheckNote(null);
    setCheckBusy(false);
    setFeedbackPending(false);
    setPendingGrade(null);
    setAskRating(null);
    setVerdict(null);
    setPrequestion(null);
    setPrequestionBusy(false);
    setSelfExplain(null);
    setSelfExplainBusy(false);
    setSelfExplainSaved(false);
    setClose(null);
    setCloseBusy(false);
    setCloseNote(null);
    countedAttempt.current = null;
  }, [invalidateHint]);

  const loadPlan = useCallback(async (sid: string, g: number) => {
    if (g !== gen.current) return;
    setPlanLoading(true);
    setLoadError(null);
    setPlan(null);
    setPlanGoalVersion(undefined);
    try {
      const r = await getLoopPlan(sid, userId);
      if (g !== gen.current) return;
      applyLearningScope(r);
      setScopeReady(true);
      setScopeError(false);
      setPlanGoalVersion(r.goal_version);
      setPlan(r.concepts ?? []);
      if (r.phase) dispatch({ type: "phase", phase: r.phase }); // an empty plan teaches at once
    } catch (err) {
      if (g !== gen.current) return;
      setLoadError("plan");
      reportError(err, "Couldn't load today's plan.");
    } finally {
      if (g === gen.current) setPlanLoading(false);
    }
  }, [userId, reportError, applyLearningScope]);

  const nextProbe = useCallback(async (sid: string, g: number) => {
    if (g !== gen.current) return;
    setProbeBusy(true);
    setLoadError(null);
    try {
      const r = await nextLoopProbe(sid, userId);
      if (g !== gen.current) return;
      applyLearningScope(r);
      setProbeReference(null);
      if (r.done) {
        setPendingGrade(null);
        setProbeItem(null);
        if (r.no_check_items) setNoCheckItems(r.preparing ? "preparing" : "none");
        dispatch({ type: "phase", phase: r.phase });
        if (r.phase === "plan") await loadPlan(sid, g);
      } else if ("pending_grade" in r) {
        setPendingGrade(r.pending_grade);
        setProbeItem(null);
      } else {
        setPendingGrade(null);
        setProbeItem(r);
        setProbeDraft(EMPTY_DRAFT);
      }
    } catch (err) {
      if (g !== gen.current) return;
      setLoadError("probe");
      reportError(err, "Couldn't load the next question.");
    } finally {
      if (g === gen.current) setProbeBusy(false);
    }
  }, [userId, loadPlan, reportError, applyLearningScope]);

  const loadLearningScope = useCallback(async (sid: string, g: number) => {
    if (g !== gen.current) return null;
    setScopeLoading(true);
    try {
      const response = await getLoopSessionStatus(sid, userId);
      if (g !== gen.current) return null;
      applyStatus(sid, response);
      setScopeReady(true);
      setScopeError(false);
      return response;
    } catch {
      if (g === gen.current) setScopeError(true);
      return null;
    } finally {
      if (g === gen.current) setScopeLoading(false);
    }
  }, [userId, applyStatus]);

  const resume = useCallback(async (s: LoopOpenSession) => {
    const g = ++gen.current;
    clearSessionView();
    setStarting(true);
    setSessionId(s.session_id);
    sessionRef.current = s.session_id;
    dispatch({ type: "phase", phase: s.phase });
    setFeedbackPending(s.phase === "feedback");
    try {
      try {
        const r = await resumeSession(s.session_id);
        if (g !== gen.current) return;
        setMessages(toChat(r.messages));
      } catch (err) {
        if (g === gen.current) toast.error(humanizeError(err, "Couldn't load this session's messages."));
      }
      if (g !== gen.current) return;
      const latest = await loadLearningScope(s.session_id, g);
      if (g !== gen.current) return;
      // Another tab may have edited the goal since /sessions was read. Continue
      // from authoritative status, never a stale list's phase or an extra pose write.
      const phase = latest ? statusPhase(latest) : s.phase;
      if (latest?.pending_grade) return; // Recover the saved result, not a new pose.
      if (phase === "probe") await nextProbe(s.session_id, g);
      else if (phase === "plan") await loadPlan(s.session_id, g);
    } finally {
      if (g === gen.current) setStarting(false);
    }
  }, [clearSessionView, nextProbe, loadPlan, loadLearningScope, toast]);

  const openReadOnly = useCallback(async (id: string) => {
    const g = ++gen.current;
    clearSessionView();
    setSessionId(null);
    sessionRef.current = null;
    try {
      const r = await resumeSession(id);
      if (g !== gen.current) return;
      setReadOnly({ id, topic: r.session?.topic ?? "", messages: toChat(r.messages) });
    } catch {
      // the same retry state as a failed /sessions — never a probe
      if (g === gen.current) setSessionsError(true);
    }
  }, [clearSessionView]);

  /** Wrap up the open session being left (A60's wrap-up), so sessions do not
   *  pile up open. True when a new session may start: closed now, or already
   *  closed elsewhere, and the screen is still on it. A close that cannot run
   *  now (409) shows why and starts nothing. */
  const wrapUpLeaving = useCallback(async (leaving: string): Promise<boolean> => {
    const g0 = gen.current;
    setStarting(true);
    try {
      await closeLoopSession(leaving, userId);
    } catch (err) {
      if (g0 !== gen.current) return false;
      setStarting(false);
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail === SESSION_CLOSED_DETAIL) {
        // already closed elsewhere: nothing to wrap up
      } else if (status === 409 && detail) {
        setCloseNote(CLOSE_RETRY_COPY[detail] ?? detail);
        return false;
      } else {
        reportError(err, "Couldn't wrap up the current session.");
        return false;
      }
    }
    dropFromPicker(leaving);
    return g0 === gen.current;
  }, [userId, reportError, dropFromPicker]);

  /** Adopt a started session: its id, scope, opener and budget. False when the
   *  crisis-support card answered instead (no session was opened). Send to
   *  tutor's note matched: the card beside the session, unless the notetaker
   *  just showed it (`cardShown`). */
  const adoptStarted = useCallback((r: Awaited<ReturnType<typeof startLoopSession>>, cardShown: boolean): boolean => {
    const crisisSupport = crisisSupportIn(r);
    if (crisisSupport && !r.crisis_support_alongside) { setStartCrisis(crisisSupport); return false; } // no session was opened
    if (crisisSupport && !cardShown) interceptCrisis(r);
    setSessionId(r.session_id);
    sessionRef.current = r.session_id;
    applyLearningScope(r);
    setScopeReady(true);
    if (r.initial_message) setMessages([asMsg("assistant", r.initial_message)]);
    if (r.materials_unavailable) setMaterialsNote(true); // A128: the opener's retrieval failed
    if (r.budget?.level === "hard") {
      // A27: a capped student still gets the template opener and the probe
      dispatch({ type: "budget", level: "hard", resetAt: r.budget.reset_at, sessionCapped: r.budget.session_capped });
    }
    return true;
  }, [applyLearningScope, interceptCrisis]);

  /** List a session the first /probe/next materialised, at the picker's front. */
  const listStarted = useCallback((sid: string, topic: string) => {
    setOpenSessions((prev) => {
      const list = prev ?? [];
      if (list.some((x) => x.session_id === sid)) return list;
      const row: LoopOpenSession = { session_id: sid, topic, started_at: new Date().toISOString(), phase: "probe" };
      return [row, ...list];
    });
  }, []);

  /** Start a session and its probe. `closeCurrent` (the "New session" button):
   *  the open session being left is closed first (A60's wrap-up), so sessions
   *  do not pile up open; a close that cannot run now (409) starts nothing.
   *  With none on screen (a read-only transcript), the course's listed open
   *  session is the one left (Z64: one open session per course). */
  const newSession = useCallback(async (
    { closeCurrent = false, topic, mode }: { closeCurrent?: boolean; topic?: string; mode?: string } = {},
  ) => {
    if (!courseId || !userId || sessionTransitionBusy) return;
    lastStart.current = { topic, mode };
    // An explicit start wins over a boot that has not listed the sessions yet.
    bootKey.current = `${userId}:${courseId}`;
    const leaving = closeCurrent ? sessionToLeave(sessionRef.current, isOpenPhase(state.phase), openSessions) : null;
    if (leaving && !(await wrapUpLeaving(leaving))) return;
    const g = ++gen.current;
    clearSessionView();
    setSessionId(null);
    sessionRef.current = null;
    setStarting(true);
    const title = topic || course?.course_name || "";
    // G1: a start on Send to tutor's note title, unchanged, names the note
    const fromNoteId = deepLink.note && topic === deepLink.topic ? deepLink.note : null;
    const cardShown = !!fromNoteId && takeNoteCardShown(fromNoteId);
    try {
      const r = await startLoopSession(userId, courseId, title, mode, undefined, fromNoteId);
      if (g !== gen.current || !adoptStarted(r, cardShown)) return;
      await nextProbe(r.session_id, g);
      if (g !== gen.current) return;
      // the first /probe/next materialised the session row: list it
      listStarted(r.session_id, title);
    } catch (err) {
      if (g !== gen.current) return;
      // docs/safety/crisis-support.md: a refused start (a 429, a 500) can carry
      // the card (b2-data's note-matched screen, via ErrorCardMiddleware) —
      // the student never gets a refusal without it, unless Send to tutor
      // just showed it for this note.
      if (!cardShown) interceptCrisis({ crisis_support: crisisSupportInError(err) });
      setLoadError("start"); // never an empty probe: the start card offers a retry
      reportError(err, "Couldn't start a session.");
    } finally {
      if (g === gen.current) setStarting(false);
    }
  }, [courseId, userId, course, deepLink, state.phase, openSessions, sessionTransitionBusy, clearSessionView, nextProbe, reportError, wrapUpLeaving, adoptStarted, listStarted, interceptCrisis]);

  const loadSessions = useCallback(async () => {
    if (!courseId || !userId) return;
    const g = ++gen.current;
    const wanted = resumePending.current ? (pendingResume.current ?? deepLink.resume) : null;
    pendingResume.current = null;
    let listed: Awaited<ReturnType<typeof listLoopSessionsFor>>;
    try {
      listed = await listLoopSessionsFor(userId, courseId, wanted);
    } catch {
      // never falls through to a new session or a probe (spec §11.3)
      if (g === gen.current) setSessionsError(true);
      return;
    }
    if (g !== gen.current) return;
    resumePending.current = false;
    const list = listed.sessions;
    setSessionsError(false);
    setOpenSessions(list);
    const found = wanted ? listed.resume : null;
    if (found) {
      if (found.course_id !== courseId && courses?.some((c) => c.course_id === found.course_id)) {
        // an open loop session in another of the student's courses: switch to it
        bootKey.current = `${userId}:${found.course_id}`;
        setCourseId(found.course_id);
        let others: LoopOpenSession[] = [];
        try {
          others = (await listLoopSessionsFor(userId, found.course_id, null)).sessions;
        } catch {
          // the picker is a convenience; the named session still resumes
        }
        if (g !== gen.current) return;
        setOpenSessions(others.some((s) => s.session_id === found.session_id) ? others : [found, ...others]);
      } else if (!list.some((s) => s.session_id === found.session_id)) {
        setOpenSessions([...list, found]); // past the picker's limit: list it too
      }
      await resume(found);
    } else if (wanted) {
      await openReadOnly(wanted); // a legacy (or closed) session: read-only
    } else if (list.length > 0) {
      await resume(list[0]);
    } else if (deepLink.topic && !topicStarted.current) {
      // a "learn this" link from the map starts on its concept, once
      topicStarted.current = true;
      await newSession({ topic: deepLink.topic, mode: deepLink.mode });
    } else {
      // wireframe T1: nothing open in this course — the Tutor home, never a
      // probe the student did not ask for
      setView((v) => (v === "session" ? "home" : v));
    }
  }, [courseId, userId, courses, deepLink, openReadOnly, resume, newSession]);

  const loadCourses = useCallback(async () => {
    if (!userId) return;
    try {
      const r = await getCourses(userId);
      if (!mounted.current) return;
      const list = r.courses ?? [];
      setCourses(list);
      // ?course= picks the course when the student is enrolled in it
      const linked = list.find((c) => c.course_id === deepLink.course)?.course_id;
      setCourseId((prev) => prev ?? linked ?? list[0]?.course_id ?? null);
    } catch {
      if (mounted.current) setSessionsError(true);
    }
  }, [userId, deepLink]);

  // ── Boot: courses → sessions (once per user + course) ───────────────────
  useEffect(() => {
    void loadCourses();
  }, [loadCourses]);

  useEffect(() => {
    if (!userId || !courseId || !courses) return;
    const key = `${userId}:${courseId}`;
    if (bootKey.current === key) return; // StrictMode re-runs must not start twice
    bootKey.current = key;
    void loadSessions();
  }, [userId, courseId, courses, loadSessions]);

  useEffect(() => {
    if (courses) void refreshGraph();
  }, [courses, refreshGraph]);

  const retryLearningScope = async () => {
    if (!sessionId) return;
    const g = gen.current;
    const latest = await loadLearningScope(sessionId, g);
    if (!latest || g !== gen.current) return;
    const phase = statusPhase(latest);
    if (phase === "probe") await nextProbe(sessionId, g);
    else if (phase === "plan") await loadPlan(sessionId, g);
  };

  const retrySessions = () => {
    setSessionsError(false);
    setOpenSessions(null);
    if (!courses) void loadCourses();
    else void loadSessions();
  };

  // ── Tutor shell: sidebar, home, course page, all sessions ────────────────
  // Every session the student has, across courses (the sidebar's recents, T2,
  // T3), a course page's material (read once, when one first opens) and the
  // reviews due — each read failure shown as one, with a retry (F11).
  const lists = useTutorLists({
    userId, sessionId, sessionClosed: state.phase === "close", wantMaterials: view === "course", studyVisible,
  });
  const sessionRows = useMemo(() => mergeSessions(lists.recent, openSessions, courseId), [lists.recent, openSessions, courseId]);

  /** Show another course: its sessions load (and an open one resumes) behind the page. */
  const switchCourse = (v: string) => {
    if (v === courseId) return;
    ++gen.current;
    clearSessionView();
    setSessionId(null);
    sessionRef.current = null;
    setOpenSessions(null);
    setCourseId(v);
  };
  const { closeDrawer } = layout;
  const showHome = () => { setView("home"); closeDrawer(); };
  const showCourse = (id: string) => {
    switchCourse(id);
    setCourseView(id);
    setView("course");
    closeDrawer();
  };
  const showAll = () => { setView("all"); closeDrawer(); };
  /** A listed session: an open one resumes; a wrapped-up one opens read-only (T14). */
  const openRow = (row: TutorSessionRow) => {
    setView("session");
    closeDrawer();
    if (row.id === sessionId && !readOnly) return;
    if (row.courseId && row.courseId !== courseId && courses?.some((c) => c.course_id === row.courseId)) {
      pendingResume.current = row.id;
      resumePending.current = true;
      switchCourse(row.courseId);
      return;
    }
    const listed = openSessions?.find((s) => s.session_id === row.id);
    if (listed) void resume(listed);
    else void openReadOnly(row.id);
  };
  /** T1's start: a new session (the open one on screen is wrapped up first). */
  const startGuided = async (opts: { topic?: string; goal?: boolean } = {}) => {
    setView("session");
    await newSession({ closeCurrent: true, topic: opts.topic, mode: deepLink.mode });
    lastStart.current.goal = opts.goal;
    if (opts.goal && mounted.current && sessionRef.current) { setGoalEditor(true); setGoalError(null); }
  };
  const retryStart = () => (lastStart.current.goal ? startGuided(lastStart.current) : newSession(lastStart.current));

  // ── Probe ──────────────────────────────────────────────────────────────
  /** After a graded answer: the probe's last answer already moved the session
   *  to `plan` (a /probe/next now would 409), otherwise the next item. */
  const advanceProbe = async (done: boolean, g: number) => {
    if (!sessionId) return;
    setProbeReference(null);
    if (done) {
      setProbeItem(null);
      dispatch({ type: "phase", phase: "plan" });
      await loadPlan(sessionId, g);
    } else {
      await nextProbe(sessionId, g);
    }
  };

  const applyProbeAnswer = async (r: LoopProbeAnswerResult, g: number) => {
    applyLearningScope(r);
    if (r.graded) {
      setPendingGrade(null);
      void refreshGraph();
      setProbeCount((n) => n + 1);
      if (r.probe_done) setProbeFinished(true);
      if (r.reference_answer) {
        setProbeReference(r.reference_answer);
        return;
      }
      await advanceProbe(r.probe_done, g);
      return;
    }
    if (r.refused) {
      setProbeNote(PROBE_REFUSED_COPY);
      return;
    }
    setProbeNote(PROBE_UNAVAILABLE_COPY);
    if (sessionId) await nextProbe(sessionId, g);
  };

  const submitProbe = async (idk: boolean) => {
    if (!sessionId || !probeItem || probeBusy || pendingGrade) return;
    focusAfter.current = "probe-answer"; // a new item, the answer or the plan takes focus first
    ++turnEpoch.current;
    const g = gen.current;
    // an idk states no confidence (spec §13 A127)
    const a: LoopCheckAnswer = idk ? { idk: true } : draftAnswer(probeDraft, probeItem.format);
    setProbeBusy(true);
    setProbeNote(null);
    try {
      const r = await answerLoopProbe(sessionId, userId, probeItem.question_hash, a);
      if (g !== gen.current) return;
      if (interceptCrisis(r)) { setProbeDraft(EMPTY_DRAFT); return; } // still posed, ungraded
      await applyProbeAnswer(r, g);
    } catch (err) {
      if (g === gen.current) {
        reportError(err, "Couldn't send that answer.");
        void reconcile(sessionId, g);
      }
    } finally {
      if (g === gen.current) setProbeBusy(false);
    }
  };

  const saveGoal = async (requested: LoopGoal | null) => {
    if (!sessionId || !courseId || goalBusy || !scopeReady || pendingGrade) return;
    if (state.phase !== "probe" && state.phase !== "plan") return;
    const ownIds = new Set(graph.nodes.filter((n) => n.course_id === courseId && !n.is_subject_root).map((n) => n.id));
    if (requested && (requested.text.length > 500 || requested.target_node_ids.length < 1 || requested.target_node_ids.length > 12 ||
      requested.target_node_ids.some((id) => !ownIds.has(id)))) {
      setGoalError("Confirm 1–12 concepts from this course.");
      return;
    }
    const sid = sessionId;
    const g = ++gen.current;
    setGoalBusy(true);
    setGoalError(null);
    try {
      const response = await setLoopGoal(sid, userId, requested);
      if (g !== gen.current) return;
      if (interceptCrisis(response)) return; // the goal was not stored
      applyLearningScope(response);
      setGoalProgress(response.goal_progress ?? null);
      setScopeReady(true);
      setGoalEditor(false);
      setProbeItem(null);
      setProbeDraft(EMPTY_DRAFT);
      setProbeReference(null);
      setProbeCount(0);
      setProbeFinished(false);
      setNoCheckItems(null);
      setPlan(null);
      setPlanGoalVersion(undefined);
      setLoadError(null);
      dispatch({ type: "phase", phase: response.phase });
      if (response.phase === "probe") await nextProbe(sid, g);
      else if (response.phase === "plan") await loadPlan(sid, g);
      requestAnimationFrame(() => { if (g === gen.current) goalButton.current?.focus(); });
    } catch (error) {
      if (g !== gen.current) return;
      setGoalError(humanizeError(error, "Couldn't update your learning scope. Try again."));
      if (extractErrorDetail(error).status === 409) {
        try {
          const latest = await getLoopSessionStatus(sid, userId);
          if (g !== gen.current) return;
          applyStatus(sid, latest);
          if (!["probe", "plan"].includes(statusPhase(latest))) {
            setGoalEditor(false);
            toast.info(humanizeError(error, "The session has started teaching. Start a new session to change its goal."));
          }
        } catch { /* keep the draft and error available for retry */ }
      }
    } finally {
      if (g === gen.current) setGoalBusy(false);
    }
  };

  /** Spec §13 A138: a guess the server just posed (plan approval, a turn that
   *  opened the next segment, a closed "why" prompt that held it back). The
   *  server saved its pose as an assistant row; the log mirrors it and hides
   *  it while the card shows it. */
  const showPrequestion = useCallback((pq: LoopPrequestion | null | undefined) => {
    if (!pq?.question_hash) return;
    setPrequestion(pq);
    if (pq.text) setMessages((prev) => [...prev, asMsg("assistant", pq.text)]);
  }, []);

  // ── Plan ───────────────────────────────────────────────────────────────
  const approvePlan = async () => {
    if (!sessionId || !plan || plan.length === 0 || planBusy) return;
    focusAfter.current = "teaching";
    const g = gen.current;
    setPlanBusy(true);
    try {
      const ids = plan.map((concept) => concept.node_id);
      const r = planGoalVersion === undefined
        ? await approveLoopPlan(sessionId, userId, ids)
        : await approveLoopPlan(sessionId, userId, ids, planGoalVersion);
      if (g === gen.current) {
        dispatch({ type: "phase", phase: r.phase });
        setPlanJustApproved(true);
        // the panel and the phase line follow the approved order from its first concept
        setApprovedPlan({ concepts: plan, cursor: 0 });
        setGoalProgress((current) => current?.status === "continue_available" ? null : current);
        // spec §13 A138: the first segment opens on its ungraded guess
        showPrequestion(r.prequestion);
      }
    } catch (err) {
      if (g !== gen.current) return;
      reportError(err, "Couldn't save the plan.");
      if (g !== gen.current) return;
      if (extractErrorDetail(err).status === 409) {
        setPlan(null);
        setLoadError("plan");
        await retryLearningScope();
      }
    } finally {
      if (g === gen.current) setPlanBusy(false);
    }
  };

  // ── Streamed turns (chat + explicit submissions) ─────────────────────────
  /** A check the server activated (a teach turn's done.check, or "Check me"):
   *  the pose, which the server also saved as an assistant row. The document
   *  is now in `check` (PKG-07 `_phase_for`), whatever the turn's own phase. */
  const applyActivated = useCallback((check: LoopCheckItem | null | undefined) => {
    if (!check?.prompt) return;
    invalidateHint();
    dispatch({ type: "check", item: check });
    dispatch({ type: "phase", phase: "check" });
    const pose = check.prompt;
    setMessages((prev) => [...prev, asMsg("assistant", pose)]);
    setAttempt(EMPTY_DRAFT);
    setHint(null);
    setCheckNote(null);
  }, [invalidateHint]);

  /** A served turn's `done` (the crisis card aside): the final reply, the
   *  grade, the phase, learner state, the next check, the teach prompts and
   *  the budget. */
  const applyServedTurn = useCallback((
    res: LoopTurnResult,
    { submission, sid, streamed, hardSeen }: { submission: boolean; sid: string | null; streamed: string; hardSeen: boolean },
  ) => {
    // done.reply is always the final, leak-stripped text (A46) — never the tokens
    const text = res.reply ?? streamed;
    if (text) setMessages((prev) => [...prev, asMsg("assistant", text)]);
    // #761 (B4): a replay re-sends a reply the server already persisted —
    // {reply, graph_update, mastery_changes: [], replayed: true}, no phase,
    // check or learner state. Its turn's state changes already happened, so
    // an absent field here is not a "clear": nothing else is applied.
    if (res.replayed) return;
    if (submission && res.graded) {
      setVerdict(res.verdict ? { verdict: res.verdict, nodeId: res.learner_state?.[0]?.node_id ?? state.focusNodeId } : null);
      setPendingGrade(null);
      // graded — correct, not yet, idk, or a refusal the server graded as idk:
      // the item takes no more answers
      dispatch({ type: "check", item: null });
      setAttempt(EMPTY_DRAFT);
      setHint(null);
    }
    if (submission && res.ask_rating && sid) setAskRating(sid);
    if (res.materials_unavailable) setMaterialsNote(true); // A128: the server sends it once per session
    if (res.phase) dispatch({ type: "phase", phase: res.phase });
    setFeedbackPending(false); // only a successful done means feedback was served
    setCheckNote(null);
    for (const learnerState of res.learner_state ?? []) {
      dispatch({ type: "learner_state", state: learnerState });
    }
    applyActivated(res.check);
    // spec §13 A138/A139: a served turn closes any open guess or "why" prompt
    // (the server superseded it) and may open new ones
    setSelfExplain(res.self_explain ?? null);
    setPrequestion(null);
    showPrequestion(res.prequestion);
    if (res.budget?.level === "hard") {
      dispatch({ type: "budget", level: "hard", resetAt: res.budget.reset_at, sessionCapped: res.budget.session_capped });
    } else if (!hardSeen) {
      dispatch({ type: "budget_clear" }); // a tutor turn got through
    }
  }, [applyActivated, showPrequestion, state.focusNodeId]);

  /** The check an answer was for is gone server-side (current is null): free
   *  the box, say why, and let the caller select another check. */
  const dropClosedCheck = useCallback((copy: string, then?: () => void) => {
    setPendingGrade(null);
    dispatch({ type: "check", item: null });
    setAttempt(EMPTY_DRAFT);
    setHint(null);
    toast.info(copy);
    then?.();
  }, [toast]);

  /** A turn that threw while this screen still owns it: what streamed stays,
   *  marked interrupted; a submission that may have been graded is re-read;
   *  then the error is routed (a pause, an already-graded resend, or a toast). */
  const failedTurn = useCallback((err: unknown, t: {
    submission: boolean; recover: boolean; sid: string | null; g: number; epoch: number;
    streamed: string; hardSeen: boolean; aborted: boolean; onPaused?: () => void; retryText?: string;
    onCheckClosed?: () => void;
  }) => {
    const { status, detail } = extractErrorDetail(err);
    const closed = status === 409 && detail === SESSION_CLOSED_DETAIL; // reportError shows the close
    const checkClosed = checkClosedCopy(t.submission, status, detail);
    // ADR 0020: what streamed stays, marked interrupted; a chat message the tutor
    // never answered offers Retry (a pause gives it back through onPaused, a
    // close has nothing to retry), and after an error it is back in the composer.
    const retryText = t.hardSeen || budgetPauseOf(err) || closed ? undefined : t.retryText;
    if (t.streamed || retryText) setMessages((prev) => [...prev, { ...asMsg("assistant", t.streamed), interrupted: true, retryText }]);
    if (retryText && !t.aborted) setChatDraft((d) => ({ text: retryText, key: d.key + 1 }));
    // The grade lands BEFORE the feedback stream starts: a submission that did
    // not settle (409 already graded, a mid-stream error, Stop) re-reads the
    // session so the answer box never sticks on a graded item.
    if (t.recover && t.sid && !closed && !checkClosed) void reconcile(t.sid, t.g, t.epoch);
    if (t.aborted) return;
    if (checkClosed) {
      dropClosedCheck(checkClosed, t.onCheckClosed);
      return;
    }
    // At the hard level the stream ends with no `done`: that is the pause, not an error.
    if (t.hardSeen) {
      t.onPaused?.();
      return;
    }
    if (t.submission && status === 409 && detail === ALREADY_GRADED_DETAIL) return;
    if (budgetPauseOf(err)) t.onPaused?.(); // a 429: reportError shows the pause banner
    reportError(err, "The tutor couldn't answer. Try again.");
  }, [reconcile, reportError, dropClosedCheck]);

  const runTurn = useCallback(async (
    run: (h: StreamChatHandlers) => Promise<LoopTurnResult>,
    { submission = false, onPaused, retryText, onCheckClosed }: {
      submission?: boolean; onPaused?: () => void; retryText?: string; onCheckClosed?: () => void;
    } = {},
  ): Promise<LoopTurnResult | null> => {
    // A hint may still be in flight when the learner submits: its previous
    // phase/question must never overwrite the newer turn. A chat turn waits for
    // a hint instead (F7: the composer is held) and keeps an earned hint's grant
    // — the server raised the rung and charged it; the item is still posed.
    if (submission) invalidateHint();
    streamAbort.current?.abort();
    const controller = new AbortController();
    streamAbort.current = controller;
    const g = gen.current;
    const sid = sessionRef.current;
    const epoch = ++turnEpoch.current;
    const recoveringFeedback = feedbackPending;
    let feedbackStarted = false;
    let streamed = "";
    let hardSeen = false;
    setSelfExplainSaved(false);
    // Abort is cooperative: a queued event may arrive after Stop or a session
    // switch. Only the currently owned, live stream may change the learner UI.
    const ownsTurn = () => mounted.current && g === gen.current && streamAbort.current === controller;
    const acceptsEvents = () => ownsTurn() && !controller.signal.aborted;
    setStreamingText("");
    const handlers: StreamChatHandlers = {
      signal: controller.signal,
      onToken: (d) => {
        if (!acceptsEvents()) return;
        streamed += d;
        setStreamingText(streamed);
      },
      // A46: discard every token streamed so far; the current text follows
      onRetract: () => {
        if (!acceptsEvents()) return;
        streamed = "";
        setStreamingText("");
      },
      onPhase: (p) => {
        if (!acceptsEvents()) return;
        dispatch({ type: "phase", phase: p });
        setFeedbackPending(p === "feedback");
        if (p === "feedback") {
          setPendingGrade(null);
          feedbackStarted = true; // the server committed the grade before this stream
          dispatch({ type: "check", item: null });
          setAttempt(EMPTY_DRAFT);
          setHint(null);
        }
      },
      onCheck: (c) => { if (acceptsEvents()) dispatch({ type: "check", item: c }); },
      onLearnerState: (s) => { if (acceptsEvents()) dispatch({ type: "learner_state", state: s }); },
      onBudget: (b) => {
        if (!acceptsEvents()) return;
        if (b.level === "hard") hardSeen = true;
        dispatch({ type: "budget", level: b.level, resetAt: b.reset_at, sessionCapped: b.session_capped });
      },
    };
    try {
      const res = await run(handlers);
      if (!ownsTurn()) return null;
      if (controller.signal.aborted) {
        if ((submission || feedbackStarted || recoveringFeedback) && sid) void reconcile(sid, g, epoch);
        return null;
      }
      // docs/safety/crisis-support.md: the card instead of a tutor turn — nothing
      // was graded or recorded, so phase, check item and learner state stay as
      // they were (an answered item stays posed)
      const crisisSupport = crisisSupportIn(res);
      if (crisisSupport) {
        setMessages((prev) => [...prev, { ...asMsg("assistant", res.reply ?? ""), crisisSupport }]);
        if (submission) setAttempt(EMPTY_DRAFT);
        setCheckNote(null);
        return res;
      }
      applyServedTurn(res, { submission, sid, streamed, hardSeen });
      return res;
    } catch (err) {
      if (!ownsTurn()) return null;
      failedTurn(err, {
        submission, recover: submission || feedbackStarted || recoveringFeedback, sid, g, epoch,
        streamed, hardSeen, aborted: controller.signal.aborted, onPaused, retryText, onCheckClosed,
      });
      return null;
    } finally {
      if (streamAbort.current === controller) {
        streamAbort.current = null;
        setStreamingText(null);
      }
    }
  }, [reconcile, invalidateHint, feedbackPending, applyServedTurn, failedTurn]);

  const send = (text: string) => {
    // A budget pause does not stop a message: the server screens it for a crisis
    // before any budget or rate limit, so a paused student in crisis still gets
    // the support card (docs/safety/crisis-support.md). Anything else the pause
    // answers with no reply, and the message goes back into the composer. While
    // a hint loads, nothing is sent: the hint the server already charged for
    // would be lost (F7).
    if (!sessionId || starting || scopeLoading || pendingGrade || hintBusy) return;
    focusAfter.current = "turn"; // a check the turn poses takes focus first
    setPlanJustApproved(false);
    const userMsg = asMsg("user", text);
    setMessages((prev) => [...prev, userMsg]);
    void runTurn((h) => streamLoopChat(sessionId, userId, text, h), {
      retryText: text,
      onPaused: () => {
        setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
        setChatDraft((d) => ({ text, key: d.key + 1 }));
      },
    });
  };

  const stop = () => streamAbort.current?.abort();
  /** ADR 0020 Retry: the failed pair leaves the log and the message is sent again
   *  (and leaves the composer, if it is still there unchanged, so it is not sent twice). */
  const retryTurn = (m: ChatMsg) => {
    const text = m.retryText;
    if (!text || streamingText !== null || !sessionId || starting || scopeLoading || pendingGrade || hintBusy) return;
    setMessages((prev) => dropInterruptedTurn(prev, m.id, text));
    if (composerRef.current?.value === text) setChatDraft((d) => ({ text: "", key: d.key + 1 }));
    send(text);
  };

  const rate = (rating: LoopRating) => {
    const sid = askRating;
    setAskRating(null); // one click answers it
    if (sid) {
      submitLoopRating(sid, rating).catch((err) => reportError(err, "Couldn't save your rating."));
    }
  };

  const submitAttempt = async (idk: boolean) => {
    if (!sessionId || !item || attemptBusy || pendingGrade || hintBusy) return;
    focusAfter.current = "answered";
    const g = gen.current;
    // an idk states no confidence (spec §13 A127)
    const a: LoopCheckAnswer = idk ? { idk: true } : draftAnswer(attempt, item.format);
    const shown = idk
      ? "I don't know."
      : item.format === "mc_reason"
        ? `${attempt.option}${attempt.reason.trim() ? ` — ${attempt.reason.trim()}` : ""}`
        : attempt.answer;
    setMessages((prev) => [...prev, asMsg("user", shown)]);
    setAttemptBusy(true);
    let checkClosed = false;
    const res = await runTurn(
      (h) => streamLoopCheckAnswer(sessionId, userId, item.question_hash, a, h),
      { submission: true, onCheckClosed: () => { checkClosed = true; } },
    );
    if (g === gen.current) setAttemptBusy(false);
    if (res?.graded) void refreshGraph();
    if (checkClosed && g === gen.current) void checkMe({ afterClosedCheck: true });
  };

  /** Spec §13 A138: the guess at the segment's ungraded prequestion — or, once a
   *  guess is saved (`explain`), the owed explanation — then, in the same
   *  stream, the explanation turn: the answer first (from code), then why.
   *  Nothing is graded. A stream that does not settle re-reads the session
   *  (the guess may be saved: the card then offers the explanation). */
  const submitPrequestion = async (guess: LoopPrequestionGuess | "explain") => {
    if (!sessionId || !prequestion || prequestionBusy || streamingText !== null || starting || scopeLoading) return;
    focusAfter.current = "turn"; // the explanation is a tutor turn: then the composer
    const g = gen.current;
    const pq = prequestion;
    const body: LoopPrequestionGuess = guess === "explain" ? { no_idea: false } : guess;
    if (guess !== "explain") setMessages((prev) => [...prev, asMsg("user", renderGuess(guess))]);
    setPlanJustApproved(false); // the explanation is the segment's first teaching turn
    setPrequestionBusy(true);
    await runTurn(
      (h) => streamLoopPrequestionAnswer(sessionId, userId, pq.question_hash, body, h),
      { submission: true },
    );
    if (g === gen.current) setPrequestionBusy(false);
  };

  /** Spec §13 A139: the reply to a "why" prompt (or Skip). Stored for diagnosis
   *  only — never graded. A prequestion the prompt was holding back (the next
   *  segment's, A138: one open prompt at a time) comes back with it. */
  const sendSelfExplain = async (reply: string | null) => {
    if (!sessionId || !selfExplain || selfExplainBusy) return;
    const g = gen.current;
    const prompt = selfExplain;
    // the card goes: lost focus returns to the card's answer, or Continue
    focusAfter.current = "answered";
    setSelfExplainBusy(true);
    try {
      const r = await postLoopSelfExplain(
        sessionId, userId, prompt.prompt_id, reply === null ? { skip: true } : { reply, skip: false },
      );
      if (g !== gen.current) return;
      if (interceptCrisis(r)) return; // the card instead: nothing was recorded, the prompt stays
      setSelfExplain(null);
      if (reply !== null) {
        setMessages((prev) => [...prev, asMsg("user", reply)]);
        setSelfExplainSaved(true);
      }
      if (r.recorded) showPrequestion(r.prequestion);
    } catch (err) {
      if (g !== gen.current) return;
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail === SELF_EXPLAIN_GONE_DETAIL) {
        setSelfExplain(null); // a later turn already closed it
        return;
      }
      reportError(err, "Couldn't save your explanation.");
    } finally {
      if (g === gen.current) setSelfExplainBusy(false);
    }
  };

  const recoverGrade = async () => {
    if (!sessionId || !pendingGrade || starting || scopeLoading || probeBusy || attemptBusy || streamingText !== null) return;
    const sid = sessionId;
    const saved = pendingGrade;
    const g = gen.current;
    focusAfter.current = saved.kind === "check" ? "answered" : "probe-answer";
    if (saved.kind === "check") {
      setAttemptBusy(true);
      let checkClosed = false;
      const result = await runTurn(
        (handlers) => streamLoopCheckAnswer(sid, userId, saved.question_hash, { idk: false }, handlers),
        { submission: true, onCheckClosed: () => { checkClosed = true; } },
      );
      if (g !== gen.current) return;
      setAttemptBusy(false);
      if (result?.graded) void refreshGraph();
      if (checkClosed) void checkMe({ afterClosedCheck: true });
      return;
    }
    ++turnEpoch.current;
    setProbeBusy(true);
    setProbeNote(null);
    try {
      const result = await answerLoopProbe(sid, userId, saved.question_hash, { idk: false });
      if (g !== gen.current) return;
      await applyProbeAnswer(result, g);
    } catch (error) {
      if (g !== gen.current) return;
      reportError(error, "Couldn't finish checking the saved answer. Try again.");
      void reconcile(sid, g);
    } finally {
      if (g === gen.current) setProbeBusy(false);
    }
  };

  const askHint = async () => {
    if (!sessionId || !item || hintBusy) return;
    const g = gen.current;
    const request = ++hintEpoch.current;
    const ownsHint = () => mounted.current && g === gen.current && request === hintEpoch.current;
    const qh = item.question_hash;
    setHintBusy(true);
    setHint(null);
    try {
      // The draft is the student's work: record it as an attempt first so the
      // hint gate can see it (judged for the gate only; never stored or graded).
      const draft = (item.format === "mc_reason"
        ? [attempt.option, attempt.reason].filter(Boolean).join(" — ")
        : attempt.answer).trim();
      const grant = earnedHint.current;
      if (!grant || grant.sessionId !== sessionId || grant.questionHash !== qh) {
        if (draft && countedAttempt.current !== `${qh}:${draft}`) {
          const recorded = await postLoopAttempt(sessionId, userId, qh, draft);
          if (!ownsHint()) return;
          if (interceptCrisis(recorded)) { setAttempt(EMPTY_DRAFT); return; } // no hint, nothing counted
          if (recorded.counted) countedAttempt.current = `${qh}:${draft}`;
        }
        const r = await requestLoopHint(sessionId, userId, qh);
        if (!ownsHint()) return;
        if (r.denied) {
          setHint({ denied: r.denied });
          return;
        }
        if (typeof r.rung === "number") {
          // The gate already granted/recorded this rung. A failed text request
          // retries only /action, never grants another rung or repeats effort.
          earnedHint.current = { sessionId, questionHash: qh, rung: r.rung };
          setHintRetry(true);
        }
      }
      const t = await requestLoopHintTurn(sessionId, userId);
      if (!ownsHint()) return;
      earnedHint.current = null;
      setHintRetry(false);
      // In the card while the item is current; the log hides this row until then
      // (the server saved it as an assistant row, so a reload shows it there).
      setHint({ reply: t.reply });
      setMessages((prev) => [...prev, asMsg("assistant", t.reply)]);
      // spec §13 A139: a worked example or a shown solution asks "why" — a
      // served hint turn closes an older prompt and may open a new one
      setSelfExplainSaved(false);
      setSelfExplain(t.self_explain ?? null);
      if (t.phase) dispatch({ type: "phase", phase: t.phase });
      if (t.budget?.level === "hard") {
        dispatch({ type: "budget", level: "hard", resetAt: t.budget.reset_at, sessionCapped: t.budget.session_capped });
      }
    } catch (err) {
      if (ownsHint()) reportError(err, "Couldn't get a hint.");
    } finally {
      if (ownsHint()) setHintBusy(false);
    }
  };

  // Spec §13 A122: an item that opens on its worked example (a novice without
  // the prerequisite — the server's `worked_first`) asks for it at once, before
  // any attempt: the same /hint + hint turn as the button, once per posed item.
  // The server still decides — /hint grants H4 with no attempt only while the
  // example is owed — and the example is a leak-checked turn like any hint.
  const workedAsked = useRef<string | null>(null);
  useEffect(() => {
    if (!sessionId || !item?.worked_first || hintBusy || attemptBusy || feedbackPending || pendingGrade) return;
    const key = `${sessionId}:${item.question_hash}`;
    if (workedAsked.current === key) return;
    workedAsked.current = key;
    void askHint();
  });

  /** "Report this question" (spec §13 A113): the server records the reason and
   *  takes the check off this session — it is never served to this student
   *  again — so the card goes and "Check me" brings another. */
  const reportItem = async (reason: LoopReportReason): Promise<boolean> => {
    if (!sessionId || !item || attemptBusy || pendingGrade) return false;
    const g = gen.current;
    try {
      await reportCheckItem({
        surface: "loop", user_id: userId, session_id: sessionId, question_hash: item.question_hash, reason,
      });
    } catch (err) {
      if (g !== gen.current) return false;
      const { status, detail } = extractErrorDetail(err);
      // already withdrawn for the whole course (other students reported it): gone either way
      if (!(status === 409 && detail === WITHDRAWN_DETAIL)) {
        reportError(err, "Couldn't report that question. Try again.");
        return false;
      }
    }
    if (g !== gen.current) return true;
    focusAfter.current = "check-me"; // the card goes; "Check me" brings another
    invalidateHint();
    setSelfExplain(null);
    dispatch({ type: "check", item: null });
    dispatch({ type: "phase", phase: "teach" });
    setAttempt(EMPTY_DRAFT);
    setHint(null);
    setCheckNote(REPORTED_COPY);
    return true;
  };

  /** "Check me" (/check/next). `afterClosedCheck`: the server just closed the
   *  check an answer was for (CHECK_CLOSED_COPY), so a saved grade this render
   *  still shows is already gone and does not hold the next check back. */
  const checkMe = async ({ afterClosedCheck = false }: { afterClosedCheck?: boolean } = {}) => {
    if (!sessionId || checkBusy || feedbackPending || starting || scopeLoading || (pendingGrade && !afterClosedCheck)) return;
    focusAfter.current = "check-me"; // a posed check, or a new plan, takes focus first
    const g = gen.current;
    const epoch = ++turnEpoch.current;
    setCheckBusy(true);
    setCheckNote(null);
    try {
      const r = await nextLoopCheck(sessionId, userId);
      if (g !== gen.current || epoch !== turnEpoch.current) return;
      applyLearningScope(r);
      if (r.pending_grade) {
        setPendingGrade(r.pending_grade);
        dispatch({ type: "check", item: null });
        dispatch({ type: "phase", phase: r.phase });
        return;
      }
      if (r.check && r.goal_progress === undefined) setGoalProgress(null);
      setPlanJustApproved(false);
      if (r.phase === "plan") {
        // A completed goal frontier may unlock a fresh prerequisite/target.
        // Drop the old plan before reading the new one; approval stays explicit.
        invalidateHint();
        dispatch({ type: "check", item: null });
        setPlan(null);
        setPlanGoalVersion(undefined);
        dispatch({ type: "phase", phase: "plan" });
        await loadPlan(sessionId, g);
        return;
      }
      dispatch({ type: "phase", phase: r.phase });
      if (r.check) {
        setSelfExplain(null); // spec §13 A139: the new check supersedes an open "why" prompt
        applyActivated(r.check);
      } else setCheckNote(checkMeNote(r, conceptNames)); // why nothing was posed
    } catch (err) {
      if (g !== gen.current || epoch !== turnEpoch.current) return;
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail === FEEDBACK_PENDING_DETAIL) {
        dispatch({ type: "check", item: null });
        dispatch({ type: "phase", phase: "feedback" });
        setFeedbackPending(true);
        setCheckNote(FEEDBACK_PENDING_COPY);
        return;
      }
      reportError(err, "Couldn't get a check question.");
    } finally {
      if (g === gen.current) setCheckBusy(false);
    }
  };

  const doClose = async () => {
    if (!sessionId || closeBusy || pendingGrade) return;
    const g = gen.current;
    const sid = sessionId;
    setCloseBusy(true);
    setCloseNote(null);
    try {
      const r = await closeLoopSession(sid, userId);
      // closed whatever the screen shows now: never leave it in the picker
      dropFromPicker(sid);
      if (g !== gen.current) return;
      ++gen.current; // invalidate status snapshots requested before this close
      streamAbort.current?.abort();
      setCloseBusy(false);
      showClose(sid, r);
      setFeedbackPending(false);
      setPrequestion(null);
      setSelfExplain(null);
      dispatch({ type: "check", item: null });
      dispatch({ type: "phase", phase: "close" });
      void refreshGraph();
    } catch (err) {
      if (g !== gen.current) return;
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail && detail !== SESSION_CLOSED_DETAIL) {
        setCloseNote(CLOSE_RETRY_COPY[detail] ?? detail);
        return;
      }
      reportError(err, "Couldn't close the session.");
    } finally {
      if (g === gen.current) setCloseBusy(false);
    }
  };

  // ── Derived view data ──────────────────────────────────────────────────
  const conceptNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const n of graph.nodes) if (n.course_id === courseId) names.set(n.id, n.name);
    for (const c of panelPlanOf(plan, approvedPlan) ?? []) if (c.concept_name) names.set(c.node_id, c.concept_name);
    return names;
  }, [graph.nodes, plan, approvedPlan, courseId]);
  const railGraph = useMemo(() => {
    const nodes = graph.nodes.filter((n) => n.course_id === courseId);
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: graph.edges.filter((e) => ids.has(e.source as string) && ids.has(e.target as string)) };
  }, [graph, courseId]);
  // The deep link's ?suggest= / ?topic= concept, until a turn names one (legacy parity).
  const linkedNodeId = useMemo(() => {
    const want = (deepLink.suggest || deepLink.topic).toLowerCase();
    return want ? railGraph.nodes.find((n) => n.name.toLowerCase() === want)?.id ?? null : null;
  }, [railGraph.nodes, deepLink]);
  const focusNodeId = state.focusNodeId ?? linkedNodeId;
  const learner = state.focusNodeId ? state.learnerState[state.focusNodeId] : undefined;
  const treeHref = focusNodeId ? `/tree?node=${encodeURIComponent(focusNodeId)}` : "/tree";
  const teaching = TEACHING.includes(state.phase);
  const streaming = streamingText !== null;
  // The card shows the current pose and hint, so the log does not paint those
  // rows while the item is current (live and after a reload alike) — nothing
  // renders twice. They stay IN the log, visually hidden (spec §13 A135): the
  // log is a live region, so a screen reader hears the pose and the hint when
  // they arrive, and reads them in order later; un-hiding them after the grade
  // adds no node, so nothing is announced twice.
  const logMessages = useMemo(() => {
    // U2: the opener's row shows the approved plan, never steps already done
    const history = withPlanHistory(messages, panelPlanOf(plan, approvedPlan));
    const inCard = new Set<string>();
    if (item?.prompt) inCard.add(item.prompt);
    if (item && hint && "reply" in hint) inCard.add(hint.reply);
    // spec §13 A138: the guess's pose, while its card shows it
    if (prequestion?.text) inCard.add(prequestion.text);
    return inCard.size === 0
      ? history
      : history.map((m) => (m.role === "assistant" && inCard.has(m.content) ? { ...m, visuallyHidden: true } : m));
  }, [messages, plan, approvedPlan, item, hint, prequestion]);

  // spec §13 A135: apply `focusAfter` once the screen has settled — no reply
  // streaming, the target rendered and enabled. Only a lost focus (left on the
  // page itself when the control that started the action was disabled or
  // removed) moves: new content that took focus first — a posed check, the
  // plan's heading, a dialog — keeps it.
  useLayoutEffect(() => {
    const want = focusAfter.current;
    if (!want) return;
    if (modalOpen()) {
      focusAfter.current = null;
      return;
    }
    if (streaming) return;
    // Lost: on the page itself, or still on the control the action disabled.
    const active = document.activeElement;
    const lost = !active || active === document.body || active.matches(":disabled");
    const answer = rootRef.current?.querySelector<HTMLElement>("[data-answer-start]") ?? null;
    const composer = composerRef.current;
    const target =
      // spec §13 A139: a "why" prompt that replaced the Continue row takes it first
      want === "answered" ? selfExplainRef.current ?? continueRef.current ?? answer ?? checkMeRef.current
        : want === "turn" ? composer
          : want === "check-me" ? checkMeRef.current
            : want === "teaching" ? teachStartRef.current ?? composer
              : answer;
    if (!target) {
      if (!lost) focusAfter.current = null; // the target is gone and focus is held elsewhere: settled
      return;
    }
    if (target.matches(":disabled") || target.getAttribute("aria-disabled") === "true") return;
    focusAfter.current = null;
    if (lost) target.focus();
  });
  // F3: never offered for the session that is already on the link's topic
  const onLinkTopic = (listedTopic ?? "").trim().toLowerCase() === deepLink.topic.toLowerCase();
  const topicOffer =
    allOf(!!deepLink.topic, !!sessionId, teaching, !starting, openSessions !== null, !onLinkTopic) ? deepLink.topic : null;

  // ── Render ─────────────────────────────────────────────────────────────
  const noCourses = courses !== null && courses.length === 0;
  const loadingSessions = allOf(
    !sessionsError, !noCourses, !readOnly, loadError !== "start",
    openSessions === null || (!sessionId && starting),
  );
  // No feedback survey mid-learning (lib/feedbackPacing.ts): an open session
  // holds the shell's prompts through every phase before the wrap-up (the
  // check-in probe, the plan, an open check card, a streaming tutor turn,
  // feedback), as does the boot that is about to resume or start one. The
  // wrap-up releases them: the natural break where a deferred prompt may open.
  useFeedbackHold(anyOf(
    loadingSessions, starting, streaming, !!item, !!pendingGrade,
    allOf(!!sessionId, !readOnly, state.phase !== "close"),
  ));

  // The screen's regions: plain render calls, not components, so React sees
  // the same element tree the inline JSX produced (nothing remounts).
  const inSession = view === "session";
  const sessionRow = findRow(sessionRows, sessionId);
  const panelPlan = panelPlanOf(plan, approvedPlan);
  /** The TopBar's line under the title: where the session is (no step pills). */
  const phaseLine = (): string => {
    if (readOnly) return "Wrapped up · read-only";
    if (!sessionId) return starting ? "Starting…" : "";
    return phaseText(state.phase, panelPlan, focusNodeId ?? cursorNode(approvedPlan), conceptNames);
  };
  const topTitle = (): string => {
    if (view === "home") return "New session";
    if (view === "all") return "All sessions";
    if (view === "course") return course ? `${course.course_code ? `${course.course_code} · ` : ""}${course.course_name}` : "Course";
    if (readOnly) return readOnly.topic || "Earlier session";
    return sessionRow ? sessionTitle(sessionRow, course ?? undefined) : sessionId ? "Guided session" : "Tutor";
  };
  const topSub = (): string => {
    if (view === "home") return "Choose where to start.";
    if (view === "all") return "Newest first.";
    if (view === "course") return "Sessions, material and progress.";
    return phaseLine();
  };
  const showPanel = allOf(inSession, !isMobile, layout.panelOpen, !!sessionId, !readOnly, !sessionsError, !noCourses);
  // A phone has no sidebar or panel on screen: the map and New session sit here.
  const renderMobileActions = () => (
    <>
      {treeVisible && <Link data-testid="loop-tree-link" href={treeHref} className="btn btn--sm btn--ghost">Map</Link>}
      <button
        data-testid="loop-new-session"
        type="button"
        className="btn btn--sm"
        onClick={showHome}
        disabled={!courseId || sessionTransitionBusy}
      >
        + New
      </button>
    </>
  );
  const renderTopActions = () => (
    <div className={tutorStyles.topActs}>
      {view === "course" && (
        <button type="button" className="btn btn--primary" data-testid="tutor-course-start"
          disabled={!courseId || sessionTransitionBusy} onClick={showHome}>
          <Icon name="sparkle" size={14} /> Start a session
        </button>
      )}
      {inSession && sessionId && !readOnly && (state.phase === "probe" || state.phase === "plan") && (
        <button ref={goalButton} type="button" className="btn btn--sm" data-testid="loop-set-goal"
          disabled={starting || probeBusy || planBusy || goalBusy || !scopeReady || !!pendingGrade}
          onClick={() => { setGoalEditor(true); setGoalError(null); }}>
          {goal ? "Edit goal" : "Set goal"}
        </button>
      )}
      {inSession && teaching && sessionId && (
        <button
          data-testid="loop-close-button"
          className="btn btn--sm"
          onClick={() => void doClose()}
          disabled={closeBusy || !!pendingGrade}
          title="Wrap up this session"
        >
          {closeBusy ? "Wrapping up…" : "Wrap up"}
        </button>
      )}
      {isMobile && renderMobileActions()}
      <AIDisclaimerChip height={32} />
      {/* Show only: while the panel is open its own head carries Hide. */}
      {allOf(inSession, !isMobile, !!sessionId, !readOnly, !layout.panelOpen) && (
        <button type="button" className={tutorStyles.iconBtn} data-testid="tutor-panel-toggle"
          aria-label="Show session panel"
          onClick={layout.showPanel}>
          <SidebarGlyph side="right" />
        </button>
      )}
    </div>
  );
  const renderHeader = () => (
    <header className={tutorStyles.topbar}>
      {(!layout.sideOpen || isMobile) && (
        <button type="button" className={tutorStyles.iconBtn} style={{ alignSelf: "center" }}
          data-testid="tutor-sidebar-show" aria-label="Show tutor sidebar" onClick={layout.showSide}>
          <SidebarGlyph />
        </button>
      )}
      <div className={tutorStyles.topTitle}>
        {course && view === "session" ? (
          <button type="button" className={`label-micro ${tutorStyles.crumb}`} data-testid="tutor-crumb-course"
            onClick={() => showCourse(course.course_id)}>
            {course.course_code ? `${course.course_code} · ` : ""}{course.nickname || course.course_name}
          </button>
        ) : (
          <div className={`label-micro ${tutorStyles.crumbStatic}`}>{view === "course" ? "Course" : "Tutor"}</div>
        )}
        <h1 className="h-serif">{topTitle()}</h1>
        <div className={tutorStyles.topSub} data-testid="tutor-phase-line">{topSub()}</div>
      </div>
      {renderTopActions()}
    </header>
  );
  const header = renderHeader();


  // docs/safety/crisis-support.md × spec §13 A128: while a crisis-support card is
  // on screen (the start card, the dialog, or the latest reply in the
  // conversation), the degraded-mode notes stand aside, so nothing operational
  // shows beside the card. They come back once the card is no longer the
  // latest thing on screen. (The budget pause stays: it is the real state.)
  const crisisOnScreen = anyOf(
    !!startCrisis && !sessionId,
    crisisDialogSupport !== null,
    messages[messages.length - 1]?.crisisSupport != null,
  );
  const showPreparing = noCheckItems === "preparing" && !crisisOnScreen;
  const showMaterialsNote = materialsNote && !crisisOnScreen;
  const hasNotices = anyOf(
    !!paused, noCheckItems === "none", showPreparing, showMaterialsNote, !!topicOffer,
    practiceUnavailable.length > 0,
  );
  // Always in the DOM (spec §13 A135): a notice is announced when it is added to
  // this polite region; one inserted together with its own region is not
  // reliably read out.
  const renderNotices = () => (
    <div
      aria-live="polite"
      data-testid="loop-notices"
      style={hasNotices ? { display: "flex", flexDirection: "column", gap: 8, padding: "12px 32px 0" } : undefined}
    >
      {paused && (
        <BudgetPausedBanner
          testId="loop-budget-paused"
          resetAt={paused.resetAt}
          sessionCapped={paused.sessionCapped}
          message={tutorPauseMessage(paused.resetAt, paused.sessionCapped)}
        >
          {studyVisible && <>{" "}<Link data-testid="loop-budget-study-link" href="/study" style={{ color: "var(--accent)", fontWeight: 500 }}>
            Review flashcards
          </Link></>}
        </BudgetPausedBanner>
      )}
      {noCheckItems === "none" && (
        <div
          data-testid="loop-no-check-items"
          role="status"
          style={{ padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--info-soft)", fontSize: 13 }}
        >
          {NO_CHECK_ITEMS_COPY}
        </div>
      )}
      {showPreparing && (
        <div
          data-testid="loop-preparing-items"
          role="status"
          style={{ padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--info-soft)", fontSize: 13 }}
        >
          {PREPARING_COPY}
        </div>
      )}
      {showMaterialsNote && (
        <div
          data-testid="loop-materials-unavailable"
          role="status"
          style={{ padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--info-soft)", fontSize: 13 }}
        >
          {MATERIALS_UNAVAILABLE_COPY}
        </div>
      )}
      {practiceUnavailable.length > 0 && (
        <div data-testid="loop-practice-unavailable" role="status"
          style={{ padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--info-soft)", fontSize: 14, lineHeight: 1.5 }}>
          <p style={{ margin: "0 0 6px" }}>{NO_FRESH_PRACTICE_COPY}</p>
          <p style={{ margin: "0 0 8px", overflowWrap: "anywhere" }}>Practice unavailable: {practiceUnavailable.map((id) => conceptNames.get(id) ?? "A selected concept").join(", ")}.</p>
          {exhaustedPracticeAttempt && <p style={{ margin: "0 0 8px" }}>This session already moved past those concepts. Once new questions are available, start a new session to practise them.</p>}
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {libraryVisible && <Link data-testid="loop-practice-sources" href="/library" className="btn btn--sm btn--ghost" style={{ minHeight: 44, flex: "1 1 130px", whiteSpace: "normal", justifyContent: "center", textAlign: "center" }}>Review source material</Link>}
            {!exhaustedPracticeAttempt && (state.phase === "plan" || (teaching && !item && !feedbackPending)) && (
              <button data-testid="loop-practice-refresh" type="button" className="btn btn--sm"
                style={{ minHeight: 44, flex: "1 1 130px", whiteSpace: "normal" }} disabled={sessionTransitionBusy || streaming || checkBusy}
                onClick={() => {
                  if (!sessionId) return;
                  if (state.phase === "plan") void loadPlan(sessionId, gen.current);
                  else void checkMe();
                }}>Check for fresh practice</button>
            )}
          </div>
        </div>
      )}
      {topicOffer && (
        // ?topic= while a session is open: resume won (a reload never starts a
        // probe, §11.3); the link's concept is one click away, never automatic.
        <div
          data-testid="loop-topic-offer"
          role="status"
          style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 13 }}
        >
          <span style={{ color: "var(--text-dim)" }}>You picked “{topicOffer}”. This session is still open.</span>
          <button
            data-testid="loop-topic-start"
            className="btn btn--sm"
            disabled={sessionTransitionBusy}
            onClick={() => void newSession({ closeCurrent: true, topic: topicOffer, mode: deepLink.mode })}
          >
            Start a session on {topicOffer}
          </button>
        </div>
      )}
    </div>
  );
  const notices = renderNotices();

  const renderLearnerChip = () => (
    <span
      data-testid="loop-learner-state"
      data-node-id={learner?.node_id ?? ""}
      data-p-known={learner ? String(learner.p_known) : ""}
      data-band={learner?.band ?? ""}
      className="chip"
      style={{ visibility: learner ? "visible" : "hidden" }}
    >
      {learner
        ? `${conceptNames.get(learner.node_id) ?? "This concept"} · ${BAND_LABEL[learner.band] ?? learner.band}`
        : "—"}
    </span>
  );
  const learnerChip = renderLearnerChip();

  /** Between checks: Continue (after feedback), Check me, the plan's first
   *  concept, and the check's status line. */
  const renderTeachActions = (firstConcept: LoopPlanConcept | undefined) => (
    <div className={tutorStyles.chatActions}>
      {state.phase === "feedback" && (
        <button
          ref={continueRef}
          data-testid="loop-continue"
          className="btn btn--primary"
          onClick={() => send(CONTINUE_MESSAGE)}
          disabled={!!paused || streaming || starting || scopeLoading}
        >
          {feedbackPending ? "Retry feedback" : "Continue"}
        </button>
      )}
      <button
        ref={checkMeRef}
        data-testid="loop-check-me"
        className={state.phase === "feedback" ? "btn" : "btn btn--primary"}
        onClick={() => void checkMe()}
        disabled={checkBusy || streaming || feedbackPending || starting || scopeLoading}
        title={feedbackPending ? FEEDBACK_PENDING_COPY : "Get a question on this concept"}
      >
        Check me
      </button>
      {feedbackPending && !streaming && !checkNote && <span role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{FEEDBACK_PENDING_COPY}</span>}
      {(messages.length <= 1 || planJustApproved) && firstConcept && state.phase === "teach" && !paused && (
        <button
          ref={teachStartRef}
          data-testid="loop-teach-start"
          className="btn"
          onClick={() => send(`Teach me about ${firstConcept.concept_name}.`)}
          disabled={streaming}
        >
          Start with {firstConcept.concept_name}
        </button>
      )}
      {/* Always in the DOM: a live region inserted with its text already in
          it is not reliably announced (spec §13 A135). */}
      <span aria-live="polite">
        {checkNote && (
          <span
            role="status"
            data-testid={checkNote === REPORTED_COPY ? "loop-check-reported" : undefined}
            style={{ fontSize: 13, color: "var(--text-muted)" }}
          >
            {checkNote}
          </span>
        )}
      </span>
    </div>
  );

  const renderChatHeader = (firstConcept: LoopPlanConcept | undefined) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {askRating && askRating === sessionId && <RatingPrompt onRate={rate} />}
      {item ? (
        <CheckCard
          item={item}
          conceptName={conceptAt(conceptNames, focusNodeId, approvedPlan)}
          draft={attempt}
          setDraft={setAttempt}
          busy={attemptBusy || streaming}
          hint={hint}
          hintBusy={hintBusy}
          hintRetry={hintRetry}
          onSubmit={() => void submitAttempt(false)}
          onIdk={() => void submitAttempt(true)}
          onHint={() => void askHint()}
          onReport={reportsOn ? reportItem : undefined}
          selfExplain={
            // spec §13 A139: the worked example's (or shown solution's) "why"
            // prompt, under the hint — the Hint button keeps focus here
            selfExplain ? (
              <SelfExplainCard
                key={selfExplain.prompt_id}
                prompt={selfExplain}
                nested
                busy={selfExplainBusy || attemptBusy || streaming} saving={selfExplainBusy} onDraft={setExplainDraft}
                onSend={(reply) => void sendSelfExplain(reply)}
                onSkip={() => void sendSelfExplain(null)}
              />
            ) : null
          }
        />
      ) : prequestion ? (
        // spec §13 A138: the segment opens on its ungraded guess (one open prompt)
        <PrequestionCard
          key={prequestion.question_hash}
          prequestion={prequestion}
          busy={prequestionBusy || streaming || starting || scopeLoading}
          onGuess={(guess) => void submitPrequestion(guess)}
          onExplain={() => void submitPrequestion("explain")}
        />
      ) : selfExplain ? (
        // spec §13 A139: the feedback's "why" prompt stands in for Continue / Check me
        <SelfExplainCard
          key={selfExplain.prompt_id}
          prompt={selfExplain}
          inputRef={selfExplainRef}
          busy={selfExplainBusy || streaming || starting || scopeLoading} saving={selfExplainBusy} onDraft={setExplainDraft}
          onSend={(reply) => void sendSelfExplain(reply)}
          onSkip={() => void sendSelfExplain(null)}
        />
      ) : (
        <>
          {state.phase === "feedback" && verdict && (
            <VerdictBanner verdict={verdict.verdict} concept={conceptAt(conceptNames, verdict.nodeId, approvedPlan)} />
          )}
          {renderTeachActions(firstConcept)}
        </>
      )}
      {/* Always in the DOM, so a close that must wait is announced (spec §13 A135). */}
      <div aria-live="polite">
        {closeNote && <div role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{closeNote}</div>}
      </div>
      {/* Always in the DOM, so a saved explanation is announced (spec §13 A139, A135). */}
      <div aria-live="polite">
        {selfExplainSaved && (
          <div role="status" data-testid="loop-self-explain-saved" style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {SELF_EXPLAIN_SAVED_COPY}
          </div>
        )}
      </div>
    </div>
  );

  /** Teach, check and feedback: the conversation, with the check card (or the
   *  open prompt, or the actions between checks) above it. */
  const renderTeach = () => {
    const firstConcept = plan?.[0];
    return (
      <div data-testid="loop-messages" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <ChatPanel
          messages={logMessages}
          composerRef={composerRef}
          onSend={send}
          footer={renderChatHeader(firstConcept)}
          streamingText={streamingText}
          onStop={stop}
          onRetry={retryTurn}
          // spec §13 A138 (review fix): the open guess card is the turn's one
          // open prompt (A121) — answer it, or "No idea", before the chat; F7: a
          // hint that is loading holds it too; K06: so does an open check; Z60: so
          // does an unsent self-explanation
          disabled={anyOf(starting, scopeLoading, guessCardOpen, hintBusy, checkOpen, explainDraft && !!selfExplain)}
          placeholder={
            checkOpen ? CHECK_OPEN_COMPOSER_COPY : guessCardOpen
              ? PREQUESTION_COMPOSER_COPY
              : paused
                ? "Tutor chat is paused — check answers still count."
                : "Ask your AI tutor anything…"
          }
          attachHref={libraryVisible ? "/library" : undefined}
          turnStyle="page"
          draftSeed={chatDraft.text}
          draftSeedKey={chatDraft.key}
        />
      </div>
    );
  };

  const renderBody = (): React.ReactNode => {
    if (sessionsError) {
      return (
        <CenteredCard testId="loop-sessions-error">
          <h2 className="h-serif" style={{ margin: "0 0 6px", fontSize: 20 }}>Couldn&apos;t load your sessions</h2>
          <p style={{ color: "var(--text-dim)", fontSize: 14, margin: "0 0 16px" }}>
            Nothing was started. Try again to pick up where you left off.
          </p>
          <button data-testid="loop-sessions-retry" className="btn btn--primary" onClick={retrySessions}>
            Retry
          </button>
        </CenteredCard>
      );
    } else if (noCourses) {
      return (
        <CenteredCard testId="loop-no-course">
          <h2 className="h-serif" style={{ margin: "0 0 6px", fontSize: 20 }}>Add a course to start learning</h2>
          <p style={{ color: "var(--text-dim)", fontSize: 14, margin: 0 }}>
            {/* Z61: courses are added in the Dashboard's course manager (the Tree has no control for it) */}
            The tutor works course by course — add one from your{" "}
            <Link data-testid="loop-no-course-link" href="/dashboard">dashboard</Link>.
          </p>
        </CenteredCard>
      );
    } else if (readOnly) {
      return (
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px" }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span className="chip">Read-only</span>
              <span style={{ fontSize: 14, color: "var(--text-dim)" }}>
                {readOnly.topic ? `“${readOnly.topic}” — ` : ""}an earlier session. Start a new one to keep learning.
              </span>
              <div style={{ flex: 1 }} />
              <button data-testid="loop-readonly-new-session" className="btn btn--primary btn--sm" disabled={sessionTransitionBusy}
                onClick={() => void newSession({ closeCurrent: true, mode: deepLink.mode })}>
                Start a new session
              </button>
            </div>
            <div
              data-testid="loop-readonly-transcript"
              className="card"
              style={{ padding: "var(--pad-lg)", display: "flex", flexDirection: "column", gap: 12 }}
            >
              {readOnly.messages.length === 0 && (
                <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No messages in this session.</div>
              )}
              {readOnly.messages.map((m) => (
                <div key={m.id} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "85%" }}>
                  <div className="label-micro" style={{ marginBottom: 2 }}>{m.role === "user" ? "You" : "Tutor"}</div>
                  <div
                    style={{
                      whiteSpace: "pre-wrap",
                      fontSize: 14,
                      padding: "8px 12px",
                      borderRadius: "var(--r-md)",
                      background: m.role === "user" ? "var(--accent-soft)" : "var(--bg-soft)",
                    }}
                  >
                    {m.content}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    } else if (startCrisis && !sessionId) {
      // "Back to studying" starts a session on the course itself: the deep-link
      // topic may be the very text the card answered.
      return (
        <CenteredCard testId="loop-start-crisis">
          <CrisisSupportCard support={startCrisis} onDismiss={() => void newSession({ mode: deepLink.mode })} />
        </CenteredCard>
      );
    } else if (loadError === "start" && !sessionId) {
      return (
        <CenteredCard testId="loop-start-error">
          <h2 className="h-serif" style={{ margin: "0 0 6px", fontSize: 20 }}>Couldn&apos;t start a session</h2>
          <p style={{ color: "var(--text-dim)", fontSize: 14, margin: "0 0 16px" }}>
            Nothing was started. Try again in a moment.
          </p>
          <button data-testid="loop-start-retry" className="btn btn--primary" disabled={starting} onClick={() => void retryStart()}>
            Try again
          </button>
        </CenteredCard>
      );
    } else if (loadingSessions) {
      return <div style={{ padding: 40, color: "var(--text-dim)" }}>{starting ? "Starting your session…" : "Loading…"}</div>;
    } else if (pendingGrade) {
      const busy = anyOf(probeBusy, attemptBusy, streaming, starting, scopeLoading);
      return (
        <CenteredCard testId="loop-pending-grade">
          <h2 className="h-serif" style={{ margin: "0 0 8px", fontSize: 22 }}>Finish checking saved answer</h2>
          <p role="status" style={{ fontSize: 14, lineHeight: 1.5, color: "var(--text-dim)", margin: "0 0 16px" }}>
            Your answer was saved before checking finished. Continue with that saved result; you don&apos;t need to answer again.
          </p>
          <button type="button" data-testid="loop-recover-grade" className="btn btn--primary"
            style={{ minHeight: 44, maxWidth: "100%", whiteSpace: "normal" }}
            disabled={busy} aria-busy={busy} onClick={() => void recoverGrade()}>
            {busy ? "Finishing check…" : "Finish checking saved answer"}
          </button>
        </CenteredCard>
      );
    } else if (goalEditor) {
      return <GoalEditor key={`${sessionId}:${courseId}`} goal={goal}
        nodes={railGraph.nodes.filter((node) => !node.is_subject_root)} busy={goalBusy} error={goalError}
        loadingNodes={graphLoading} nodesError={graphError} onRetryNodes={() => void refreshGraph()}
        onSave={(next) => void saveGoal(next)} onCancel={() => { setGoalEditor(false); goalButton.current?.focus(); }} />;
    } else if (state.phase === "probe") {
      return (
        <ProbePanel
          item={probeItem}
          count={probeCount}
          draft={probeDraft}
          setDraft={setProbeDraft}
          reference={probeReference}
          note={probeNote}
          busy={probeBusy}
          loadFailed={loadError === "probe"}
          greeting={messages.find((m) => m.role === "assistant")?.content ?? null}
          onSubmit={() => void submitProbe(false)}
          onIdk={() => void submitProbe(true)}
          onNext={() => void advanceProbe(probeFinished, gen.current)}
          onRetry={() => { if (sessionId) void nextProbe(sessionId, gen.current); }}
        />
      );
    } else if (state.phase === "plan") {
      return (
        <PlanPanel
          diagnosis={diagnosis}
          names={conceptNames}
          plan={plan}
          busy={planBusy}
          loadFailed={loadError === "plan"}
          onApprove={() => void approvePlan()}
          onRetry={() => { if (sessionId) void loadPlan(sessionId, gen.current); }}
        />
      );
    } else if (state.phase === "close") {
      return <ClosePanel close={close} note={closeNote} names={conceptNames} courseId={courseId} onNew={showHome}
        studyVisible={studyVisible} rating={wrapUpAsk?.sessionId === sessionId ? wrapUpAsk : null} />;
    }
    return renderTeach();
  };
  const body = renderBody();

  const renderScopeSummary = () => (
    <div className={styles.scopeSummary} data-testid="loop-goal-summary">
      {scopeError ? <><span>Couldn&apos;t load this session&apos;s learning scope. </span>
        <button type="button" data-testid="loop-goal-retry" className="btn btn--sm" onClick={() => void retryLearningScope()}>Retry learning scope</button></>
        : !scopeReady ? "Loading learning scope…"
          : goal ? <><strong>Goal: </strong>{goal.text || "Selected concepts"}<span> · {goal.target_node_ids.map((id) => conceptNames.get(id) ?? "Selected concept").join(", ")}</span></>
            : "Scope: Explore the whole course"}
    </div>
  );
  const renderGoalProgress = (progress: LoopGoalProgress) => (
    <div data-testid="loop-goal-progress" role="status" className={styles.scopeSummary}>
      {progress.status === "continue_available"
        ? "The next step toward your goal is ready to review. Approve the new plan before continuing."
        : progress.status === "needs_more_practice"
          ? "Your goal still needs prerequisite practice. Review source material; more practice is needed before the goal can continue."
          : "You finished the practice planned for this session. This does not establish mastery; check what you retain after time away."}
      {progress.unresolved_prerequisite_ids.length > 0 && <span> Prerequisites needing practice: {progress.unresolved_prerequisite_ids.map((id) => conceptNames.get(id) ?? "A prerequisite").join(", ")}.</span>}
      {progress.remaining_target_node_ids.length > 0 && <span> Goal concepts remaining: {progress.remaining_target_node_ids.map((id) => conceptNames.get(id) ?? "A selected concept").join(", ")}.</span>}
    </div>
  );
  /** Skill per concept in today's plan (else the concept being taught): the
   *  loop's own estimate when it has one, else the map's mastery. */
  const panelSkills = (): PanelConcept[] => {
    const ids = panelPlan && panelPlan.length > 0 ? panelPlan.map((c) => c.node_id) : focusNodeId ? [focusNodeId] : [];
    return ids.map((id) => {
      // measured only: the loop's estimate once this session observed the
      // concept, else the map's mastery. The plan's p_known for an untested
      // concept is the prior, not a measurement — it reads "Not started".
      const live = state.learnerState[id]?.p_known;
      const node = railGraph.nodes.find((n) => n.id === id);
      const mapScore = node && node.mastery_tier !== "unexplored" ? node.mastery_score : null;
      return { nodeId: id, name: conceptNames.get(id) ?? "Concept", score: live ?? mapScore };
    });
  };
  const dueHref = studyVisible ? dueLink(dueCourseIds) : null;
  const renderRail = () => (
    <SessionPanel
      plan={state.phase === "plan" ? null : panelPlan}
      currentNodeId={teaching ? focusNodeId ?? cursorNode(approvedPlan) : null}
      skills={panelSkills()}
      dueCount={lists.dueReviews}
      dueHref={dueHref}
      learnerChip={learnerChip}
      hasLearner={!!learner}
      treeHref={treeHref}
      showTreeLink={allOf(!isMobile, treeVisible)}
      onHide={layout.hidePanel}
      map={railGraph.nodes.length > 0 ? (
        <SessionMap nodes={railGraph.nodes} edges={railGraph.edges} highlightId={focusNodeId ?? undefined} />
      ) : graphError ? <LoadFailed testId="tutor-map-error" what="your map" onRetry={() => void refreshGraph()} /> : (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Concepts appear here as you learn.</div>
      )}
    />
  );

  const renderHome = () => {
    const openHere = sessionRows.find((r) => r.open && r.courseId === courseId) ?? null;
    const leaving = allOf(!!sessionId, !readOnly, isOpenPhase(state.phase));
    return (
      <div className={tutorStyles.scroll}>
        <TutorHome
          courseName={course?.course_name ?? null}
          continueRow={openHere}
          continueTitle={openHere ? sessionTitle(openHere, course ?? undefined) : undefined}
          dueCount={lists.dueReviews}
          dueHref={dueHref}
          startWith={weakestConcept(railGraph.nodes)}
          busy={anyOf(!courseId, sessionTransitionBusy, openSessions === null)} starting={starting}
          closesCurrent={leaving ? sessionTitle(sessionRow ?? { topic: "" }, course ?? undefined) : listedOpenTitle(sessionId, openSessions, course ?? undefined)}
          onContinue={() => { if (openHere) openRow(openHere); }}
          onStart={() => void startGuided()}
          onStartWith={(topic) => void startGuided({ topic })}
          onGoal={() => void startGuided({ goal: true })}
        />
      </div>
    );
  };
  const renderCourse = (c: EnrolledCourse) => (
    <div className={tutorStyles.scroll}>
      <TutorCourse
        course={c}
        sessions={sessionRows.filter((r) => r.courseId === c.course_id)}
        concepts={railGraph.nodes.filter((n) => !n.is_subject_root)}
        materials={lists.materials && lists.materials.filter((m) => m.course_id === c.course_id)}
        dueHref={dueHref}
        libraryHref={libraryVisible ? "/library" : null}
        onRetrySessions={lists.retryRecent}
        onRetryMaterials={lists.retryMaterials} onRetryConcepts={graphError ? () => void refreshGraph() : null}
        onOpen={openRow}
        onAll={showAll}
      />
    </div>
  );
  const renderAll = () => (
    <div className={tutorStyles.scroll}>
      <TutorAllSessions
        sessions={sessionRows}
        courses={courses ?? []}
        query={allQuery}
        setQuery={setAllQuery}
        filter={allFilter}
        setFilter={setAllFilter}
        onRetry={lists.retryRecent}
        onOpen={openRow}
      />
    </div>
  );
  const renderSession = () => {
    const live = allOf(!!sessionId, !readOnly);
    return (
      <>
        {/* the conversation column's first row (design T4-T10, anatomy D) */}
        {live && <PhaseStepper phase={state.phase} />}
        {live && state.phase !== "close" && renderScopeSummary()}
        {goalProgress && goal && renderGoalProgress(goalProgress)}
        {notices}
        {allOf(!showPanel, live, !!learner) && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px clamp(16px, 4vw, 56px) 0" }}>
            {learnerChip}
          </div>
        )}
        {body}
      </>
    );
  };
  /** The main column's page: T1 home, T2 course, T3 all sessions, else the session. */
  const renderPage = (): React.ReactNode => {
    const pageable = !sessionsError && !noCourses;
    if (view === "home" && pageable) return renderHome();
    if (view === "course" && course) return renderCourse(course);
    if (view === "all") return renderAll();
    return renderSession();
  };

  const renderSidebar = () => (
    <TutorSidebar
      courses={courses}
      courseId={courseId}
      sessions={sessionRows}
      currentSessionId={inSession ? readOnly?.id ?? sessionId : null}
      currentCourseView={view === "course" ? courseView : null}
      query={sideQuery}
      setQuery={setSideQuery}
      newDisabled={!courseId || sessionTransitionBusy}
      showNew={!isMobile}
      onNew={showHome}
      onCourse={showCourse}
      onOpen={openRow}
      onAll={showAll}
      onHide={layout.hideSide}
      onRetryRecent={lists.retryRecent}
    />
  );

  return (
    <FullHeightScreen className={`${styles.screen} fade-in`}>
      <DisclaimerModal />
      {crisisDialog}
      <div
        ref={rootRef}
        data-testid="loop-phase"
        data-phase={state.phase}
        data-session-id={sessionId ?? ""}
        data-view={view}
        className={tutorStyles.shell}
      >
        {layout.sideOpen && !isMobile && renderSidebar()}
        {/* A phone: the sidebar is a modal drawer over the whole app (F6). */}
        {layout.sideOpen && isMobile && <TutorDrawer label="Tutor sessions" onClose={layout.hideSide}>{renderSidebar()}</TutorDrawer>}
        <div className={tutorStyles.main}>
          {header}
          <div className={tutorStyles.body}>
            <div className={tutorStyles.center}>{renderPage()}</div>
            {showPanel && renderRail()}
          </div>
        </div>
      </div>
    </FullHeightScreen>
  );
}

function dueLink(courseIds: string[]): string {
  return courseIds.length > 0 ? retentionHref(courseIds) : "/study";
}

/** The plan the panel lists: the one on screen, else the approved one /status reported. */
function panelPlanOf(plan: LoopPlanConcept[] | null, approved: { concepts: LoopPanelConcept[] } | null): LoopPanelConcept[] | null {
  return plan ?? approved?.concepts ?? null;
}

/** The name of `id`, else of the approved plan's current concept. */
function conceptAt(names: Map<string, string>, id: string | null, approved: { concepts: LoopPanelConcept[]; cursor: number } | null): string | null {
  const at = id ?? cursorNode(approved);
  return at ? names.get(at) ?? null : null;
}

/** The concept the approved plan's cursor is on (a resumed session's current one). */
function cursorNode(p: { concepts: LoopPanelConcept[]; cursor: number } | null): string | null {
  return p?.concepts[p.cursor]?.node_id ?? null;
}

function findRow(rows: TutorSessionRow[], id: string | null): TutorSessionRow | null {
  return id ? rows.find((r) => r.id === id) ?? null : null;
}

/** Where an open session is, in words: "Check-in", "Plan · 3 concepts",
 *  "Recursion · concept 2 of 3", "Wrap-up". */
function phaseText(phase: LoopPhase, plan: LoopPanelConcept[] | null, focus: string | null, names: Map<string, string>): string {
  const n = plan?.length ?? 0;
  if (phase === "probe") return "Check-in";
  if (phase === "plan") return n ? `Plan · ${n} ${n === 1 ? "concept" : "concepts"}` : "Plan";
  if (phase === "close") return "Wrap-up";
  const name = focus ? names.get(focus) : undefined;
  const at = plan && focus ? plan.findIndex((c) => c.node_id === focus) : -1;
  if (name && at >= 0) return `${name} · concept ${at + 1} of ${n}`;
  // an approved plan with no current concept: its cursor is past the end
  return name ?? (n > 0 ? "Plan complete" : "Learning");
}

/** The concept T1 offers as a first focus: the weakest one not yet mastered. */
function weakestConcept(nodes: GraphNode[]): string | null {
  const open = nodes.filter((n) => !n.is_subject_root && n.mastery_tier !== "mastered");
  open.sort((a, b) => a.mastery_score - b.mastery_score);
  return open[0]?.name ?? null;
}

/** A session the "New session" button should wrap up first: one the student is in. */
function isOpenPhase(phase: LoopPhase): boolean {
  return phase !== "close";
}

// ── Pieces ─────────────────────────────────────────────────────────────────


const VERDICT_COPY: Record<string, { title: string; note: string }> = {
  correct: { title: "Correct", note: "That answer counts toward this concept." },
  not_yet: { title: "Not yet", note: "The tutor's reply above shows what to fix. Try another one on the same idea." },
  idk: { title: "Not yet", note: "No problem — the tutor's reply above walks through it." },
};

/** Wireframe T9: the graded check's verdict, above the tutor's feedback. */
function VerdictBanner({ verdict, concept }: { verdict: string; concept: string | null }) {
  const copy = VERDICT_COPY[verdict] ?? VERDICT_COPY.not_yet;
  const yes = verdict === "correct";
  return (
    <div data-testid="loop-verdict" data-verdict={verdict} className={`${yes ? tutorStyles.verdictYes : tutorStyles.verdictNo} fade-in`}>
      {concept && <span className="label-micro">{concept} · check</span>}
      <div style={{ font: "600 17px var(--font-display)", color: yes ? "var(--sap-600)" : "var(--warn)" }}>{copy.title}</div>
      <div style={{ fontSize: 14 }}>{copy.note}</div>
    </div>
  );
}

/** One tutor turn outside the chat log (the check-in opener, the plan's intro),
 *  on the page as the conversation's turns are (`PageTurn`). */
function TutorTurn({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return <PageTurn plain testId={testId}>{children}</PageTurn>;
}

function ProbePanel({
  item, count, draft, setDraft, reference, note, busy, loadFailed, greeting, onSubmit, onIdk, onNext, onRetry,
}: {
  item: LoopProbeItem | null;
  count: number;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  reference: string | null;
  note: string | null;
  busy: boolean;
  /** The next item failed to load (not a pause): offer a retry, never an empty card. */
  loadFailed: boolean;
  /** The session opener: in the probe phase always a template — a welcome and
   *  the check-in's intro, no teaching and no question (spec §13 A121). */
  greeting: string | null;
  onSubmit: () => void;
  onIdk: () => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  const mc = item?.format === "mc_reason";
  // K02: an mc_reason answer needs its reason too (the grader judges it, never the option alone)
  const canSubmit = !!item && !busy && (mc ? draft.option !== "" && draft.reason.trim() !== "" : draft.answer.trim() !== "");
  const ids = useId();
  const promptId = `${ids}-prompt`;
  const headingId = `${ids}-question`;
  const cardRef = useRef<HTMLElement>(null);
  const referenceRef = useRef<HTMLDivElement>(null);
  // spec §13 A135: a new question takes focus — its answer box, described by
  // the question (or the options' tab stop, named by it) — so a screen reader
  // reads the question and the student can answer at once.
  const questionHash = item?.question_hash;
  useLayoutEffect(() => {
    if (!questionHash || modalOpen()) return;
    focusAnswerStart(cardRef.current);
  }, [questionHash]);
  // ...and the answer shown after a miss takes focus, so it is read out.
  useLayoutEffect(() => {
    if (reference === null || modalOpen()) return;
    referenceRef.current?.focus();
  }, [reference]);
  const referenceBlock = (
    <div
      ref={referenceRef}
      tabIndex={-1}
      data-testid="loop-probe-reference"
      style={{
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        fontSize: 14,
        ...(item ? { padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--bg-soft)" } : null),
      }}
    >
      <div className="label-micro" style={{ marginBottom: 4 }}>Here&apos;s the answer</div>
      {reference}
    </div>
  );
  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className={tutorStyles.col}>
        <h2 className={tutorStyles.sr}>Quick check-in</h2>
        <TutorTurn testId="loop-probe-greeting">
          {greeting ?? "Let's start with a quick check-in so I know where you are. No hints here; it just shows me what to teach."}
        </TutorTurn>
        {/* The coverage summary reads the check-in's results: it shows on the plan,
            once there is something to summarise, not over the first question. */}
        {!item && busy && <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Loading the next question…</div>}
        {!item && reference !== null && (
          <div className="card" style={{ padding: "var(--pad-xl)", display: "flex", flexDirection: "column", gap: 12 }}>
            {referenceBlock}
            <button data-testid="loop-probe-next" className="btn btn--primary" disabled={busy} onClick={onNext}>
              Next
            </button>
          </div>
        )}
        {!item && !busy && loadFailed && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: "var(--text-muted)" }}>
            <span>The next question didn&apos;t load.</span>
            <button data-testid="loop-probe-retry" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}
        {item && (
          <section
            ref={cardRef}
            aria-labelledby={headingId}
            data-testid="loop-probe-item"
            data-question-hash={item.question_hash}
            data-difficulty={item.difficulty}
            className={`card ${tutorStyles.qcard}`}
          >
            <div className={tutorStyles.qhead}>
              <h3 id={headingId} className={`label-micro ${tutorStyles.qlabel}`}>Check-in · Question {count + (reference === null ? 1 : 0)}</h3>
              <span className="chip">No hints</span>
            </div>
            <p id={promptId} className={tutorStyles.q}>{item.prompt}</p>
            {reference === null ? (
              <>
                {mc ? (
                  <>
                    <OptionList
                      options={item.options ?? []}
                      selected={draft.option}
                      onSelect={(letter) => setDraft((d) => ({ ...d, option: letter }))}
                      testIdPrefix="loop-probe-option"
                      labelledBy={promptId}
                      disabled={busy}
                    />
                    <label className={tutorStyles.fl} htmlFor={`${ids}-reason`} style={{ marginBottom: -8 }}>In one sentence: why?</label>
                    <input
                      id={`${ids}-reason`}
                      data-testid="loop-probe-reason"
                      style={FIELD_STYLE}
                      placeholder="Because…"
                      value={draft.reason}
                      disabled={busy}
                      onChange={(e) => {
                        const reason = e.target.value;
                        setDraft((d) => ({ ...d, reason }));
                      }}
                    />
                  </>
                ) : (
                  <textarea
                    data-testid="loop-probe-input"
                    data-answer-start=""
                    aria-label="Check-in answer"
                    aria-describedby={promptId}
                    style={FIELD_STYLE}
                    rows={3}
                    placeholder={item.format === "teachback" ? "Explain it in your own words" : "Your answer"}
                    value={draft.answer}
                    disabled={busy}
                    onChange={(e) => {
                      const answer = e.target.value;
                      setDraft((d) => ({ ...d, answer }));
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) onSubmit();
                    }}
                  />
                )}
                <ConfidenceControl
                  testIdPrefix="loop-probe-confidence"
                  value={draft.confidence}
                  onChange={(confidence) => setDraft((d) => ({ ...d, confidence }))}
                  disabled={busy}
                />
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button data-testid="loop-probe-submit" className="btn btn--primary" disabled={!canSubmit} onClick={onSubmit}>
                    {busy ? "Checking…" : "Submit answer"}
                  </button>
                  <button data-testid="loop-probe-idk" className="btn btn--ghost" disabled={busy} onClick={onIdk}>
                    I don&apos;t know
                  </button>
                </div>
              </>
            ) : (
              <>
                {referenceBlock}
                <button
                  data-testid="loop-probe-next"
                  className="btn btn--primary"
                  style={{ alignSelf: "flex-start" }}
                  disabled={busy}
                  onClick={onNext}
                >
                  Next
                </button>
              </>
            )}
          </section>
        )}
        {note && <div role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{note}</div>}
      </div>
    </div>
  );
}

function PlanPanel({
  plan, busy, loadFailed, onApprove, onRetry, diagnosis, names,
}: {
  diagnosis: LoopDiagnosis | null;
  names: Map<string, string>;
  plan: LoopPlanConcept[] | null;
  busy: boolean;
  loadFailed: boolean;
  onApprove: () => void;
  onRetry: () => void;
}) {
  // spec §13 A135: the plan replaces the check-in (or its retry), so its heading
  // takes focus — read out, and the place Tab continues from.
  const headingRef = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (!modalOpen()) headingRef.current?.focus();
  }, []);
  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className={tutorStyles.col}>
      <TutorTurn>Here&apos;s today&apos;s plan. Due reviews come first, then what&apos;s new, then related practice.</TutorTurn>
      <section
        aria-labelledby="loop-plan-heading"
        className={`card ${tutorStyles.qcard}`}
      >
        <div className={tutorStyles.qhead}>
          <h2 id="loop-plan-heading" ref={headingRef} tabIndex={-1} className={`label-micro ${tutorStyles.qlabel}`}>
            Today&apos;s plan
          </h2>
        </div>
        <DiagnosisSummary diagnosis={diagnosis} names={names} />
        {plan === null && !loadFailed && <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Building your plan…</div>}
        {plan === null && loadFailed && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: "var(--text-muted)" }}>
            <span>Today&apos;s plan didn&apos;t load.</span>
            <button data-testid="loop-plan-retry" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}
        {plan !== null && plan.length === 0 && (
          <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Nothing to plan right now — ask the tutor anything.</div>
        )}
        {plan && plan.length > 0 && (
          <ol aria-label="Concepts in today's plan" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {plan.map((c, i) => {
              const kind = planKind(c.kind);
              const why = planGoalReason(c.reason);
              return (
                <li
                  key={c.node_id}
                  data-testid={`loop-plan-concept-${c.node_id}`}
                  className={`${styles.planItem} ${tutorStyles.planRow} ${i === 0 ? tutorStyles.planCur : ""}`}
                >
                  <span className={tutorStyles.planBox} aria-hidden>{i + 1}</span>
                  <span style={{ flex: "1 1 100px", minWidth: 0, overflowWrap: "anywhere", fontSize: 14, fontWeight: 500 }}>{c.concept_name || "Concept"}
                    {why && <span data-testid={`loop-plan-reason-${c.node_id}`} className={tutorStyles.ps} style={{ display: "block", marginTop: 2, fontWeight: 400 }}>{why}</span>}
                  </span>
                  {c.band && <span className="chip">{BAND_LABEL[c.band] ?? c.band}</span>}
                  {kind && <span data-testid={`loop-plan-kind-${c.node_id}`} className={kind.chip}>{kind.label}</span>}
                </li>
              );
            })}
          </ol>
        )}
        {plan && plan.length > 0 && (
          <button
            data-testid="loop-plan-approve"
            className="btn btn--primary"
            style={{ alignSelf: "flex-start" }}
            disabled={busy}
            onClick={onApprove}
          >
            <Icon name="sparkle" size={14} /> {busy ? "Saving…" : "Start learning"}
          </button>
        )}
      </section>
      </div>
    </div>
  );
}

function CheckCard({
  item, conceptName, draft, setDraft, busy, hint, hintBusy, hintRetry, onSubmit, onIdk, onHint, onReport, selfExplain,
}: {
  item: LoopCheckItem;
  /** The concept the check is on (the chip in the card's head). */
  conceptName?: string | null;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  busy: boolean;
  hint: HintView;
  hintBusy: boolean;
  hintRetry: boolean;
  onSubmit: () => void;
  onIdk: () => void;
  onHint: () => void;
  /** spec §13 A113: present while the `item_reports` flag is on. */
  onReport?: (reason: LoopReportReason) => Promise<boolean>;
  /** spec §13 A139: an open "why" prompt, rendered under the hint it follows. */
  selfExplain?: React.ReactNode;
}) {
  const mc = item.format === "mc_reason";
  // K02: an mc_reason answer needs its reason; K09: a loading hint (its rung already charged) is shown first
  const canSubmit = !busy && !hintBusy && (mc ? draft.option !== "" && draft.reason.trim() !== "" : draft.answer.trim() !== "");
  const ids = useId();
  const headingId = `${ids}-heading`;
  const promptId = `${ids}-prompt`;
  const cardRef = useRef<HTMLElement>(null);
  // spec §13 A135: a posed check takes focus — its answer box, described by the
  // question (or the options' tab stop, named by it): a screen reader is told a
  // question appeared, and the student can answer at once. The pose and the
  // hint also stay in the conversation log (visually hidden while the card
  // shows them), so they are announced as they arrive.
  useLayoutEffect(() => {
    if (modalOpen()) return;
    focusAnswerStart(cardRef.current);
  }, [item.question_hash]);
  // While a hint loads the Hint button keeps focus (aria-disabled, not
  // disabled: a disabled control drops focus to the page).
  const hintUnavailable = hintBusy || busy;
  return (
    <section
      ref={cardRef}
      aria-labelledby={headingId}
      className={`card ${tutorStyles.qcard}`}
    >
      <div
        data-testid="loop-check-prompt"
        data-question-hash={item.question_hash}
        data-format={item.format}
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <div className={tutorStyles.qhead}>
          <h2 id={headingId} className={`label-micro ${tutorStyles.qlabel}`}>Check your understanding</h2>
          {conceptName && <span className="chip">{conceptName}</span>}
        </div>
        <p id={promptId} className={tutorStyles.q}>{item.prompt}</p>
      </div>
      {mc ? (
        <>
          <OptionList
            options={item.options ?? []}
            selected={draft.option}
            onSelect={(letter) => setDraft((d) => ({ ...d, option: letter }))}
            testIdPrefix="loop-attempt-option"
            labelledBy={promptId}
            disabled={busy}
          />
          <label className={tutorStyles.fl} htmlFor={`${ids}-reason`} style={{ marginBottom: -8 }}>Your reasoning</label>
          <input
            id={`${ids}-reason`}
            data-testid="loop-attempt-reason"
            style={FIELD_STYLE}
            placeholder="In one sentence: why?"
            value={draft.reason}
            disabled={busy}
            onChange={(e) => {
              const reason = e.target.value;
              setDraft((d) => ({ ...d, reason }));
            }}
          />
        </>
      ) : (
        <>
        <label className={tutorStyles.fl} htmlFor={`${ids}-answer`} style={{ marginBottom: -8 }}>Your answer — this is what gets checked</label>
        <textarea
          id={`${ids}-answer`}
          data-testid="loop-attempt-input"
          data-answer-start=""
          aria-describedby={promptId}
          style={FIELD_STYLE}
          rows={2}
          placeholder={item.format === "teachback" ? "Explain it in your own words" : ""}
          value={draft.answer}
          disabled={busy}
          onChange={(e) => {
            const answer = e.target.value;
            setDraft((d) => ({ ...d, answer }));
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) onSubmit();
          }}
        />
        </>
      )}
      <ConfidenceControl
        testIdPrefix="loop-check-confidence"
        value={draft.confidence}
        onChange={(confidence) => setDraft((d) => ({ ...d, confidence }))}
        disabled={busy}
      />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button data-testid="loop-attempt-submit" className="btn btn--primary" disabled={!canSubmit} onClick={onSubmit}>
          Submit answer
        </button>
        <button
          data-testid="loop-hint-button"
          className="btn"
          aria-disabled={hintUnavailable}
          style={hintUnavailable ? { cursor: "not-allowed" } : undefined}
          onClick={() => {
            if (!hintUnavailable) onHint();
          }}
        >
          <Icon name="sparkle" size={13} />{hintBusy ? "Hint…" : hintRetry ? "Retry earned hint" : "Hint"}
        </button>
        <button data-testid="loop-attempt-idk" className="btn btn--ghost" disabled={busy || hintBusy} onClick={onIdk}>
          I don&apos;t know
        </button>
      </div>
      {/* Always in the DOM, so a refusal is announced when it appears. */}
      <div aria-live="polite">
        {hint && "denied" in hint && (
          <div
            data-testid="loop-hint-denied"
            data-reason={hint.denied}
            role="status"
            style={{ fontSize: 13, color: "var(--text-muted)" }}
          >
            {HINT_DENIED_COPY[hint.denied] ?? HINT_DENIED_FALLBACK}
          </div>
        )}
      </div>
      {hint && "reply" in hint && (
        <div
          data-testid="loop-hint-reply"
          style={{
            fontSize: 14,
            padding: "10px 12px",
            borderRadius: "var(--r-md)",
            border: "1px solid var(--accent-border)",
            background: "var(--accent-soft)",
            whiteSpace: "pre-wrap",
            display: "flex",
            gap: 8,
          }}
        >
          <span style={{ color: "var(--accent)", marginTop: 2 }} aria-hidden><Icon name="sparkle" size={13} /></span>
          <span>{hint.reply}</span>
        </div>
      )}
      {selfExplain}
      {onReport && <ReportQuestion testIdPrefix="loop-check-report" disabled={busy} onReport={onReport} />}
    </section>
  );
}
