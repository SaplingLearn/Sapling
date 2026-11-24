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
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { FullHeightScreen } from "../FullHeightScreen";
import { DisclaimerModal } from "../DisclaimerModal";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { ChatPanel, type ChatMsg } from "../chat/ChatPanel";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { extractErrorDetail, humanizeError } from "@/lib/errorMessage";
import { apiToGraphNode, type GraphEdge, type GraphNode } from "@/lib/data";
import type { GraphEdge as ApiEdge, GraphNode as ApiNode } from "@/lib/types";
import {
  answerLoopProbe,
  approveLoopPlan,
  loopPauseOf,
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
  type LoopPendingGrade,
  type LoopPhase,
  type LoopPlanConcept,
  type LoopPlanPrereqEdge,
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
} from "@/lib/api";
import { useFlag } from "@/context/FlagsContext";
import { useStudyNavShown } from "../useRetentionNav";
import { forgetEndedSession, noteLearningSession, useFeedbackHold } from "@/lib/feedbackPacing";
import { useHypercorrectionDwell } from "@/lib/hypercorrectionDwell";
import { checkIsOpen, hintTurnEvents, initialLoopState, reduceLoopEvent } from "./loopState";
import { hasDeepLink, readDeepLink } from "./deepLink";
import styles from "./LoopLearn.module.css";
import { GoalEditor, GoalProgressNote, ScopeSummary } from "./LearningScope";
import { CrisisSupportCard, useCrisisSupport } from "../safety/CrisisSupportCard";
import { crisisSupportIn, crisisSupportInError, takeNoteCardShown, type CrisisSupport } from "@/lib/crisisSupport";
import { PrequestionCard, renderGuess } from "./PrequestionCard";
import { SelfExplainCard } from "./SelfExplainCard";
import { useRetentionDue } from "@/context/RetentionDueContext";
import { Icon } from "../Icon";
import { TutorSidebar } from "./tutor/TutorSidebar";
import { LoadFailed, TutorAllSessions, TutorCourse, TutorHome, type SessionFilter } from "./tutor/TutorPages";
import { SessionPanel, type PanelConcept } from "./tutor/SessionPanel";
import { SessionMap } from "./tutor/SessionMap";
import { PhaseStepper } from "./tutor/PhaseStepper";
import { TutorDrawer } from "./tutor/TutorDrawer";
import { useTutorLayout } from "./tutor/useTutorLayout";
import { useTutorCourses, useTutorLists } from "./tutor/useTutorLists";
import { useSessionEdits } from "./tutor/useSessionEdits";
import { SidebarGlyph } from "./tutor/TutorIcons";
import { listedOpenTitle, mergeSessions, sessionTitle, sessionToLeave, type TutorSessionRow } from "./tutor/sessions";
import tutorStyles from "./tutor/tutor.module.css";
import { CenteredCard } from "./CenteredCard";
import { ClosePanel } from "./ClosePanel";
import { RatingPrompt } from "./RatingPrompt";
import { claimWrapUpAsk, useWrapUpAsk } from "./WrapUpRating";
import { checkMeFailure, checkMeNote, FEEDBACK_PENDING_COPY } from "./checkNote";
import { TeachActions } from "./TeachActions";
import { LearnerChip } from "./LearnerChip";
import { SESSION_CLOSED_DETAIL, sessionRefusal } from "./sessionErrors";
import { withPlanHistory } from "./loopHistory";
import { dropInterruptedTurn } from "./chatRetry";
import { modalOpen } from "./modalOpen";
import { hintDenial, type Draft, type HintView } from "./loopShared";
import { VerdictBanner } from "./VerdictBanner";
import { ProbePanel } from "./ProbePanel";
import { PlanPanel } from "./PlanPanel";
import { CheckCard } from "./CheckCard";
import { LoopNotices } from "./LoopNotices";
import { ReadOnlyTranscript } from "./ReadOnlyTranscript";
import {
  conceptAt, conceptGoal, currentConcept, dueLink, findRow, isOpenPhase, linkGoal, nextAfterVerdict, panelPlanOf, phaseText,
  tutorTopSub, tutorTopTitle,
  weakestConcept, type ApprovedPlan,
} from "./tutor/sessionView";

