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
import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { FullHeightScreen } from "../FullHeightScreen";
import { DisclaimerModal } from "../DisclaimerModal";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { ChatPanel, type ChatMsg, type InterruptedReason } from "../chat/ChatPanel";
import { interruptedTurnLanded, removeInterruptedTurn } from "../chat/interruptedTurn";
import { CustomSelect } from "../CustomSelect";
import { KnowledgeGraph } from "../graph/KnowledgeGraph";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { useFlag, useFlagMap } from "@/context/FlagsContext";
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
  requestLoopHint,
  requestLoopHintTurn,
  resumeSession,
  setLoopGoal,
  startLoopSession,
  streamLoopChat,
  streamLoopCheckAnswer,
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
  type LoopPhase,
  type LoopPlanConcept,
  type LoopProbeItem,
  type LoopRating,
  type LoopSessionStatus,
  type LoopTurnResult,
  type StreamChatHandlers,
} from "@/lib/api";
import { BudgetPausedBanner, tutorPauseMessage } from "./BudgetPausedBanner";
import { initialLoopState, reduceLoopEvent } from "./loopState";
import { readResumeParam } from "./resumeParam";
import styles from "./LoopLearn.module.css";
import { DiagnosisSummary, GoalEditor, skillEvidenceLabel } from "./LearningScope";
import { NewSessionConfirm } from "./NewSessionConfirm";
import {
  CONTEXT_TITLES,
  CONVERSATION_SEEDS,
  ContextChips,
  GoalPlanContext,
  MapContext,
  MaterialsContext,
  TutorBar,
  TutorHistory,
  TutorMenu,
  TutorWelcome,
  type TutorContextTab,
} from "./TutorView";
import {
  BotanicalIcon,
  ChoiceGroup,
  ContextPanel,
  ContextSheet,
  GoalSummary,
  PageHeading,
  PhaseStrip,
  SaplingAction,
  StatusMessage,
} from "@/components/sapling";

// ── Copy ─────────────────────────────────────────────────────────────────
const NO_CHECK_ITEMS_COPY =
  "No check items for this course yet. You can still learn with the tutor; nothing is graded until the course has items.";
const PLAN_DONE_COPY = "That's every concept in today's plan — close the session when you're ready.";
const NO_ITEM_COPY = "No check is ready for this concept yet — keep going with the tutor.";
const PROBE_UNAVAILABLE_COPY = "Couldn't grade that one — here's another.";
const PROBE_REFUSED_COPY = "Answer in your own words — that read as instructions to the grader.";
const CLOSED_ELSEWHERE_COPY = "This session was closed — start a new one to keep learning.";
const CONTINUE_MESSAGE = "Let's continue.";
/** A submission whose feedback stream did not settle: the grade may already be
 *  written, so the answer is never sent again on its own (status-first). */
const FEEDBACK_INTERRUPTED_COPY =
  "The feedback was interrupted. Your answer may already be graded, so it wasn't sent again — here's where your session stands.";
const ALREADY_GRADED_COPY = "That answer was already graded. Here's where your session stands.";
const RETRY_LANDED_COPY = "Clov's reply had already been saved, so nothing was sent again. It's shown above.";
const isOffline = () => typeof navigator !== "undefined" && navigator.onLine === false;

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
/** setTimeout's ceiling (2^31 − 1 ms): a later reset time is never armed early. */
const MAX_TIMER_MS = 2_147_483_647;

const BAND_LABEL: Record<string, string> = { novice: "Getting started", develop: "Developing", profic: "Proficient" };
const KIND_LABEL: Record<string, { label: string }> = {
  review: { label: "Review" },
  new: { label: "New" },
  sibling: { label: "Related" },
};
/** Why the server put a concept in the plan (planner `reason`). */
const REASON_LABEL: Record<string, string> = {
  prerequisite: "Prerequisite for your goal",
  goal: "Your selected goal",
  review: "Due for review",
  related: "Related practice",
};
/** The phase strip (components/sapling LOOP_STAGES) groups the server phases:
 *  Check-in = probe, Plan = plan, Learn = teach/check/feedback, Wrap-up = close. */
const TEACHING: readonly LoopPhase[] = ["teach", "check", "feedback"];
/** Below this width the learning-route rail becomes a labelled sheet. */
const RAIL_BREAKPOINT = 1024;
/** The Clov tutor view of this same controller (prompt 04): `?view=tutor`,
 *  shown only while this flag is on (services/feature_flags.py REGISTRY). */
const TUTOR_VIEW_FLAG = "tutor_view";
type LoopView = "learn" | "tutor";
const viewHref = (base: string, view: LoopView) => (view === "tutor" ? `${base}?view=tutor` : base);
const RAIL_GRAPH_HEIGHT = 240;
const TUTOR_GRAPH_HEIGHT = 300;

let msgSeq = 0;
const msgId = (prefix: string) => `${prefix}-${Date.now()}-${++msgSeq}`;
const asMsg = (role: "user" | "assistant", content: string): ChatMsg => ({ id: msgId(role), role, content });
const toChat = (rows: { id: string; role: string; content: string }[] | undefined): ChatMsg[] =>
  (rows ?? [])
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({ id: m.id, role: m.role as "user" | "assistant", content: m.content }));
const shortDate = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

type Draft = { answer: string; option: string; reason: string };
const EMPTY_DRAFT: Draft = { answer: "", option: "", reason: "" };
type HintView = { denied: string } | { reply: string } | null;

/** The Learn deep links (Dashboard, Tree, notetaker, quiz): read ONCE at mount,
 *  so a consumed `?resume=` never re-applies on a session or course switch. */
type DeepLink = { resume: string | null; topic: string; course: string; mode: string; suggest: string };
const readDeepLink = (p: { get(name: string): string | null }): DeepLink => ({
  resume: readResumeParam(p),
  topic: (p.get("topic") ?? "").trim(),
  course: (p.get("course") ?? "").trim(),
  mode: (p.get("mode") ?? "").trim(),
  suggest: (p.get("suggest") ?? "").trim(),
});
const hasDeepLink = (d: DeepLink) => !!(d.resume || d.topic || d.course || d.mode || d.suggest);

/** The phase GET /status reports for a document, in the UI's vocabulary. */
const statusPhase = (st: LoopSessionStatus) => (st.loop_phase === "teach" ? st.phase : st.loop_phase);