// ── Copy ─────────────────────────────────────────────────────────────────
const PROBE_UNAVAILABLE_COPY = "Couldn't grade that one — here's another.";
const PROBE_REFUSED_COPY = "Answer in your own words — that read as instructions to the grader.";
const CLOSED_ELSEWHERE_COPY = "This session was closed — start a new one to keep learning.";
/** K26: a request the session's phase refused (another tab or device moved it). */
const MOVED_ELSEWHERE_COPY = "This session moved on in another tab — here's where it is now.";
const CONTINUE_MESSAGE = "Let's continue.";
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


/** 409s from POST /close while a claim is live (A60): the student retries. */
const CLOSE_RETRY_COPY: Record<string, string> = {
  "a check is being graded; close again in a moment": "A check is still being graded — close again in a moment.",
  "session close in progress": "This session is already closing — try again in a moment.",
};
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

const TEACHING: readonly LoopPhase[] = ["teach", "check", "feedback"];


let msgSeq = 0;
const msgId = (prefix: string) => `${prefix}-${Date.now()}-${++msgSeq}`;
const asMsg = (role: "user" | "assistant", content: string, extra?: Partial<ChatMsg>): ChatMsg => ({
  id: msgId(role), role, content, ...extra,
});
/** W4.3: calm grounded chrome only when the server says passages were in the prompt. */
const groundedExtra = (res: { materials_grounded?: boolean }): Partial<ChatMsg> =>
  res.materials_grounded ? { materialsGrounded: true } : {};
const toChat = (rows: { id: string; role: string; content: string }[] | undefined): ChatMsg[] =>
  (rows ?? [])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content }));
const EMPTY_DRAFT: Draft = { answer: "", option: "", reason: "", reasoning: "", confidence: null };

/** The answer fields a draft submits: `confidence` only when chosen (A127).
 *  Free/teachback may include optional `reasoning` (W2.3; never evidence). */
function draftAnswer(draft: Draft, format: string): LoopCheckAnswer {
  const a: LoopCheckAnswer = format === "mc_reason"
    ? { option: draft.option, reason: draft.reason, idk: false }
    : {
      answer: draft.answer,
      idk: false,
      ...(draft.reasoning.trim() ? { reasoning: draft.reasoning.trim() } : {}),
    };
  return draft.confidence ? { ...a, confidence: draft.confidence } : a;
}
/** The Tutor's main column: a session (T4–T15), the Tutor home (T1), a course
 *  page (T2), every session (T3), or the home's goal editor before a start (K30). */
type TutorView = "session" | "home" | "course" | "all" | "goal";


/** The phase GET /status reports for a document, in the UI's vocabulary. */
const statusPhase = (st: LoopSessionStatus) => (st.loop_phase === "teach" ? st.phase : st.loop_phase);