export function LoopLearn() {
  const { userId } = useUser();
  const toast = useToast();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const compact = useIsMobile(RAIL_BREAKPOINT);
  // A phone keeps the learning flow first: the open-sessions strip moves below
  // the workspace (in DOM order too, so focus order matches what is seen).
  const phone = useIsMobile();
  const [state, dispatch] = useReducer(reduceLoopEvent, undefined, initialLoopState);
  const [deepLink] = useState(() => readDeepLink(searchParams));
  // One controller, two views (prompt 04): the Learning Studio and the Clov
  // tutor render this same session/goal/plan/phase. The view is presentation
  // only — switching it never touches the session. `?view=tutor` asks for the
  // tutor; the tutor_view flag decides whether it is offered at all.
  const tutorOffered = useFlag(TUTOR_VIEW_FLAG) === "on";
  const { ready: flagsReady } = useFlagMap();
  const [viewParam, setViewParam] = useState<LoopView>(() => (searchParams.get("view") === "tutor" ? "tutor" : "learn"));
  const view: LoopView = tutorOffered && viewParam === "tutor" ? "tutor" : "learn";
  // The tutor's discovery shows a welcome instead of auto-starting a check-in;
  // wait for the flag answer before discovery when the tutor was asked for.
  const bootReady = viewParam !== "tutor" || flagsReady;
  const [welcome, setWelcome] = useState(false);
  const [contextTab, setContextTab] = useState<TutorContextTab | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

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

  // Goals are session-owned. New sessions start whole-course; typed topic text
  // never silently selects targets, and nothing is inherited across courses.
  const [goal, setGoal] = useState<LoopGoal | null>(null);
  const [goalProgress, setGoalProgress] = useState<LoopGoalProgress | null>(null);
  const [diagnosis, setDiagnosis] = useState<LoopDiagnosis | null>(null);
  const [scopeReady, setScopeReady] = useState(false);
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
  const [noCheckItems, setNoCheckItems] = useState(false);

  // Plan
  const [plan, setPlan] = useState<LoopPlanConcept[] | null>(null);
  const [planBusy, setPlanBusy] = useState(false);
  const [planGoalVersion, setPlanGoalVersion] = useState<number | undefined>(undefined);
  const [planJustApproved, setPlanJustApproved] = useState(false);

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
  // PKG-14: the session a graded check asked to rate (done.ask_rating); one click hides it
  const [askRating, setAskRating] = useState<string | null>(null);
  // Retry of an interrupted conversational turn (prompt 04): one at a time,
  // and a status-first note when a graded submission's feedback broke off.
  const [retryBusy, setRetryBusy] = useState(false);
  const [recoveryNote, setRecoveryNote] = useState<string | null>(null);
  const messagesRef = useRef<ChatMsg[]>([]);

  // Close
  const [close, setClose] = useState<LoopCloseResponse | null>(null);
  const [closeBusy, setCloseBusy] = useState(false);
  const [closeNote, setCloseNote] = useState<string | null>(null);
  // New-session confirmation: leaving an open session is never one click.
  const [confirmNew, setConfirmNew] = useState<{ topic?: string; mode?: string } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  // Phone/tablet: the learning-route context lives in a labelled sheet.
  const [routeOpen, setRouteOpen] = useState(false);

  // Knowledge map
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState(false);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({ nodes: [], edges: [] });

  // A session "generation": bumped whenever the screen switches session, so a
  // response for the previous one is dropped instead of landing on the new one.
  const gen = useRef(0);
  const bootKey = useRef<string | null>(null);
  const resumePending = useRef(true); // the deep link's ?resume= is honoured once
  const sessionRef = useRef<string | null>(null);
  const streamAbort = useRef<AbortController | null>(null);
  const countedAttempt = useRef<string | null>(null); // `${qh}:${text}` the server counted
  const hintEpoch = useRef(0);
  const earnedHint = useRef<{ sessionId: string; questionHash: string; rung: number } | null>(null);
  const mounted = useRef(true);
  const graphRequest = useRef(0);
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
    messagesRef.current = messages;
  }, [messages]);

  // The deep link is consumed at mount: drop it from the URL so a reload, or a
  // later session/course switch, never re-applies it (it was sticky).
  const urlCleaned = useRef(false);
  useEffect(() => {
    if (urlCleaned.current || !hasDeepLink(deepLink)) return;
    urlCleaned.current = true;
    // the view is not a deep link: it stays in the URL
    router.replace(viewHref(pathname || "/learn", viewParam), { scroll: false });
  }, [deepLink, router, pathname, viewParam]);
  const switchView = (next: LoopView) => {
    setViewParam(next);
    setContextTab(null);
    setHistoryOpen(false);
    router.replace(viewHref(pathname || "/learn", next), { scroll: false });
  };

  const course = useMemo(() => courses?.find((c) => c.course_id === courseId) ?? null, [courses, courseId]);
  const applyLearningScope = useCallback((payload: LoopLearningScope | null | undefined) => {
    if (!payload) return;
    if (payload.goal !== undefined) setGoal(payload.goal);
    if (payload.diagnosis !== undefined) setDiagnosis(payload.diagnosis);
    if (payload.goal_progress !== undefined) setGoalProgress(payload.goal_progress);
  }, []);
  const paused = state.budgetPause;
  const item = state.item;

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
    setCloseBusy(false);
    dispatch({ type: "check", item: null });
    dispatch({ type: "phase", phase: "close" });
    dropFromPicker(sid);
    try {
      const r = await closeLoopSession(sid, userId);
      if (g === gen.current) setClose(r);
    } catch {
      if (g === gen.current) setCloseNote(CLOSED_ELSEWHERE_COPY);
    }
  }, [userId, dropFromPicker, invalidateHint]);

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
    if (st.loop_phase === "close") {
      void enterClosed(sid);
      return;
    }
    dispatch({ type: "check", item: st.check ?? null });
    dispatch({ type: "phase", phase: statusPhase(st) });
  }, [enterClosed, applyLearningScope, invalidateHint]);

  /** After a submission that did not settle (a 409, a stream error, Stop): the
   *  server may already have graded it, so re-read where the session stands.
   *  Read-only. If even that fails, the item is cleared (fail closed): "Check
   *  me" re-poses it while it is still open (/check/next is idempotent then). */
  const reconcile = useCallback(async (sid: string, g: number) => {
    try {
      const st = await getLoopSessionStatus(sid, userId);
      if (g === gen.current) applyStatus(sid, st);
    } catch {
      if (g === gen.current) dispatch({ type: "check", item: null });
    }
  }, [userId, applyStatus]);

  // ── Session lifecycle ──────────────────────────────────────────────────
  const clearSessionView = useCallback(() => {
    invalidateHint();
    streamAbort.current?.abort();
    streamAbort.current = null;
    dispatch({ type: "reset" });
    setReadOnly(null);
    setGoal(null);
    setGoalProgress(null);
    setDiagnosis(null);
    setScopeReady(false);
    setScopeError(false);
    setGoalEditor(false);
    setGoalBusy(false);
    setGoalError(null);
    setStarting(false);
    setLoadError(null);
    setProbeItem(null);
    setProbeDraft(EMPTY_DRAFT);
    setProbeReference(null);
    setProbeNote(null);
    setProbeCount(0);
    setProbeBusy(false);
    setProbeFinished(false);
    setNoCheckItems(false);
    setPlan(null);
    setPlanJustApproved(false);
    setPlanGoalVersion(undefined);
    setPlanBusy(false);
    setMessages([]);
    setStreamingText(null);
    setAttempt(EMPTY_DRAFT);
    setAttemptBusy(false);
    setHint(null);
    setHintBusy(false);
    setCheckNote(null);
    setCheckBusy(false);
    setAskRating(null);
    setRetryBusy(false);
    setRecoveryNote(null);
    setClose(null);
    setCloseBusy(false);
    setCloseNote(null);
    // A pending new-session confirmation belonged to the session being left.
    setConfirmNew(null);
    setConfirmBusy(false);
    setConfirmError(null);
    setWelcome(false);
    countedAttempt.current = null;
  }, [invalidateHint]);

  const loadPlan = useCallback(async (sid: string, g: number) => {
    setLoadError(null);
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
    }
  }, [userId, reportError, applyLearningScope]);

  const nextProbe = useCallback(async (sid: string, g: number) => {
    setProbeBusy(true);
    setLoadError(null);
    try {
      const r = await nextLoopProbe(sid, userId);
      if (g !== gen.current) return;
      applyLearningScope(r);
      setProbeReference(null);
      if (r.done) {
        setProbeItem(null);
        if (r.no_check_items) setNoCheckItems(true);
        dispatch({ type: "phase", phase: r.phase });
        if (r.phase === "plan") await loadPlan(sid, g);
      } else {
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
    }
  }, [userId, applyStatus]);

  const resume = useCallback(async (s: LoopOpenSession) => {
    const g = ++gen.current;
    clearSessionView();
    setSessionId(s.session_id);
    sessionRef.current = s.session_id;
    dispatch({ type: "phase", phase: s.phase });
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
    if (phase === "probe") await nextProbe(s.session_id, g);
    else if (phase === "plan") await loadPlan(s.session_id, g);
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

  /** Wrap up the open session being left (A60's close) before a new one
   *  starts, so sessions do not pile up open. Only ever runs from the
   *  new-session confirmation. A close that cannot run now (409) or fails
   *  starts nothing: the reason comes back for the dialog to show. */
  const wrapUpCurrent = useCallback(async (): Promise<{ ok: true } | { ok: false; reason: string | null }> => {
    const leaving = sessionRef.current;
    if (!leaving || !isOpenPhase(state.phase)) return { ok: true };
    const g0 = gen.current;
    setStarting(true);
    try {
      await closeLoopSession(leaving, userId);
    } catch (err) {
      if (g0 !== gen.current) return { ok: false, reason: null };
      setStarting(false);
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail === SESSION_CLOSED_DETAIL) {
        // already closed elsewhere: nothing to wrap up
      } else if (status === 409 && detail) {
        return { ok: false, reason: CLOSE_RETRY_COPY[detail] ?? detail };
      } else {
        const pause = budgetPauseOf(err);
        return {
          ok: false,
          reason: pause
            ? "Wrap-up is paused for now. Your current session is still open."
            : humanizeError(err, "Couldn't wrap up the current session."),
        };
      }
    }
    dropFromPicker(leaving);
    if (g0 !== gen.current) return { ok: false, reason: null };
    return { ok: true };
  }, [state.phase, userId, dropFromPicker]);

  /** Start a session and its probe. Never closes anything itself: leaving an
   *  open session goes through the confirmation (`requestNewSession`). */
  const newSession = useCallback(async (
    { topic, mode }: { topic?: string; mode?: string } = {},
  ) => {
    if (!courseId || !userId) return;
    // An explicit start wins over a boot that has not listed the sessions yet.
    bootKey.current = `${userId}:${courseId}`;
    const g = ++gen.current;
    clearSessionView();
    setSessionId(null);
    sessionRef.current = null;
    setStarting(true);
    try {
      const r = await startLoopSession(userId, courseId, topic || course?.course_name || "", mode);
      if (g !== gen.current) return;
      setSessionId(r.session_id);
      sessionRef.current = r.session_id;
      applyLearningScope(r);
      setScopeReady(true);
      if (r.initial_message) setMessages([asMsg("assistant", r.initial_message)]);
      if (r.budget?.level === "hard") {
        // A27: a capped student still gets the template opener and the probe
        dispatch({ type: "budget", level: "hard", resetAt: r.budget.reset_at, sessionCapped: r.budget.session_capped });
      }
      setStarting(false);
      await nextProbe(r.session_id, g);
      if (g !== gen.current) return;
      // the first /probe/next materialised the session row: list it
      setOpenSessions((prev) => {
        const list = prev ?? [];
        if (list.some((x) => x.session_id === r.session_id)) return list;
        const row: LoopOpenSession = {
          session_id: r.session_id,
          topic: topic || course?.course_name || "",
          started_at: new Date().toISOString(),
          phase: "probe",
        };
        return [row, ...list];
      });
    } catch (err) {
      if (g !== gen.current) return;
      setLoadError("start"); // never an empty probe: the start card offers a retry
      reportError(err, "Couldn't start a session.");
    } finally {
      if (g === gen.current) setStarting(false);
    }
  }, [courseId, userId, course, clearSessionView, nextProbe, reportError, applyLearningScope]);

  const loadSessions = useCallback(async () => {
    if (!courseId || !userId) return;
    const g = ++gen.current;
    const wanted = resumePending.current ? deepLink.resume : null;
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
    } else if (view === "tutor" && !deepLink.topic && !deepLink.mode) {
      // The tutor's start (s3Kxuz): discovery succeeded and nothing is open,
      // so the student chooses — nothing starts until they do.
      setWelcome(true);
    } else {
      await newSession({ topic: deepLink.topic, mode: deepLink.mode });
    }
  }, [courseId, userId, courses, deepLink, openReadOnly, resume, newSession, view]);

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
    if (!userId || !courseId || !courses || !bootReady) return;
    const key = `${userId}:${courseId}`;
    if (bootKey.current === key) return; // StrictMode re-runs must not start twice
    bootKey.current = key;
    void loadSessions();
  }, [userId, courseId, courses, loadSessions, bootReady]);

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

  const submitProbe = async (idk: boolean) => {
    if (!sessionId || !probeItem || probeBusy) return;
    const g = gen.current;
    const a: LoopCheckAnswer = idk
      ? { idk: true }
      : probeItem.format === "mc_reason"
        ? { option: probeDraft.option, reason: probeDraft.reason, idk: false }
        : { answer: probeDraft.answer, idk: false };
    setProbeBusy(true);
    setProbeNote(null);
    try {
      const r = await answerLoopProbe(sessionId, userId, probeItem.question_hash, a);
      if (g !== gen.current) return;
      applyLearningScope(r);
      if (r.graded) {
        void refreshGraph();
        setProbeCount((n) => n + 1);
        if (r.probe_done) setProbeFinished(true);
        if (r.reference_answer) {
          setProbeReference(r.reference_answer); // shown until "Next" (spec §3.3 corrective feedback)
          return;
        }
        await advanceProbe(r.probe_done, g);
        return;
      }
      if (r.refused) {
        setProbeNote(PROBE_REFUSED_COPY); // the item stays posed (A33)
        return;
      }
      setProbeNote(PROBE_UNAVAILABLE_COPY); // counted as not asked; another item follows
      await nextProbe(sessionId, g);
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't send that answer.");
    } finally {
      if (g === gen.current) setProbeBusy(false);
    }
  };

  const saveGoal = async (requested: LoopGoal | null) => {
    if (!sessionId || !courseId || goalBusy || !scopeReady) return;
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
      applyLearningScope(response);
      setGoalProgress(response.goal_progress ?? null);
      setScopeReady(true);
      setGoalEditor(false);
      setProbeItem(null);
      setProbeDraft(EMPTY_DRAFT);
      setProbeReference(null);
      setProbeCount(0);
      setProbeFinished(false);
      setNoCheckItems(false);
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

  // ── Plan ───────────────────────────────────────────────────────────────
  const approvePlan = async () => {
    if (!sessionId || !plan || plan.length === 0 || planBusy) return;
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
        setGoalProgress((current) => current?.status === "continue_available" ? null : current);
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

  const runTurn = useCallback(async (
    run: (h: StreamChatHandlers) => Promise<LoopTurnResult>,
    { submission = false, retryText }: {
      submission?: boolean;
      /** A conversational turn's own text: an interrupted turn offers Retry with it. */
      retryText?: string;
    } = {},
  ): Promise<LoopTurnResult | null> => {
    // A hint may still be in flight when the learner submits or continues.
    // Its previous phase/question must never overwrite the newer turn.
    invalidateHint();
    streamAbort.current?.abort();
    const controller = new AbortController();
    streamAbort.current = controller;
    const g = gen.current;
    const sid = sessionRef.current;
    let streamed = "";
    let hardSeen = false;
    setRecoveryNote(null);
    /** Keep what arrived, marked interrupted. A conversational turn carries its
     *  text and owning session so Retry can re-send it there and nowhere else;
     *  a submission never does (its grade may already be written). */
    const interrupt = (reason: InterruptedReason) => {
      const conversational = !submission && retryText !== undefined && !!sid;
      if (!conversational && !streamed) return;
      const partial = streamed;
      setMessages((prev) => [...prev, {
        ...asMsg("assistant", partial),
        interrupted: true,
        interruptedReason: reason,
        ...(conversational ? { retryText, turnOwner: sid ?? undefined } : {}),
      }]);
    };
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
      onPhase: (p) => { if (acceptsEvents()) dispatch({ type: "phase", phase: p }); },
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
        interrupt("stopped");
        if (submission && sid) {
          setRecoveryNote(FEEDBACK_INTERRUPTED_COPY);
          void reconcile(sid, g);
        }
        return null;
      }
      // done.reply is always the final, leak-stripped text (A46) — never the tokens
      const text = res.reply ?? streamed;
      if (text) setMessages((prev) => [...prev, asMsg("assistant", text)]);
      if (submission && res.graded) {
        // graded — correct, not yet, idk, or a refusal the server graded as idk:
        // the item takes no more answers
        dispatch({ type: "check", item: null });
        setAttempt(EMPTY_DRAFT);
        setHint(null);
      }
      if (submission && res.ask_rating && sid) setAskRating(sid);
      if (res.phase) dispatch({ type: "phase", phase: res.phase });
      for (const learnerState of res.learner_state ?? []) {
        dispatch({ type: "learner_state", state: learnerState });
      }
      applyActivated(res.check);
      if (res.budget?.level === "hard") {
        dispatch({ type: "budget", level: "hard", resetAt: res.budget.reset_at, sessionCapped: res.budget.session_capped });
      } else if (!hardSeen) {
        dispatch({ type: "budget_clear" }); // a tutor turn got through
      }
      return res;
    } catch (err) {
      if (!ownsTurn()) return null;
      const { status, detail } = extractErrorDetail(err);
      const closed = status === 409 && detail === SESSION_CLOSED_DETAIL; // reportError shows the close
      const alreadyGraded = submission && status === 409 && detail === ALREADY_GRADED_DETAIL;
      const offline = isOffline();
      if (!closed && !alreadyGraded) {
        interrupt(
          controller.signal.aborted ? "stopped" : hardSeen || budgetPauseOf(err) ? "paused" : offline ? "offline" : "failed",
        );
      }
      // The grade lands BEFORE the feedback stream starts: a submission that did
      // not settle (409 already graded, a mid-stream error, Stop) re-reads the
      // session so the answer box never sticks on a graded item — and the
      // answer is never sent again on its own.
      if (submission && sid && !closed) {
        setRecoveryNote(alreadyGraded ? ALREADY_GRADED_COPY : FEEDBACK_INTERRUPTED_COPY);
        void reconcile(sid, g);
      }
      if (controller.signal.aborted) return null;
      // At the hard level the stream ends with no `done`: that is the pause, not an error.
      if (hardSeen) return null;
      if (alreadyGraded) return null;
      // A conversational turn explains itself inline (the interrupted turn and
      // its Retry); only a pause or a closed session still routes elsewhere.
      if (!submission && retryText !== undefined && !closed && !budgetPauseOf(err)) return null;
      reportError(err, offline
        ? "You're offline, so nothing reached the tutor. Retry once you're back online."
        : "The tutor couldn't answer. Try again.");
      return null;
    } finally {
      if (streamAbort.current === controller) {
        streamAbort.current = null;
        setStreamingText(null);
      }
    }
  }, [applyActivated, reportError, reconcile, invalidateHint]);

  const send = (text: string) => {
    if (!sessionId || paused) return;
    setPlanJustApproved(false);
    setMessages((prev) => [...prev, asMsg("user", text)]);
    void runTurn((h) => streamLoopChat(sessionId, userId, text, h), { retryText: text });
  };

  const stop = () => streamAbort.current?.abort();

  /** Retry ONE interrupted conversational turn (prompt 04). Only the latest
   *  turn, in the session that owns it, while nothing else runs. The loop saves
   *  a turn's user row and reply together on completion, so an interrupted turn
   *  normally left nothing — but a Stop or a dropped connection can race the
   *  server finishing it. The stored transcript is read first: if the turn
   *  landed, the screen takes the stored rows and the server status, and
   *  nothing is sent again. Otherwise the pair is replaced by one re-send
   *  through the same stream client. A failed read sends nothing. */
  const retryTurn = async (m: ChatMsg) => {
    const sid = sessionRef.current;
    const text = m.retryText;
    if (!text || !sid || m.turnOwner !== sid || retryBusy || streamAbort.current || paused) return;
    if (!TEACHING.includes(state.phase) || messagesRef.current.at(-1)?.id !== m.id) return;
    const g = gen.current;
    setRetryBusy(true);
    setRecoveryNote(null);
    let landed: ChatMsg[] | null = null;
    try {
      const stored = await resumeSession(sid);
      if (g !== gen.current || sessionRef.current !== sid) return;
      const rows = toChat(stored.messages);
      if (interruptedTurnLanded(rows, messagesRef.current, m.id, text)) landed = rows;
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't check this conversation, so nothing was sent again. Try Retry in a moment.");
      return;
    } finally {
      if (g === gen.current) setRetryBusy(false);
    }
    if (landed) {
      setMessages(landed);
      setRecoveryNote(RETRY_LANDED_COPY);
      await reconcile(sid, g); // the landed turn may have moved the phase or posed a check
      return;
    }
    setMessages((prev) => [...removeInterruptedTurn(prev, m.id, text), asMsg("user", text)]);
    void runTurn((h) => streamLoopChat(sid, userId, text, h), { retryText: text });
  };

  const rate = (rating: LoopRating) => {
    const sid = askRating;
    setAskRating(null); // one click answers it
    if (sid) {
      submitLoopRating(sid, rating).catch((err) => reportError(err, "Couldn't save your rating."));
    }
  };

  const submitAttempt = async (idk: boolean) => {
    if (!sessionId || !item || attemptBusy) return;
    const g = gen.current;
    const a: LoopCheckAnswer = idk
      ? { idk: true }
      : item.format === "mc_reason"
        ? { option: attempt.option, reason: attempt.reason, idk: false }
        : { answer: attempt.answer, idk: false };
    const shown = idk
      ? "I don't know."
      : item.format === "mc_reason"
        ? `${attempt.option}${attempt.reason.trim() ? ` — ${attempt.reason.trim()}` : ""}`
        : attempt.answer;
    setMessages((prev) => [...prev, asMsg("user", shown)]);
    setAttemptBusy(true);
    const res = await runTurn(
      (h) => streamLoopCheckAnswer(sessionId, userId, item.question_hash, a, h),
      { submission: true },
    );
    if (g === gen.current) setAttemptBusy(false);
    if (res?.graded) void refreshGraph();
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

  const checkMe = async () => {
    if (!sessionId || checkBusy) return;
    const g = gen.current;
    setCheckBusy(true);
    setCheckNote(null);
    try {
      const r = await nextLoopCheck(sessionId, userId);
      if (g !== gen.current) return;
      applyLearningScope(r);
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
      if (r.check) applyActivated(r.check);
      else setCheckNote(r.plan_done ? PLAN_DONE_COPY : NO_ITEM_COPY);
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't get a check question.");
    } finally {
      if (g === gen.current) setCheckBusy(false);
    }
  };

  const doClose = async () => {
    if (!sessionId || closeBusy) return;
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
      setClose(r);
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

  // ── New session: confirmed whenever an open session would be wrapped up ──
  const sessionIsOpen = !!sessionId && !readOnly && isOpenPhase(state.phase);
  const requestNewSession = (opts: { topic?: string; mode?: string } = {}) => {
    if (!courseId || starting) return;
    if (sessionIsOpen) {
      setConfirmError(null);
      setConfirmNew(opts);
      return;
    }
    void newSession(opts); // nothing open to leave (closed, read-only or none)
  };
  const cancelNewSession = () => {
    if (confirmBusy) return; // a close in flight cannot be taken back
    setConfirmNew(null);
    setConfirmError(null);
  };
  /** Confirm: wait for the close to succeed, THEN start. A 409 or a failed
   *  close keeps the dialog (and the current session) and starts nothing. */
  const confirmNewSession = async () => {
    if (!confirmNew || confirmBusy) return;
    const request = confirmNew;
    setConfirmBusy(true);
    setConfirmError(null);
    const outcome = await wrapUpCurrent();
    if (!mounted.current) return;
    setConfirmBusy(false);
    if (!outcome.ok) {
      if (outcome.reason) setConfirmError(outcome.reason);
      else setConfirmNew(null); // superseded by another switch
      return;
    }
    setConfirmNew(null);
    await newSession(request);
  };

  // ── Derived view data ──────────────────────────────────────────────────
  const conceptNames = useMemo(() => {
    const names = new Map<string, string>();
    for (const n of graph.nodes) if (n.course_id === courseId) names.set(n.id, n.name);
    for (const c of plan ?? []) if (c.concept_name) names.set(c.node_id, c.concept_name);
    return names;
  }, [graph.nodes, plan, courseId]);
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
  // The card shows the current pose and hint; the log hides those rows while
  // the item is current (live and after a reload alike), so nothing renders twice.
  const visibleMessages = useMemo(() => {
    const inCard = new Set<string>();
    if (item?.prompt) inCard.add(item.prompt);
    if (item && hint && "reply" in hint) inCard.add(hint.reply);
    return inCard.size === 0
      ? messages
      : messages.filter((m) => !(m.role === "assistant" && inCard.has(m.content)));
  }, [messages, item, hint]);
  const topicOffer =
    deepLink.topic && sessionId && teaching && !starting && openSessions !== null ? deepLink.topic : null;
  /** The learning route: the server's plan order when this view has it, else
   *  the confirmed goal concepts. Status text is only what the server said
   *  (plan reason, check-in evidence, the concept the last turn named) — never
   *  a mastery claim. */
  const routeItems = useMemo(() => {
    const evidence = new Map((diagnosis?.skills ?? []).map((skill) => [skill.node_id, skill.status]));
    const source = plan && plan.length > 0
      ? plan.map((c) => ({
        id: c.node_id,
        name: c.concept_name || conceptNames.get(c.node_id) || "Concept",
        why: c.reason ? REASON_LABEL[c.reason] : KIND_LABEL[c.kind]?.label,
      }))
      : (goal?.target_node_ids ?? []).map((id) => ({
        id, name: conceptNames.get(id) ?? "Selected concept", why: REASON_LABEL.goal,
      }));
    return source.map((entry) => ({
      ...entry,
      current: teaching && state.focusNodeId === entry.id,
      evidence: evidence.has(entry.id) ? `Check-in: ${skillEvidenceLabel(evidence.get(entry.id))}` : null,
    }));
  }, [plan, goal, diagnosis, conceptNames, teaching, state.focusNodeId]);

  // ── Render ─────────────────────────────────────────────────────────────
  const noCourses = courses !== null && courses.length === 0;
  const loadingSessions =
    !sessionsError && !noCourses && !readOnly && loadError !== "start" &&
    (openSessions === null || (!sessionId && starting));
  const showScope = !!sessionId && !readOnly;
  const canEditGoal = showScope && (state.phase === "probe" || state.phase === "plan");
  const showLearningChrome = !sessionsError && !noCourses && !readOnly;
  // A failed session list must never invite a start that could duplicate an
  // open session it could not see: the strip waits for the Retry.
  const showSessions = !sessionsError && !noCourses;
  const courseLabel = course ? course.course_code || course.course_name : null;
  const studio = studioCopy({
    blocked: sessionsError || noCourses || loadingSessions || (loadError === "start" && !sessionId),
    readOnly: !!readOnly,
    editingGoal: goalEditor,
    phase: state.phase,
    courseName: course?.course_name ?? null,
    noCourses,
  });
  const openGoalEditor = () => { setGoalEditor(true); setGoalError(null); };
  const lastMessageId = messages[messages.length - 1]?.id;
  /** Retry is offered only for the latest interrupted turn of THIS session,
   *  while no other turn or retry runs and chat is allowed (not paused). */
  const canRetry = (m: ChatMsg) =>
    !!m.retryText && !!sessionId && m.turnOwner === sessionId && m.id === lastMessageId &&
    !streaming && !retryBusy && !paused && teaching;
  const openContext = (tab: TutorContextTab) => {
    setHistoryOpen(false);
    setContextTab((current) => (current === tab && !compact ? null : tab));
  };
  // Materials: real course context from Library, never an attachment.
  const materialsLead = view === "tutor" ? (
    <button
      type="button"
      className={styles.materialsLead}
      data-testid="tutor-materials-open"
      aria-haspopup={compact ? "dialog" : undefined}
      onClick={() => openContext("materials")}
    >
      <BotanicalIcon name="paper" size={18} />
      Materials
    </button>
  ) : (
    <Link href="/library" className={styles.materialsLead} data-testid="loop-materials-link">
      <BotanicalIcon name="paper" size={18} />
      Course materials
    </Link>
  );

  const courseSelect = courses && courses.length > 1 && (
    <CustomSelect<string>
      testId="loop-course-select"
      value={courseId ?? ""}
      options={courses.map((c) => ({ value: c.course_id, label: c.course_code || c.course_name }))}
      onChange={(v) => {
        ++gen.current;
        clearSessionView();
        setSessionId(null);
        sessionRef.current = null;
        setOpenSessions(null);
        setCourseId(v);
      }}
      ariaLabel="Course"
      size="sm"
    />
  );
  const heading = (
    <div className={styles.heading}>
      <PageHeading
        testid="loop-heading"
        eyebrow={courseLabel ? <>Learning studio <span aria-hidden="true">/</span> {courseLabel}</> : "Learning studio"}
        title={studio.title}
        description={studio.description}
        actions={
          <>
            {courseSelect}
            {tutorOffered && (
              <SaplingAction tone="quiet" data-testid="loop-view-tutor" onClick={() => switchView("tutor")}>
                Open Clov tutor
              </SaplingAction>
            )}
            <Link data-testid="loop-tree-link" href={treeHref} className={styles.headerLink}>
              Knowledge map
            </Link>
            {teaching && sessionId && (
              <SaplingAction
                tone="secondary"
                data-testid="loop-close-button"
                onClick={() => void doClose()}
                disabled={closeBusy}
                title="Wrap up this session"
              >
                {closeBusy ? "Closing…" : "End session"}
              </SaplingAction>
            )}
            <AIDisclaimerChip />
          </>
        }
      />
    </div>
  );

  const sessionStrip = (
    <section className={styles.sessions} aria-label="Your sessions">
      <span className={styles.sessionsLabel}>Open sessions</span>
      <div data-testid="loop-session-picker" role="list" className={styles.sessionList}>
        {(openSessions ?? []).map((s) => {
          const current = s.session_id === sessionId;
          return (
            <div role="listitem" key={s.session_id} className={styles.sessionItem}>
              <button
                type="button"
                data-testid={`loop-session-${s.session_id}`}
                aria-current={current ? "true" : undefined}
                className={styles.sessionChip}
                onClick={() => { if (!current) void resume(s); }}
                title={current ? "Current session" : `Resume “${s.topic}”`}
              >
                <span className={styles.sessionTopic}>{s.topic || "Session"}</span>
                <span className={styles.sessionDate}>{shortDate(s.started_at)}</span>
                {current && <span className="sapling-visually-hidden"> (current session)</span>}
              </button>
            </div>
          );
        })}
        {openSessions !== null && openSessions.length === 0 && (
          <span className={styles.muted}>None yet</span>
        )}
      </div>
      <SaplingAction
        tone="secondary"
        data-testid="loop-new-session"
        className={styles.newSession}
        onClick={() => requestNewSession()}
        disabled={!courseId || starting}
        title={sessionIsOpen ? "Wrap up this session and start a new one" : "Start a new session"}
      >
        + New session
      </SaplingAction>
    </section>
  );

  const goalStrip = showScope && (
    <div className={styles.goalStrip} data-testid="loop-goal-summary">
      {scopeError ? (
        <StatusMessage tone="error" testid="loop-goal" onRetry={() => void retryLearningScope()} retryLabel="Retry learning scope">
          Couldn&apos;t load this session&apos;s learning scope. Nothing was changed.
        </StatusMessage>
      ) : !scopeReady ? (
        <StatusMessage tone="pending">Loading learning scope…</StatusMessage>
      ) : (
        <GoalSummary
          heading={goal ? "Your goal" : "Your scope"}
          goal={goal ? goal.text || "Selected concepts" : "Explore the whole course"}
          scope={goal ? goal.target_node_ids.map((id) => conceptNames.get(id) ?? "Selected concept").join(" + ") : undefined}
          action={canEditGoal ? (
            <SaplingAction
              ref={goalButton}
              tone="quiet"
              data-testid="loop-set-goal"
              disabled={starting || probeBusy || planBusy || goalBusy || !scopeReady}
              onClick={openGoalEditor}
            >
              {goal ? "Edit goal" : "Set goal"}
            </SaplingAction>
          ) : teaching ? (
            <>
              <span className={styles.goalNote}>To change your goal, start a new session.</span>
              <SaplingAction
                tone="quiet"
                data-testid="loop-goal-new-session"
                disabled={!courseId || starting}
                onClick={() => requestNewSession()}
              >
                New session
              </SaplingAction>
            </>
          ) : null}
        />
      )}
    </div>
  );

  const progressNote = goalProgress && goal && (
    <StatusMessage
      tone="info"
      testid="loop-goal-progress"
      title={goalProgress.status === "continue_available"
        ? "A next step is ready"
        : goalProgress.status === "needs_more_practice" ? "More practice needed" : "Planned practice finished"}
    >
      {goalProgress.status === "continue_available"
        ? "The next step toward your goal is ready to review. Approve the new plan before continuing."
        : goalProgress.status === "needs_more_practice"
          ? "Your goal still needs prerequisite practice. No fresh next step is available in this session; review your material or start another session."
          : "You finished the practice planned for this session. This does not establish mastery; check what you retain after time away."}
      {goalProgress.unresolved_prerequisite_ids.length > 0 && <span> Prerequisites needing practice: {goalProgress.unresolved_prerequisite_ids.map((id) => conceptNames.get(id) ?? "A prerequisite").join(", ")}.</span>}
      {goalProgress.remaining_target_node_ids.length > 0 && <span> Goal concepts remaining: {goalProgress.remaining_target_node_ids.map((id) => conceptNames.get(id) ?? "A selected concept").join(", ")}.</span>}
    </StatusMessage>
  );

  const learnerChip = (
    <span
      data-testid="loop-learner-state"
      data-node-id={learner?.node_id ?? ""}
      data-p-known={learner ? String(learner.p_known) : ""}
      data-band={learner?.band ?? ""}
      className={styles.learnerChip}
      hidden={!learner}
    >
      {learner
        ? `${conceptNames.get(learner.node_id) ?? "This concept"} · ${BAND_LABEL[learner.band] ?? learner.band}`
        : "—"}
    </span>
  );

  const phaseRow = showLearningChrome && (
    <div className={styles.phaseRow}>
      <PhaseStrip phase={sessionId ? state.phase : null} testid="loop-phase-strip" />
      <div className={styles.phaseSide}>
        {learnerChip}
        {compact && (
          <button
            type="button"
            className={`sapling-context-trigger ${styles.routeTrigger}`}
            aria-haspopup="dialog"
            aria-expanded={routeOpen}
            data-testid="loop-route-trigger"
            onClick={() => setRouteOpen(true)}
          >
            <BotanicalIcon name="paper" size={18} />
            Route &amp; sources
          </button>
        )}
      </div>
    </div>
  );

  const notices = (paused || noCheckItems || topicOffer || (closeNote && state.phase !== "close")) && (
    <div className={styles.notices}>
      {paused && (
        <BudgetPausedBanner
          testId="loop-budget-paused"
          resetAt={paused.resetAt}
          sessionCapped={paused.sessionCapped}
          message={tutorPauseMessage(paused.resetAt, paused.sessionCapped)}
        >
          {" "}
          <Link data-testid="loop-budget-study-link" href="/study?mode=cards" className={styles.textLink}>
            Review flashcards
          </Link>
        </BudgetPausedBanner>
      )}
      {noCheckItems && (
        <StatusMessage tone="info" testid="loop-no-check-items">{NO_CHECK_ITEMS_COPY}</StatusMessage>
      )}
      {topicOffer && (
        // ?topic= while a session is open: resume won (a reload never starts a
        // probe, §11.3); the link's concept is one confirmed click away, never automatic.
        <div data-testid="loop-topic-offer" role="status" className={styles.topicOffer}>
          <span>You picked “{topicOffer}”. This session is still open.</span>
          <SaplingAction
            tone="secondary"
            data-testid="loop-topic-start"
            disabled={starting}
            onClick={() => requestNewSession({ topic: topicOffer, mode: deepLink.mode })}
          >
            Start a session on {topicOffer}
          </SaplingAction>
        </div>
      )}
      {closeNote && state.phase !== "close" && (
        <StatusMessage tone="info" testid="loop-close-note">{closeNote}</StatusMessage>
      )}
    </div>
  );

  let body: React.ReactNode;
  if (sessionsError) {
    body = (
      <div className={styles.centerState} data-testid="loop-sessions-error">
        <StatusMessage tone="error" title="Couldn't load your sessions">
          Nothing was started. Try again to pick up where you left off.
        </StatusMessage>
        <SaplingAction data-testid="loop-sessions-retry" onClick={retrySessions}>Retry</SaplingAction>
      </div>
    );
  } else if (noCourses) {
    body = (
      <div className={styles.centerState} data-testid="loop-no-course">
        <h2 className={styles.panelTitle}>Add a course to start learning</h2>
        <p className={styles.panelLead}>
          The tutor works course by course — add one from your{" "}
          <Link data-testid="loop-no-course-link" href="/tree" className={styles.textLink}>knowledge map</Link>.
        </p>
      </div>
    );
  } else if (readOnly) {
    body = (
      <div className={styles.panel}>
        <div className={styles.readOnlyBar}>
          <span className={styles.tag}>Read-only</span>
          <span className={styles.muted}>
            {readOnly.topic ? `“${readOnly.topic}” — ` : ""}an earlier session. Start a new one to keep learning.
          </span>
          <SaplingAction data-testid="loop-readonly-new-session" onClick={() => requestNewSession()}>
            Start a new session
          </SaplingAction>
        </div>
        <div data-testid="loop-readonly-transcript" className={styles.transcript}>
          {readOnly.messages.length === 0 && <p className={styles.muted}>No messages in this session.</p>}
          {readOnly.messages.map((m) => (
            <div key={m.id} className={styles.transcriptRow} data-role={m.role}>
              <p className={styles.transcriptWho}>{m.role === "user" ? "You" : "Tutor"}</p>
              <div className={styles.transcriptText}>{m.content}</div>
            </div>
          ))}
        </div>
      </div>
    );
  } else if (loadError === "start" && !sessionId) {
    body = (
      <div className={styles.centerState} data-testid="loop-start-error">
        <StatusMessage tone="error" title="Couldn't start a session">
          Nothing was started. Try again in a moment.
        </StatusMessage>
        <SaplingAction
          data-testid="loop-start-retry"
          disabled={starting}
          onClick={() => void newSession({ topic: deepLink.topic, mode: deepLink.mode })}
        >
          Try again
        </SaplingAction>
      </div>
    );
  } else if (loadingSessions) {
    body = (
      <div className={styles.centerState}>
        <StatusMessage tone="pending">{starting ? "Starting your session…" : "Loading your sessions…"}</StatusMessage>
      </div>
    );
  } else if (welcome && !sessionId) {
    body = (
      <TutorWelcome
        courseLabel={courseLabel}
        starting={starting}
        onStartCheckIn={() => requestNewSession()}
        onAsk={(text) => requestNewSession({ topic: text })}
        materials={materialsLead}
      />
    );
  } else if (goalEditor) {
    body = <GoalEditor key={`${sessionId}:${courseId}`} goal={goal}
      nodes={railGraph.nodes.filter((node) => !node.is_subject_root)} busy={goalBusy} error={goalError}
      loadingNodes={graphLoading} nodesError={graphError} onRetryNodes={() => void refreshGraph()}
      onSave={(next) => void saveGoal(next)} onCancel={() => { setGoalEditor(false); goalButton.current?.focus(); }} />;
  } else if (state.phase === "probe") {
    body = (
      <ProbePanel
        diagnosis={diagnosis}
        names={conceptNames}
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
    body = (
      <PlanPanel
        diagnosis={diagnosis}
        names={conceptNames}
        plan={plan}
        busy={planBusy}
        loadFailed={loadError === "plan"}
        onApprove={() => void approvePlan()}
        onRetry={() => { if (sessionId) void loadPlan(sessionId, gen.current); }}
        onAdjust={canEditGoal && scopeReady && !goalBusy ? openGoalEditor : undefined}
      />
    );
  } else if (state.phase === "close") {
    body = <ClosePanel close={close} note={closeNote} names={conceptNames} courseId={courseId} />;
  } else {
    const firstConcept = plan?.[0];
    const tutorView = view === "tutor";
    // Conversation seeds ask for teaching through the chat stream; none grades.
    const canSeed = !paused && !streaming && !!sessionId;
    const teachActions = (
      <>
        {state.phase === "feedback" && (
          <SaplingAction
            data-testid="loop-continue"
            onClick={() => send(CONTINUE_MESSAGE)}
            disabled={!!paused || streaming}
          >
            {tutorView ? "Continue learning" : "Continue"}
          </SaplingAction>
        )}
        {(messages.length <= 1 || planJustApproved) && firstConcept && state.phase === "teach" && !paused && (
          <SaplingAction
            data-testid="loop-teach-start"
            onClick={() => send(`Teach me about ${firstConcept.concept_name}.`)}
            disabled={streaming}
          >
            Start with {firstConcept.concept_name}
          </SaplingAction>
        )}
        <SaplingAction
          tone={tutorView && state.phase !== "feedback" ? "primary" : "secondary"}
          data-testid="loop-check-me"
          className={tutorView ? styles.checkMeWide : undefined}
          onClick={() => void checkMe()}
          disabled={checkBusy || streaming}
          title="Get a question on this concept"
        >
          {checkBusy
            ? "Getting a question…"
            : tutorView
              ? state.phase === "feedback" ? "Try another check" : "Check my understanding"
              : "Check me"}
        </SaplingAction>
        {state.phase !== "feedback" && (
          <>
            <SaplingAction tone="secondary" data-testid="loop-seed-confused" disabled={!canSeed} onClick={() => send(CONVERSATION_SEEDS.confused)}>
              I&apos;m confused
            </SaplingAction>
            <SaplingAction tone="secondary" data-testid="loop-seed-example" disabled={!canSeed} onClick={() => send(CONVERSATION_SEEDS.example)}>
              Another example
            </SaplingAction>
          </>
        )}
        {checkNote && <span role="status" className={styles.muted}>{checkNote}</span>}
      </>
    );
    body = (
      <div className={styles.teach} data-view={view}>
        <div className={styles.teachTop}>
          {recoveryNote && <StatusMessage tone="info" testid="loop-recovery-note">{recoveryNote}</StatusMessage>}
          {askRating && askRating === sessionId && <RatingPrompt onRate={rate} />}
          {item ? (
            <CheckCard
              item={item}
              draft={attempt}
              setDraft={setAttempt}
              busy={attemptBusy || streaming}
              hint={hint}
              hintBusy={hintBusy}
              hintRetry={hintRetry}
              onSubmit={() => void submitAttempt(false)}
              onIdk={() => void submitAttempt(true)}
              onHint={() => void askHint()}
            />
          ) : !tutorView ? (
            <div className={styles.teachActions}>{teachActions}</div>
          ) : null}
        </div>
        <div data-testid="loop-messages" className={styles.conversation}>
          <ChatPanel
            messages={visibleMessages}
            onSend={send}
            streamingText={streamingText}
            onStop={stop}
            onRetry={(m) => void retryTurn(m)}
            canRetry={canRetry}
            disabled={!!paused}
            disabledReason={paused ? "Tutor chat is paused. Check answers still count, and review stays open." : undefined}
            placeholder={paused ? "Chat is paused" : tutorView ? "Ask Clov, or think out loud…" : "Ask the tutor…"}
            inputLabel="Message Clov"
            // In the tutor the actions sit above the composer (ULhG3) — outside
            // the transcript's scroll box, so they never overlap a message.
            beforeComposer={tutorView && !item ? <div className={styles.teachActions}>{teachActions}</div> : undefined}
            composerLead={materialsLead}
          />
        </div>
      </div>
    );
  }

  const routeEmpty = teaching
    ? "Your approved plan guides this session. Use Check me when you're ready for a question."
    : state.phase === "close"
      ? "This session is wrapped up."
      : "Your route appears once the check-in builds a plan.";
  const routeContext = (
    <div className={styles.route}>
      <section aria-labelledby="loop-route-heading" className={styles.routeSection}>
        <h2 id="loop-route-heading" className={styles.railTitle}>Your learning route</h2>
        {routeItems.length > 0 ? (
          <ol className={styles.routeList} data-testid="loop-route">
            {routeItems.map((entry) => (
              <li key={entry.id} data-testid={`loop-route-${entry.id}`} data-current={entry.current || undefined}>
                <span className={styles.routeMark} aria-hidden="true" />
                <div>
                  <p className={styles.routeName}>{entry.name}</p>
                  <p className={styles.routeDetail}>
                    {[entry.current ? "Current focus" : null, entry.why, entry.evidence].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className={styles.muted}>{routeEmpty}</p>
        )}
      </section>
      <section aria-labelledby="loop-map-heading" className={styles.routeSection}>
        <h2 id="loop-map-heading" className={styles.railTitle}>Knowledge map</h2>
        {railGraph.nodes.length > 0 ? (
          <RailGraph nodes={railGraph.nodes} edges={railGraph.edges} highlightId={focusNodeId ?? undefined} />
        ) : (
          <p className={styles.muted}>Concepts appear here as you learn.</p>
        )}
      </section>
      <section aria-labelledby="loop-sources-heading" className={styles.routeSection}>
        <h2 id="loop-sources-heading" className={styles.railTitle}>Keep your sources close.</h2>
        <ul className={styles.sourceLinks}>
          <li>
            <Link href="/library" className={styles.sourceLink}>
              <BotanicalIcon name="paper" size={20} />
              <span>Course materials in Library</span>
            </Link>
          </li>
          <li>
            <Link href="/study?mode=cards" className={styles.sourceLink}>
              <BotanicalIcon name="library" size={20} />
              <span>Review flashcards</span>
            </Link>
          </li>
        </ul>
      </section>
    </div>
  );

  if (view === "tutor") {
    const tab = contextTab;
    const contextTitle = tab ? CONTEXT_TITLES[tab] : "";
    const goalText = goal ? goal.text || "Selected concepts" : "Explore the whole course";
    const focusTitle =
      (state.focusNodeId ? conceptNames.get(state.focusNodeId) : undefined) ??
      plan?.[0]?.concept_name ??
      course?.course_name ??
      "Your session";
    const inSession = !!sessionId && !readOnly;
    const contextContent = tab === "goal" ? (
      <GoalPlanContext
        goalText={goalText}
        scope={goal ? goal.target_node_ids.map((id) => conceptNames.get(id) ?? "Selected concept").join(" · ") : null}
        route={routeItems}
        teaching={teaching}
        diagnosis={<DiagnosisSummary diagnosis={diagnosis} names={conceptNames} />}
        onEditGoal={canEditGoal && scopeReady && !goalBusy ? () => { setContextTab(null); openGoalEditor(); } : undefined}
        onNewSession={inSession ? () => { setContextTab(null); requestNewSession(); } : undefined}
        emptyCopy={routeEmpty}
      />
    ) : tab === "materials" ? (
      <MaterialsContext userId={userId} courseId={courseId} courseLabel={courseLabel} />
    ) : tab === "map" ? (
      <MapContext
        graph={railGraph.nodes.length > 0
          ? <RailGraph nodes={railGraph.nodes} edges={railGraph.edges} highlightId={focusNodeId ?? undefined} height={TUTOR_GRAPH_HEIGHT} />
          : <p className={styles.muted}>Concepts appear here as you learn.</p>}
        courseLabel={courseLabel}
        conceptCount={railGraph.nodes.filter((n) => !n.is_subject_root).length}
        focusName={focusNodeId ? conceptNames.get(focusNodeId) ?? null : null}
        treeHref={treeHref}
      />
    ) : null;
    const closeContext = () => {
      const was = contextTab;
      setContextTab(null);
      if (was && !compact) {
        requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-testid="tutor-context-${was}"]`)?.focus());
      }
    };
    return (
      <FullHeightScreen className={styles.screen}>
        <DisclaimerModal />
        <div
          data-testid="loop-phase"
          data-phase={state.phase}
          data-session-id={sessionId ?? ""}
          data-view="tutor"
          className={`${styles.studio} ${styles.tutor}`}
        >
          <div className={styles.top}>
            <TutorBar
              course={courseSelect || <span className={styles.tutorCourse}>{courseLabel ?? "Your course"}</span>}
              historyOpen={historyOpen}
              onHistory={() => { setContextTab(null); setHistoryOpen(true); }}
              newSession={
                <SaplingAction
                  tone="secondary"
                  data-testid="loop-new-session"
                  onClick={() => requestNewSession()}
                  disabled={!courseId || starting || !showSessions}
                  aria-label="New session"
                  title={sessionIsOpen ? "Wrap up this session and start a new one" : "Start a new session"}
                >
                  <span aria-hidden="true">+</span>
                  <span className={styles.tutorBarLabel}> New session</span>
                </SaplingAction>
              }
              menu={
                <TutorMenu
                  items={[
                    { id: "goal", label: "View goal & plan", onSelect: () => openContext("goal"), disabled: !inSession },
                    { id: "materials", label: "Open course materials", onSelect: () => openContext("materials") },
                    { id: "map", label: "Open the knowledge map", onSelect: () => openContext("map") },
                    ...(teaching && sessionId
                      ? [{ id: "end", label: closeBusy ? "Closing…" : "End session & review", onSelect: () => void doClose(), disabled: closeBusy }]
                      : []),
                    { id: "studio", label: "Switch to the Learning studio", onSelect: () => switchView("learn") },
                  ]}
                />
              }
            />
          </div>
          <div className={styles.workspace}>
            {/* HHU6e: the context panel sits beside everything under the bar,
                so the column it narrows stays one centred column. */}
            <div className={styles.tutorColumn}>
              <div className={styles.tutorTop}>
                {inSession && showLearningChrome && (
                  <div className={styles.tutorNav}>
                    <div className={styles.phaseRow}>
                      <PhaseStrip phase={state.phase} testid="loop-phase-strip" />
                      <div className={styles.phaseSide}>{learnerChip}</div>
                    </div>
                    <ContextChips active={tab} onSelect={openContext} panelId={compact ? undefined : "tutor-context-panel"} />
                  </div>
                )}
                {!(welcome && !sessionId) && (
                  <div className={styles.tutorHeading}>
                    {inSession && teaching ? (
                      <>
                        <p className={styles.tutorGoalLine} data-testid="tutor-goal-line">
                          <span className={styles.tutorGoalTag}>Goal</span> <span aria-hidden="true">·</span> {goalText}
                        </p>
                        <h1 className={styles.tutorTitle}>{focusTitle}</h1>
                      </>
                    ) : (
                      <>
                        <h1 className={styles.tutorTitle}>{studio.title}</h1>
                        {studio.description && <p className={styles.panelLead}>{studio.description}</p>}
                      </>
                    )}
                  </div>
                )}
                {progressNote}
                {notices}
              </div>
              <div className={`${styles.main} ${styles.tutorMain}`}>{body}</div>
            </div>
            {!compact && tab && (
              <aside
                id="tutor-context-panel"
                className={styles.tutorContext}
                aria-labelledby="tutor-context-title"
                data-testid="tutor-context-panel"
              >
                <div className={styles.tutorContextHead}>
                  <h2 id="tutor-context-title" className={styles.tutorContextTitle}>{contextTitle}</h2>
                  <button
                    type="button"
                    className={styles.tutorContextClose}
                    data-testid="tutor-context-close"
                    aria-label={`Close ${contextTitle}`}
                    onClick={closeContext}
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </div>
                {contextContent}
              </aside>
            )}
          </div>
        </div>
        {compact && (
          <ContextSheet open={!!tab} onClose={() => setContextTab(null)} title={contextTitle} testid="tutor-context-sheet">
            <div className={styles.tutorSheetBody}>
              {contextContent}
              <SaplingAction data-testid="tutor-context-back" onClick={() => setContextTab(null)}>
                Back to conversation
              </SaplingAction>
            </div>
          </ContextSheet>
        )}
        <ContextSheet
          open={historyOpen}
          onClose={() => setHistoryOpen(false)}
          title="Your conversations"
          side={compact ? "bottom" : "right"}
          testid="tutor-history-sheet"
        >
          <TutorHistory
            userId={userId}
            courseId={courseId}
            open={sessionsError ? [] : openSessions ?? []}
            currentId={sessionId}
            onResume={(s) => {
              setHistoryOpen(false);
              if (s.session_id !== sessionId) void resume(s);
            }}
            onOpenPast={(id) => {
              setHistoryOpen(false);
              void openReadOnly(id);
            }}
            onNewSession={() => {
              setHistoryOpen(false);
              requestNewSession();
            }}
          />
        </ContextSheet>
        <NewSessionConfirm
          open={confirmNew !== null}
          topic={confirmNew?.topic ?? null}
          busy={confirmBusy}
          error={confirmError}
          onCancel={cancelNewSession}
          onConfirm={() => void confirmNewSession()}
        />
      </FullHeightScreen>
    );
  }

  return (
    <FullHeightScreen className={styles.screen}>
      <DisclaimerModal />
      <div
        data-testid="loop-phase"
        data-phase={state.phase}
        data-session-id={sessionId ?? ""}
        className={styles.studio}
      >
        <div className={styles.top}>
          {heading}
          {!phone && showSessions && sessionStrip}
          {goalStrip}
          {progressNote}
          {phaseRow}
          {notices}
        </div>
        <div className={styles.workspace}>
          <div className={styles.main}>{body}</div>
          {showLearningChrome && (
            <ContextPanel
              label="Learning route and sources"
              breakpoint={RAIL_BREAKPOINT}
              open={routeOpen}
              onOpenChange={setRouteOpen}
              hideTrigger
              testid="loop-rail"
            >
              {routeContext}
            </ContextPanel>
          )}
        </div>
        {phone && showSessions && <div className={styles.sessionsBottom}>{sessionStrip}</div>}
      </div>
      <NewSessionConfirm
        open={confirmNew !== null}
        topic={confirmNew?.topic ?? null}
        busy={confirmBusy}
        error={confirmError}
        onCancel={cancelNewSession}
        onConfirm={() => void confirmNewSession()}
      />
    </FullHeightScreen>
  );
}

/** A session the "New session" button should wrap up first: one the student is in. */
function isOpenPhase(phase: LoopPhase): boolean {
  return phase !== "close";
}

/** The studio's page title and lead for where the learner is. The phase is the
 *  server's; this only names it. "Wrap up", never "Review": closing a session
 *  is not a delayed retention check. */
function studioCopy({ blocked, readOnly, editingGoal, phase, courseName, noCourses }: {
  blocked: boolean; readOnly: boolean; editingGoal: boolean; phase: LoopPhase; courseName: string | null; noCourses: boolean;
}): { title: string; description?: string } {
  if (noCourses) return { title: "Start with a course." };
  if (blocked) return { title: courseName ?? "Pick up where you left off." };
  if (readOnly) return { title: "An earlier session.", description: "Read-only. Nothing here changes your progress." };
  if (editingGoal) return { title: "Choose what to work on." };
  switch (phase) {
    case "probe":
      return {
        title: "Find your starting point.",
        description: "A few questions so the tutor knows where to start. Answer what you can — “I don't know yet” is a fine answer.",
      };
    case "plan":
      return { title: "Review your plan.", description: "Built from your check-in. Nothing starts until you approve it." };
    case "close":
      return { title: "Wrap up and reflect." };
    default:
      return { title: "Work through your plan." };
  }
}

// ── Pieces ─────────────────────────────────────────────────────────────────

/** The knowledge-map rail: `KnowledgeGraph` fed as Learn.tsx's
 *  SidebarKnowledgeGraph feeds it (measured width, fixed height, original colours). */
function RailGraph({ nodes, edges, highlightId, height = RAIL_GRAPH_HEIGHT }: {
  nodes: GraphNode[]; edges: GraphEdge[]; highlightId?: string; height?: number;
}) {
  const [width, setWidth] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} className={styles.railGraph}>
      {width > 0 && (
        <KnowledgeGraph nodes={nodes} edges={edges} width={width} height={height} highlightId={highlightId} />
      )}
    </div>
  );
}

/** Clov's line: the approved flower mark beside a sentence from the tutor. */
function ClovNote({ children }: { children: React.ReactNode }) {
  return (
    <div className={styles.clovNote}>
      <BotanicalIcon name="clov" size={28} label="Clov" />
      <p className={styles.clovText}>{children}</p>
    </div>
  );
}

/** A served prompt. Fenced code (```…```) renders as a code block; everything
 *  else stays the server's text, line breaks kept. Nothing is rewritten. */
function PromptText({ text, id }: { text: string; id?: string }) {
  const parts: { code?: string; text?: string }[] = [];
  const fence = /```[^\n`]*\n?([\s\S]*?)```/g;
  let last = 0;
  for (let m = fence.exec(text); m; m = fence.exec(text)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index) });
    parts.push({ code: m[1].replace(/\n$/, "") });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return (
    <div id={id} className={styles.prompt}>
      {parts.map((part, i) => part.code !== undefined
        ? <pre key={i} className={styles.code}><code>{part.code}</code></pre>
        : part.text!.trim() && <p key={i} className={styles.promptText}>{part.text!.replace(/^\n+|\n+$/g, "")}</p>)}
    </div>
  );
}

/** The explicit answer form shared by the check-in and knowledge checks:
 *  mc_reason = the served options in served order (a native radio group; sage
 *  means SELECTED only) plus an optional reason; free/teachback = answer text;
 *  "I don't know yet" submits idk. Only `onSubmit`/`onIdk` ever grade. */
function AnswerForm({
  kind, item, draft, setDraft, busy, promptId, onSubmit, onIdk, aside,
}: {
  kind: "probe" | "attempt";
  item: LoopCheckItem;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  busy: boolean;
  promptId: string;
  onSubmit: () => void;
  onIdk: () => void;
  /** Extra controls in the action row (the check's Hint). */
  aside?: React.ReactNode;
}) {
  const mc = item.format === "mc_reason";
  const canSubmit = !busy && (mc ? draft.option !== "" : draft.answer.trim() !== "");
  const answerId = React.useId();
  const reasonId = React.useId();
  const probe = kind === "probe";
  return (
    <form
      className={styles.answerForm}
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) onSubmit();
      }}
    >
      {mc ? (
        <>
          <ChoiceGroup
            legend={<span className="sapling-visually-hidden">Choose an answer</span>}
            describedBy={promptId}
            options={(item.options ?? []).map((o) => ({
              value: o.letter, letter: o.letter, label: o.text, testid: `loop-${kind}-option-${o.letter}`,
            }))}
            value={draft.option || null}
            onChange={(letter) => setDraft((d) => ({ ...d, option: letter }))}
            disabled={busy}
          />
          <div className={styles.field}>
            <label htmlFor={reasonId} className={styles.fieldLabel}>
              {probe ? "Check-in reasoning" : "Your reasoning"} <span className={styles.fieldHint}>(optional)</span>
            </label>
            <input
              id={reasonId}
              data-testid={`loop-${kind}-reason`}
              className={styles.input}
              placeholder="In one sentence, what helped you choose?"
              value={draft.reason}
              disabled={busy}
              onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))}
            />
          </div>
        </>
      ) : (
        <div className={styles.field}>
          <label htmlFor={answerId} className={styles.fieldLabel}>{probe ? "Check-in answer" : "Your answer"}</label>
          <textarea
            id={answerId}
            data-testid={`loop-${kind}-input`}
            aria-describedby={promptId}
            className={styles.input}
            rows={3}
            placeholder={item.format === "teachback" ? "Explain it in your own words" : probe ? "Your answer" : "Your answer — this is what gets checked"}
            value={draft.answer}
            disabled={busy}
            onChange={(e) => setDraft((d) => ({ ...d, answer: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) {
                e.preventDefault();
                onSubmit();
              }
            }}
          />
        </div>
      )}
      <div className={styles.answerActions}>
        <SaplingAction type="submit" data-testid={`loop-${kind}-submit`} disabled={!canSubmit}>
          {busy ? "Checking…" : "Submit answer"}
        </SaplingAction>
        <SaplingAction tone="secondary" data-testid={`loop-${kind}-idk`} disabled={busy} onClick={onIdk}>
          I don&apos;t know yet
        </SaplingAction>
        {aside}
      </div>
    </form>
  );
}

function ProbePanel({
  item, count, draft, setDraft, reference, note, busy, loadFailed, greeting, onSubmit, onIdk, onNext, onRetry, diagnosis, names,
}: {
  diagnosis: LoopDiagnosis | null;
  names: Map<string, string>;
  item: LoopProbeItem | null;
  count: number;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  reference: string | null;
  note: string | null;
  busy: boolean;
  /** The next item failed to load (not a pause): offer a retry, never an empty card. */
  loadFailed: boolean;
  /** The session opener (model-written, or the hard-level template, A27). */
  greeting: string | null;
  onSubmit: () => void;
  onIdk: () => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  const headingId = React.useId();
  const promptId = React.useId();
  return (
    <div className={styles.panel}>
      {greeting && <ClovNote>{greeting}</ClovNote>}
      {!item && busy && <StatusMessage tone="pending">Loading the next question…</StatusMessage>}
      {!item && !busy && loadFailed && (
        <div className={styles.retryRow}>
          <StatusMessage tone="error">The next question didn&apos;t load. Your earlier answers are saved.</StatusMessage>
          <SaplingAction tone="secondary" data-testid="loop-probe-retry" onClick={onRetry}>Try again</SaplingAction>
        </div>
      )}
      {item && (
        <section
          data-testid="loop-probe-item"
          data-question-hash={item.question_hash}
          data-difficulty={item.difficulty}
          aria-labelledby={headingId}
          className={styles.question}
        >
          <h2 id={headingId} className="sapling-eyebrow">
            Check-in <span aria-hidden="true">·</span> Question {count + (reference === null ? 1 : 0)}
          </h2>
          <PromptText text={item.prompt} id={promptId} />
          {reference === null ? (
            <AnswerForm
              kind="probe"
              item={item}
              draft={draft}
              setDraft={setDraft}
              busy={busy}
              promptId={promptId}
              onSubmit={onSubmit}
              onIdk={onIdk}
            />
          ) : (
            <>
              <div data-testid="loop-probe-reference" className={styles.reference}>
                <p className="sapling-eyebrow">Here&apos;s the answer</p>
                <div className={styles.referenceText}>{reference}</div>
              </div>
              <div className={styles.answerActions}>
                <SaplingAction data-testid="loop-probe-next" disabled={busy} onClick={onNext}>
                  Next
                </SaplingAction>
              </div>
            </>
          )}
        </section>
      )}
      {note && <StatusMessage tone="info">{note}</StatusMessage>}
      <DiagnosisSummary diagnosis={diagnosis} names={names} />
    </div>
  );
}

function PlanPanel({
  plan, busy, loadFailed, onApprove, onRetry, onAdjust, diagnosis, names,
}: {
  diagnosis: LoopDiagnosis | null;
  names: Map<string, string>;
  plan: LoopPlanConcept[] | null;
  busy: boolean;
  loadFailed: boolean;
  onApprove: () => void;
  onRetry: () => void;
  /** Open the goal editor (plan phase only). */
  onAdjust?: () => void;
}) {
  const listHeading = React.useId();
  const approveHeading = React.useId();
  return (
    <div className={styles.panel}>
      {plan === null && !loadFailed && <StatusMessage tone="pending">Building your plan…</StatusMessage>}
      {plan === null && loadFailed && (
        <div className={styles.retryRow}>
          <StatusMessage tone="error">Today&apos;s plan didn&apos;t load. Nothing was approved.</StatusMessage>
          <SaplingAction tone="secondary" data-testid="loop-plan-retry" onClick={onRetry}>Try again</SaplingAction>
        </div>
      )}
      {plan !== null && plan.length === 0 && (
        <StatusMessage tone="info">Nothing to plan right now — ask the tutor anything.</StatusMessage>
      )}
      {plan && plan.length > 0 && (
        <>
          <ClovNote>Based on your check-in, here&apos;s a path we can work through together.</ClovNote>
          <section aria-labelledby={listHeading} className={styles.planSection}>
            <h2 id={listHeading} className="sapling-eyebrow">Proposed plan, in order</h2>
            <ol className={styles.planList}>
              {plan.map((c, i) => {
                const kind = KIND_LABEL[c.kind];
                return (
                  <li key={c.node_id} data-testid={`loop-plan-concept-${c.node_id}`} className={styles.planItem}>
                    <span className={styles.planIndex} aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                    <div className={styles.planBody}>
                      <h3 className={styles.planName}>{c.concept_name || "Concept"}</h3>
                      {c.reason && (
                        <p data-testid={`loop-plan-reason-${c.node_id}`} className={styles.planReason}>
                          {REASON_LABEL[c.reason] ?? "Related practice"}
                        </p>
                      )}
                      {(c.band || kind) && (
                        <p className={styles.planTags}>
                          {kind && <span className={styles.tag} data-kind={c.kind}>{kind.label}</span>}
                          {c.band && <span className={styles.tag}>{BAND_LABEL[c.band] ?? c.band}</span>}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        </>
      )}
      <DiagnosisSummary diagnosis={diagnosis} names={names} />
      {plan && plan.length > 0 && (
        <section aria-labelledby={approveHeading} className={styles.approve}>
          <h2 id={approveHeading} className={styles.panelTitle}>Does this plan work for you?</h2>
          <p className={styles.panelLead}>
            Review the goal and scope before you begin. A prerequisite comes before the goal it supports.
          </p>
          <div className={styles.answerActions}>
            <SaplingAction data-testid="loop-plan-approve" disabled={busy} onClick={onApprove}>
              {busy ? "Saving…" : "Approve and start learning"}
            </SaplingAction>
            {onAdjust && (
              <SaplingAction tone="quiet" data-testid="loop-plan-adjust" disabled={busy} onClick={onAdjust}>
                Adjust goal or scope
              </SaplingAction>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

function CheckCard({
  item, draft, setDraft, busy, hint, hintBusy, hintRetry, onSubmit, onIdk, onHint,
}: {
  item: LoopCheckItem;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  busy: boolean;
  hint: HintView;
  hintBusy: boolean;
  hintRetry: boolean;
  onSubmit: () => void;
  onIdk: () => void;
  onHint: () => void;
}) {
  const headingId = React.useId();
  const promptId = React.useId();
  return (
    <section
      data-testid="loop-check-prompt"
      data-question-hash={item.question_hash}
      data-format={item.format}
      aria-labelledby={headingId}
      className={styles.question}
    >
      <h2 id={headingId} className="sapling-eyebrow">Knowledge check</h2>
      <PromptText text={item.prompt ?? ""} id={promptId} />
      <AnswerForm
        kind="attempt"
        item={item}
        draft={draft}
        setDraft={setDraft}
        busy={busy}
        promptId={promptId}
        onSubmit={onSubmit}
        onIdk={onIdk}
        aside={
          <SaplingAction
            tone="quiet"
            data-testid="loop-hint-button"
            className={styles.hintButton}
            disabled={hintBusy || busy}
            onClick={onHint}
          >
            {hintBusy ? "Hint…" : hintRetry ? "Retry earned hint" : "Hint"}
          </SaplingAction>
        }
      />
      {hint && "denied" in hint && (
        <div data-testid="loop-hint-denied" data-reason={hint.denied}>
          <StatusMessage tone="info" title="No hint yet">
            {HINT_DENIED_COPY[hint.denied] ?? HINT_DENIED_FALLBACK}
          </StatusMessage>
        </div>
      )}
      {hint && "reply" in hint && (
        <div className={styles.hintBox}>
          <p className="sapling-eyebrow">Hint</p>
          <div data-testid="loop-hint-reply" className={styles.hintText}>{hint.reply}</div>
        </div>
      )}
      <p className={styles.checkNote}>Submit your answer to continue. Chat messages don&apos;t submit a check.</p>
    </section>
  );
}

function ClosePanel({
  close, note, names, courseId,
}: {
  close: LoopCloseResponse | null;
  /** Set when the stored close could not be read (the session was closed elsewhere). */
  note: string | null;
  names: Map<string, string>;
  courseId: string | null;
}) {
  if (!close) {
    if (!note) return <div className={styles.panel}><StatusMessage tone="pending">Wrapping up…</StatusMessage></div>;
    return (
      <div className={styles.panel}>
        <div data-testid="loop-close-done" className={styles.closeDone}>
          <p className={styles.panelLead}>{note}</p>
          <Link data-testid="loop-close-study-link" href="/study?mode=cards" className={styles.textLink}>
            Review what&apos;s due
          </Link>
        </div>
      </div>
    );
  }
  const rec = close.close;
  return (
    <div className={styles.panel}>
      <section aria-labelledby="loop-close-heading" className={styles.closeSection}>
        <h2 id="loop-close-heading" className={styles.panelTitle}>Session wrap-up</h2>
        <p data-testid="loop-close-summary" className={styles.closeSummary}>{rec.summary}</p>
        {rec.concepts.length > 0 && (
          <ul className={styles.closeConcepts}>
            {rec.concepts.map((c) => {
              const dir = c.p_after > c.p_before ? "up" : c.p_after < c.p_before ? "down" : "same";
              return (
                <li key={c.node_id} data-direction={dir}>
                  <span aria-hidden="true" className={styles.closeArrow}>
                    {dir === "up" ? "↑" : dir === "down" ? "↓" : "→"}
                  </span>
                  <span className={styles.closeConceptName}>{names.get(c.node_id) ?? "A concept"}</span>
                  <span className={styles.muted}>
                    {dir === "up" ? "stronger" : dir === "down" ? "worth another look" : "about the same"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      {/* A60: the self-evaluation is a reflection prompt only — nothing is saved. */}
      <div data-testid="loop-close-self-eval" className={styles.reflect}>
        <p className="sapling-eyebrow">Reflect</p>
        <p className={styles.reflectText}>{rec.self_eval}</p>
        <p className={styles.fieldHint}>Take a moment with it — it&apos;s just for you, nothing is saved.</p>
      </div>
      {rec.if_then && (
        <div data-testid="loop-close-if-then" className={styles.ifThen}>
          <p className="sapling-eyebrow">Your plan for next time</p>
          <p className={styles.reflectText}>{rec.if_then}</p>
        </div>
      )}
      <div data-testid="loop-close-done" className={styles.closeDone}>
        <span>Session closed.</span>
        <Link data-testid="loop-close-study-link" href="/study?mode=cards" className={styles.textLink}>
          Review what&apos;s due
        </Link>
        {courseId && (
          <Link
            data-testid="loop-close-retention-link"
            href={`/study?mode=cards&retention-course=${encodeURIComponent(courseId)}`}
            className={styles.textLink}
          >
            Check retention after time away
          </Link>
        )}
      </div>
    </div>
  );
}

const RATING_CHOICES: { value: LoopRating; label: string }[] = [
  { value: "too_easy", label: "Too easy" },
  { value: "appropriate", label: "About right" },
  { value: "too_hard", label: "Too hard" },
];

/** PKG-14 (spec §3.4): "How hard did these feel?" after every
 *  ZPD_RATING_EVERY_N_CHECKS graded checks; the server says when (done.ask_rating).
 *  A perceived-difficulty answer only — never mastery evidence. */
function RatingPrompt({ onRate }: { onRate: (rating: LoopRating) => void }) {
  return (
    <div
      data-testid="loop-rating"
      role="group"
      aria-label="How hard did these questions feel?"
      className={styles.rating}
    >
      <span className={styles.muted}>How hard did these questions feel?</span>
      {RATING_CHOICES.map((c) => (
        <SaplingAction
          key={c.value}
          tone="secondary"
          data-testid={`loop-rating-${c.value}`}
          onClick={() => onRate(c.value)}
        >
          {c.label}
        </SaplingAction>
      ))}
    </div>
  );
}