// ── Keyboard focus (spec §13 A135) ────────────────────────────────────────
// Every focus move runs in a layout effect, synchronously with the commit that
// shows the new content. A passive effect could still be pending when the next
// input event arrives; React then flushes it inside that event, and the focus
// change it makes dispatches a nested event that restores the controlled field
// before its new value has rendered.
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
  const quizVisible = useFlag("hide_quiz") !== "on";
  const handoffVisibility = {
    study: studyVisible,
    tutor: true, // this screen is Tutor; hide_tutor would not render LoopLearn
    quiz: quizVisible,
    tree: treeVisible,
  };
  // A session picked in another course: resumed once that course's sessions list.
  const pendingResume = useRef<string | null>(null);

  // Course + sessions
  const [courses, setCourses] = useState<EnrolledCourse[] | null>(null);
  const [courseId, setCourseId] = useState<string | null>(null);
  const listedCourses = useTutorCourses(courses, courseId, setCourseId);
  const [openSessions, setOpenSessions] = useState<LoopOpenSession[] | null>(null); // null = loading
  const [openComplete, setOpenComplete] = useState(true); // K29: it lists every open session
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

  // Goals are session-owned. New sessions start whole-course unless the student
  // chose concepts: the goal editor, or a concept they clicked (K05: its node
  // id, never typed text matched to a concept); nothing is inherited across courses.
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
  const [startGoal, setStartGoal] = useState<LoopGoal | null>(null); // K30: the goal a start was refused on
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
  // W3.1: GET /plan prereq pairs — kept through approve for SessionPanel
  const [planPrereqEdges, setPlanPrereqEdges] = useState<LoopPlanPrereqEdge[]>([]);
  const [planBusy, setPlanBusy] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const [planGoalVersion, setPlanGoalVersion] = useState<number | undefined>(undefined);
  const [planJustApproved, setPlanJustApproved] = useState(false);
  // The approved plan as GET /status reports it: the session panel's list after a reload
  const [approvedPlan, setApprovedPlan] = useState<ApprovedPlan | null>(null);

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
  const [verdict, setVerdict] = useState<{ verdict: string; nodeId: string | null; credit?: LoopTurnResult["credit"]; reasons?: LoopTurnResult["credit_reasons"] } | null>(null);
  // W2.5: ms Continue / probe Next holds after high-confidence wrong (server-scaled)
  const [feedbackDwellMs, setFeedbackDwellMs] = useState<number | null>(null);
  const hypercorrectionHold = useHypercorrectionDwell(feedbackDwellMs);
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
  const [wrapUpAsk, setWrapUpAsk] = useWrapUpAsk(close);

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
  const lastStart = useRef<{ topic?: string; mode?: string; goal?: LoopGoal }>({}); // the start card's "Try again" repeats it
  const sessionRef = useRef<string | null>(null);
  // K26: re-enter the session on screen as the server now has it (set below,
  // once `resume` exists). One at a time.
  const resyncRef = useRef<(sid: string) => void>(() => {});
  const phaseRef = useRef<LoopPhase>("probe");
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
  useEffect(() => {
    phaseRef.current = state.phase;
  }, [state.phase]);

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
  }, [courseName, setWrapUpAsk]);

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
    const pause = loopPauseOf(err); // K11: the loop's tutor budget, or the daily AI limit
    if (pause) {
      dispatch({ type: "budget", level: "hard", resetAt: pause.resetAt, sessionCapped: pause.sessionCapped, pauseNovice: pause.pauseNovice, aiLimit: pause.aiLimit });
      return;
    }
    const { status, detail } = extractErrorDetail(err);
    const sid = sessionRef.current;
    const refusal = sessionRefusal(status, detail); // K26: closed (or gone), or moved
    if (refusal === "closed" && sid) {
      void enterClosed(sid);
      return;
    }
    if (refusal === "moved" && sid) {
      resyncRef.current(sid); // one in flight already re-reads it
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
    setPlanPrereqEdges([]);
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
    setPlanPrereqEdges([]);
    setPlanGoalVersion(undefined);
    try {
      const r = await getLoopPlan(sid, userId);
      if (g !== gen.current) return;
      applyLearningScope(r);
      setScopeReady(true);
      setScopeError(false);
      setPlanGoalVersion(r.goal_version);
      setPlan(r.concepts ?? []);
      setPlanPrereqEdges(r.prereq_edges ?? []);
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
  const resyncing = useRef(false);
  useEffect(() => {
    resyncRef.current = (sid: string) => {
      if (resyncing.current || sid !== sessionRef.current) return;
      resyncing.current = true;
      toast.info(MOVED_ELSEWHERE_COPY);
      const s = { session_id: sid, topic: "", started_at: "", phase: phaseRef.current };
      void resume(s).finally(() => { resyncing.current = false; });
    };
  }, [resume, toast]);

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
      if (sessionRefusal(status, detail) === "closed") {
        // already closed elsewhere, or gone (K26): nothing to wrap up
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
    if (r.initial_message) setMessages([asMsg("assistant", r.initial_message, groundedExtra(r))]);
    if (r.materials_unavailable) setMaterialsNote(true); // A128: the opener's retrieval failed
    if (r.budget?.level === "hard") {
      // A27: a capped student still gets the template opener and the probe
      dispatch({ type: "budget", level: "hard", resetAt: r.budget.reset_at, sessionCapped: r.budget.session_capped, pauseNovice: r.budget.pause_novice });
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
    { closeCurrent = false, topic, mode, goal }: { closeCurrent?: boolean; topic?: string; mode?: string; goal?: LoopGoal } = {},
  ) => {
    if (!courseId || !userId || sessionTransitionBusy) return;
    lastStart.current = { topic, mode, goal };
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
      // K05/K30: a session on chosen concepts starts on them (StartSessionBody.goal)
      const r = await startLoopSession(userId, courseId, title, mode, goal, fromNoteId);
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
      if (goal && extractErrorDetail(err).status === 422) {
        // K05/K30: a concept the course no longer has — choose again, never a retry that fails again
        setStartGoal(goal);
        setGoalError(humanizeError(err, "Confirm 1–12 concepts from this course."));
        setView("goal");
        return;
      }
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
    setOpenComplete(listed.complete);
    const found = wanted ? listed.resume : null;
    if (found) {
      if (found.course_id !== courseId && courses?.some((c) => c.course_id === found.course_id)) {
        // an open loop session in another of the student's courses: switch to it
        bootKey.current = `${userId}:${found.course_id}`;
        setCourseId(found.course_id);
        let others: LoopOpenSession[] = [];
        try {
          const other = await listLoopSessionsFor(userId, found.course_id, null);
          others = other.sessions;
          setOpenComplete(other.complete);
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
      // a "learn this" link from the map starts on its concept (its goal, K05), once
      topicStarted.current = true;
      await newSession({ topic: deepLink.topic, mode: deepLink.mode, goal: linkGoal(deepLink, courseId) });
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
      setCourseId((prev) => prev ?? list.find((c) => c.course_id === deepLink.course)?.course_id ?? null); // else useTutorCourses picks
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
  const sessionRows = useMemo(
    () => mergeSessions(lists.recent, openSessions, courseId, openComplete), [lists.recent, openSessions, courseId, openComplete],
  );
  // K31: rename and delete, from every session's list; a deleted session on
  // screen (or read-only) is let go of, so nothing of it stays behind the list
  const edits = useSessionEdits({
    userId, toast, renameRecent: lists.renameRecent, dropRecent: lists.dropRecent, setOpenSessions,
    onDeleted: useCallback((id: string) => {
      if (id !== sessionRef.current && id !== readOnly?.id) return;
      ++gen.current;
      clearSessionView();
      setSessionId(null);
      sessionRef.current = null;
    }, [readOnly, clearSessionView]),
  });

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
    else if (row.open) resumeUnlisted(row.id); // K29: past the open list's cap
    else void openReadOnly(row.id);
  };
  /** An open session the course's capped list left out: found by id, as a ?resume= link is. */
  const resumeUnlisted = (id: string) => {
    pendingResume.current = id;
    resumePending.current = true;
    void loadSessions();
  };
  /** T1's start: a new session (the open one on screen is wrapped up first),
   *  on the concepts of `goal` when one was chosen (K05, K30). */
  const startGuided = (opts: { topic?: string; goal?: LoopGoal } = {}) => {
    setView("session");
    return newSession({ closeCurrent: true, topic: opts.topic, mode: deepLink.mode, goal: opts.goal });
  };
  const retryStart = () => newSession(lastStart.current);
  /** K30: the home's "Set a goal" sets it before anything starts or is posed. */
  const showStartGoal = () => { setStartGoal(null); setGoalError(null); setView("goal"); };

  // ── Probe ──────────────────────────────────────────────────────────────
  /** After a graded answer: the probe's last answer already moved the session
   *  to `plan` (a /probe/next now would 409), otherwise the next item. */
  const advanceProbe = async (done: boolean, g: number) => {
    if (!sessionId || hypercorrectionHold) return;
    setProbeReference(null);
    setFeedbackDwellMs(null);
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
        setFeedbackDwellMs(r.feedback_dwell_ms && r.feedback_dwell_ms > 0 ? r.feedback_dwell_ms : null);
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
      setPlanPrereqEdges([]);
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
        setPlanPrereqEdges([]);
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
    if (text) setMessages((prev) => [...prev, asMsg("assistant", text, groundedExtra(res))]);
    // #761 (B4): a replay re-sends a reply the server already persisted —
    // {reply, graph_update, mastery_changes: [], replayed: true}, no phase,
    // check or learner state. Its turn's state changes already happened, so
    // an absent field here is not a "clear": nothing else is applied.
    if (res.replayed) return;
    if (res.approved_plan) setApprovedPlan(res.approved_plan); // K08: the server moved the plan's cursor
    if (submission && res.graded) {
      setVerdict(res.verdict ? { verdict: res.verdict, nodeId: res.learner_state?.[0]?.node_id ?? state.focusNodeId, credit: res.credit, reasons: res.credit_reasons } : null);
      setFeedbackDwellMs(res.feedback_dwell_ms && res.feedback_dwell_ms > 0 ? res.feedback_dwell_ms : null);
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
      dispatch({ type: "budget", level: "hard", resetAt: res.budget.reset_at, sessionCapped: res.budget.session_capped, pauseNovice: res.budget.pause_novice });
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
    const closed = sessionRefusal(status, detail) === "closed"; // reportError shows the close
    const checkClosed = checkClosedCopy(t.submission, status, detail);
    // ADR 0020: what streamed stays, marked interrupted; a chat message the tutor
    // never answered offers Retry (a pause gives it back through onPaused, a
    // close has nothing to retry), and after an error it is back in the composer.
    const retryText = t.hardSeen || loopPauseOf(err) || closed ? undefined : t.retryText;
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
    if (loopPauseOf(err)) t.onPaused?.(); // a pause: reportError shows the pause banner
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
        dispatch({ type: "budget", level: b.level, resetAt: b.reset_at, sessionCapped: b.session_capped, pauseNovice: b.pause_novice });
      },
    };
    try {
      // K10: a result is the saved turn — Stop pressed after `done`, while its
      // reply was still typing out, keeps it (the loop streams resolve with it)
      const res = await run(handlers);
      if (!ownsTurn()) return null;
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
  }, [invalidateHint, feedbackPending, applyServedTurn, failedTurn]);

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
        let waitS: number | undefined; // K32: time alone kept the draft from counting
        if (draft && countedAttempt.current !== `${qh}:${draft}`) {
          const recorded = await postLoopAttempt(sessionId, userId, qh, draft);
          if (!ownsHint()) return;
          if (interceptCrisis(recorded)) { setAttempt(EMPTY_DRAFT); return; } // no hint, nothing counted
          if (recorded.counted) countedAttempt.current = `${qh}:${draft}`;
          waitS = recorded.wait_s;
        }
        const r = await requestLoopHint(sessionId, userId, qh);
        if (!ownsHint()) return;
        if (r.denied) {
          setHint({ denied: hintDenial(r.denied, r.lifts, waitS) });
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
      setMessages((prev) => [...prev, asMsg("assistant", t.reply, groundedExtra(t))]);
      // spec §13 A139: a worked example or a shown solution asks "why" — a
      // served hint turn closes an older prompt and may open a new one
      setSelfExplainSaved(false);
      setSelfExplain(t.self_explain ?? null);
      // K33: a hint turn is a served turn too — the once-per-session materials note, the focus concept
      if (t.materials_unavailable) setMaterialsNote(true);
      hintTurnEvents(t).forEach(dispatch);
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
      if (r.approved_plan) setApprovedPlan(r.approved_plan); // K08: activation moved past a concept
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
        setPlanPrereqEdges([]);
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
      const failed = checkMeFailure(err);
      if (failed === "feedback") {
        dispatch({ type: "check", item: null });
        dispatch({ type: "phase", phase: "feedback" });
        setFeedbackPending(true);
        setCheckNote(FEEDBACK_PENDING_COPY);
        return;
      }
      if (failed) setCheckNote(failed.note); // #866 K35: this concept's check waits (the banner says why)
      reportError(err, "Couldn't get a check question.");
    } finally {
      if (g === gen.current) setCheckBusy(false);
    }
  };

  const doClose = async () => {
    if (!sessionId || closeBusy || pendingGrade || streamingText !== null) return;
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
    for (const c of [...(plan ?? []), ...(approvedPlan?.concepts ?? [])]) if (c.concept_name) names.set(c.node_id, c.concept_name);
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
  // K08: the concept the session is on — the plan cursor the server moves
  const currentNodeId = currentConcept(approvedPlan, focusNodeId);
  const mapNodeId = currentNodeId ?? focusNodeId;
  const learner = state.focusNodeId ? state.learnerState[state.focusNodeId] : undefined;
  // W3.2: practiced = measured learner_state keys (session covered outline).
  const practicedNodeIds = useMemo(
    () => new Set(Object.keys(state.learnerState)),
    [state.learnerState],
  );
  const treeHref = mapNodeId ? `/tree?node=${encodeURIComponent(mapNodeId)}` : "/tree";
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
    const history = withPlanHistory(messages, panelPlanOf(state.phase, plan, approvedPlan));
    const inCard = new Set<string>();
    if (item?.prompt) inCard.add(item.prompt);
    if (item && hint && "reply" in hint) inCard.add(hint.reply);
    // spec §13 A138: the guess's pose, while its card shows it
    if (prequestion?.text) inCard.add(prequestion.text);
    return inCard.size === 0
      ? history
      : history.map((m) => (m.role === "assistant" && inCard.has(m.content) ? { ...m, visuallyHidden: true } : m));
  }, [messages, state.phase, plan, approvedPlan, item, hint, prequestion]);

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
  const panelPlan = panelPlanOf(state.phase, plan, approvedPlan);
  /** The TopBar's line under the title: where the session is (no step pills). */
  const phaseLine = (): string => {
    if (readOnly) return "Wrapped up · read-only";
    if (!sessionId) return starting ? "Starting…" : "";
    return phaseText(state.phase, panelPlan, currentNodeId, conceptNames);
  };
  const topTitle = () => tutorTopTitle(view, course, readOnly, sessionRow, sessionId);
  const topSub = () => tutorTopSub(view, phaseLine);
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
          disabled={closeBusy || !!pendingGrade || streaming}
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
  // a render call, not a component: React sees the tree the inline JSX produced
  const renderNotices = () => (
    <LoopNotices
      paused={paused}
      studyVisible={studyVisible}
      quizVisible={quizVisible}
      courseId={courseId}
      noCheckItems={noCheckItems}
      preparing={noCheckItems === "preparing" && !crisisOnScreen}
      materialsNote={materialsNote && !crisisOnScreen}
      practiceUnavailable={practiceUnavailable}
      names={conceptNames}
      exhaustedPracticeAttempt={exhaustedPracticeAttempt}
      libraryVisible={libraryVisible}
      canRefreshPractice={state.phase === "plan" || (teaching && !item && !feedbackPending)}
      refreshDisabled={sessionTransitionBusy || streaming || checkBusy}
      onRefreshPractice={() => {
        if (!sessionId) return;
        if (state.phase === "plan") void loadPlan(sessionId, gen.current);
        else void checkMe();
      }}
      topicOffer={topicOffer}
      topicStartDisabled={sessionTransitionBusy}
      onTopicStart={() => void newSession({ closeCurrent: true, topic: topicOffer ?? undefined, mode: deepLink.mode, goal: linkGoal(deepLink, courseId) })}
    />
  );
  const notices = renderNotices();

  const learnerChip = <LearnerChip learner={learner} names={conceptNames} />;

  /** Between checks: Continue (after feedback), Check me, the plan's first
   *  concept, and the check's status line. A render call, not a component. */
  const renderTeachActions = (firstConcept: LoopPlanConcept | undefined) => (
    <TeachActions
      feedback={state.phase === "feedback"}
      feedbackPending={feedbackPending}
      hold={hypercorrectionHold}
      continueDisabled={anyOf(!!paused, streaming, starting, scopeLoading, hypercorrectionHold)}
      checkMeDisabled={anyOf(checkBusy, streaming, feedbackPending, starting, scopeLoading, hypercorrectionHold)}
      pendingNote={allOf(feedbackPending, !streaming, !checkNote)}
      teachStart={allOf(messages.length <= 1 || planJustApproved, state.phase === "teach", !paused) ? firstConcept : undefined}
      streaming={streaming}
      checkNote={checkNote}
      checkNoteReported={checkNote === REPORTED_COPY}
      continueRef={continueRef}
      checkMeRef={checkMeRef}
      teachStartRef={teachStartRef}
      onContinue={() => {
        setFeedbackDwellMs(null);
        send(CONTINUE_MESSAGE);
      }}
      onCheckMe={() => void checkMe()}
      onTeachStart={(concept) => send(`Teach me about ${concept.concept_name}.`)}
    />
  );

  const renderChatHeader = (firstConcept: LoopPlanConcept | undefined) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {askRating && askRating === sessionId && <RatingPrompt onRate={rate} />}
      {item ? (
        <CheckCard
          item={item}
          conceptName={conceptAt(conceptNames, currentNodeId, null)}
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
            <VerdictBanner verdict={verdict.verdict} credit={verdict.credit} reasons={verdict.reasons} concept={conceptAt(conceptNames, verdict.nodeId, approvedPlan)}
              next={nextAfterVerdict(approvedPlan, verdict.nodeId, conceptNames)} />
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
                ? paused.aiLimit ? "AI features are paused until today's limit resets." : "Tutor chat is paused — check answers still count."
                : "Ask your AI tutor anything…"
          }
          attachHref={libraryVisible ? "/library" : undefined}
          // Z08: code serves class material verbatim here (a check pose, an H2
          // passage, a worked sibling, a reference): drawn inert, never a live link
          turnStyle="page" markdown="inert"
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
      return <ReadOnlyTranscript topic={readOnly.topic} messages={readOnly.messages} startDisabled={sessionTransitionBusy}
        onStart={() => void newSession({ closeCurrent: true, mode: deepLink.mode })} />;
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
          nextHeld={hypercorrectionHold}
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
          prereqEdges={planPrereqEdges}
          busy={planBusy}
          loadFailed={loadError === "plan"}
          onApprove={() => void approvePlan()}
          onRetry={() => { if (sessionId) void loadPlan(sessionId, gen.current); }}
        />
      );
    } else if (state.phase === "close") {
      return <ClosePanel close={close} note={closeNote} names={conceptNames} courseId={courseId} onNew={showHome}
        visibility={handoffVisibility} rating={wrapUpAsk?.sessionId === sessionId ? wrapUpAsk : null} />;
    }
    return renderTeach();
  };
  const body = renderBody();

  /** Skill per concept in today's plan (else the concept being taught): the
   *  loop's own estimate when it has one, else the map's mastery. */
  const panelSkills = (): PanelConcept[] => {
    const ids = panelPlan && panelPlan.length > 0 ? panelPlan.map((c) => c.node_id) : mapNodeId ? [mapNodeId] : [];
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
      prereqEdges={planPrereqEdges}
      names={conceptNames}
      currentNodeId={teaching ? currentNodeId : null}
      skills={panelSkills()}
      dueCount={lists.dueReviews}
      dueHref={dueHref}
      learnerChip={learnerChip}
      hasLearner={!!learner}
      treeHref={treeHref}
      showTreeLink={allOf(!isMobile, treeVisible)}
      onHide={layout.hidePanel}
      map={railGraph.nodes.length > 0 ? (
        <SessionMap
          nodes={railGraph.nodes}
          edges={railGraph.edges}
          highlightId={mapNodeId ?? undefined}
          practicedNodeIds={practicedNodeIds}
        />
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
          onStartWith={(c) => void startGuided({ topic: c.name, goal: conceptGoal(c.id) })}
          onGoal={showStartGoal}
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
        onRename={(row, topic) => void edits.rename(row, topic)}
        onDelete={(row) => void edits.remove(row)}
      />
    </div>
  );
  const renderSession = () => {
    const live = allOf(!!sessionId, !readOnly);
    return (
      <>
        {/* the conversation column's first row (design T4-T10, anatomy D) */}
        {live && <PhaseStepper phase={state.phase} />}
        {live && state.phase !== "close" && (
          <ScopeSummary error={scopeError} ready={scopeReady} goal={goal} names={conceptNames} onRetry={() => void retryLearningScope()} />
        )}
        {goalProgress && goal && <GoalProgressNote progress={goalProgress} names={conceptNames} />}
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
  /** K30: the home's goal editor — saving starts the session on that goal. */
  const renderStartGoal = () => (
    <GoalEditor key={`start:${courseId}`} goal={startGoal} nodes={railGraph.nodes.filter((node) => !node.is_subject_root)}
      busy={starting} error={goalError} loadingNodes={graphLoading} nodesError={graphError} onRetryNodes={() => void refreshGraph()}
      onSave={(next) => void startGuided({ goal: next ?? undefined })} onCancel={showHome} />
  );
  /** The main column's page: T1 home, T2 course, T3 all sessions, else the session. */
  const renderPage = (): React.ReactNode => {
    const pageable = !sessionsError && !noCourses;
    if (view === "home" && pageable) return renderHome();
    if (view === "goal" && pageable) return renderStartGoal();
    if (view === "course" && course) return renderCourse(course);
    if (view === "all") return renderAll();
    return renderSession();
  };

  const renderSidebar = () => (
    <TutorSidebar
      courses={listedCourses}
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

// ── Pieces ─────────────────────────────────────────────────────────────────
