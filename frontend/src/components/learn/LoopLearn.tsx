"use client";
// Learning loop (PKG-13): the loop-path Learn screen (build phase: the
// staff/QA toggle; after launch: every student — spec §13 A14). The flow is
// probe → plan → teach ⇄ check → feedback → close, and the phase is
// SERVER-DRIVEN: every change comes from a loop route's response, a stream
// event or a listed session (`reduceLoopEvent` never advances it on its own).
// No model toggle and no tier preference is sent (A15/A26). Resume before probe: a reload
// of /learn never starts a probe while an open loop session exists (§11.3).
// The attempt box grades only through /check/answer/stream, never as a chat
// turn (A16). Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md
// §9, §11.3; routes: backend/routes/learn_loop.py.
import React, { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { TopBar } from "../TopBar";
import { FullHeightScreen } from "../FullHeightScreen";
import { DisclaimerModal } from "../DisclaimerModal";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { ChatPanel, type ChatMsg } from "../chat/ChatPanel";
import { CustomSelect } from "../CustomSelect";
import { KnowledgeGraph } from "../graph/KnowledgeGraph";
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
  listLoopSessions,
  nextLoopCheck,
  nextLoopProbe,
  postLoopAttempt,
  requestLoopHint,
  requestLoopHintTurn,
  resumeSession,
  startLoopSession,
  streamLoopChat,
  streamLoopCheckAnswer,
  type EnrolledCourse,
  type LoopCheckAnswer,
  type LoopCheckItem,
  type LoopCloseResponse,
  type LoopOpenSession,
  type LoopPhase,
  type LoopPlanConcept,
  type LoopProbeItem,
  type LoopTurnResult,
  type StreamChatHandlers,
} from "@/lib/api";
import { BudgetPausedBanner, tutorPauseMessage } from "./BudgetPausedBanner";
import { initialLoopState, reduceLoopEvent } from "./loopState";
import { readResumeParam } from "./resumeParam";

// ── Copy ─────────────────────────────────────────────────────────────────
const NO_CHECK_ITEMS_COPY =
  "No check items for this course yet. You can still learn with the tutor; nothing is graded until the course has items.";
const PLAN_DONE_COPY = "That's every concept in today's plan — close the session when you're ready.";
const NO_ITEM_COPY = "No check is ready for this concept yet — keep going with the tutor.";
const PROBE_UNAVAILABLE_COPY = "Couldn't grade that one — here's another.";
const PROBE_REFUSED_COPY = "Answer in your own words — that read as instructions to the grader.";
const CONTINUE_MESSAGE = "Let's continue.";

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

const BAND_LABEL: Record<string, string> = { novice: "Getting started", develop: "Developing", profic: "Proficient" };
const KIND_LABEL: Record<string, { label: string; chip: string }> = {
  review: { label: "Review", chip: "chip chip--warn" },
  new: { label: "New", chip: "chip chip--accent" },
  sibling: { label: "Related", chip: "chip chip--info" },
};
const STEPS: { label: string; phases: LoopPhase[] }[] = [
  { label: "Check-in", phases: ["probe"] },
  { label: "Plan", phases: ["plan"] },
  { label: "Learn", phases: ["teach", "check", "feedback"] },
  { label: "Wrap-up", phases: ["close"] },
];
const TEACHING: readonly LoopPhase[] = ["teach", "check", "feedback"];
const RAIL_WIDTH = 300;
const RAIL_GRAPH_HEIGHT = 240;

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
const shortDate = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

type Draft = { answer: string; option: string; reason: string };
const EMPTY_DRAFT: Draft = { answer: "", option: "", reason: "" };
type HintView = { denied: string } | { reply: string } | null;

export function LoopLearn() {
  const { userId } = useUser();
  const toast = useToast();
  const searchParams = useSearchParams();
  const isMobile = useIsMobile();
  const [state, dispatch] = useReducer(reduceLoopEvent, undefined, initialLoopState);

  // Course + sessions
  const [courses, setCourses] = useState<EnrolledCourse[] | null>(null);
  const [courseId, setCourseId] = useState<string | null>(null);
  const [openSessions, setOpenSessions] = useState<LoopOpenSession[] | null>(null); // null = loading
  const [sessionsError, setSessionsError] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState<{ id: string; topic: string; messages: ChatMsg[] } | null>(null);
  const [starting, setStarting] = useState(false);

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

  // Teach / check / feedback
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<Draft>(EMPTY_DRAFT);
  const [attemptBusy, setAttemptBusy] = useState(false);
  const [hint, setHint] = useState<HintView>(null);
  const [hintBusy, setHintBusy] = useState(false);
  const [checkNote, setCheckNote] = useState<string | null>(null);
  const [checkBusy, setCheckBusy] = useState(false);

  // Close
  const [close, setClose] = useState<LoopCloseResponse | null>(null);
  const [closeBusy, setCloseBusy] = useState(false);
  const [closeNote, setCloseNote] = useState<string | null>(null);

  // Knowledge map
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({ nodes: [], edges: [] });

  // A session "generation": bumped whenever the screen switches session, so a
  // response for the previous one is dropped instead of landing on the new one.
  const gen = useRef(0);
  const bootKey = useRef<string | null>(null);
  const streamAbort = useRef<AbortController | null>(null);
  const countedAttempt = useRef<string | null>(null); // `${qh}:${text}` the server counted
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      streamAbort.current?.abort();
    };
  }, []);

  const course = useMemo(() => courses?.find((c) => c.course_id === courseId) ?? null, [courses, courseId]);
  const paused = state.budgetPause;
  const item = state.item;

  // ── Error routing: a budget 429 is the banner, never a toast ─────────────
  const reportError = useCallback((err: unknown, fallback: string) => {
    const pause = budgetPauseOf(err);
    if (pause) {
      dispatch({ type: "budget", level: "hard", resetAt: pause.resetAt, sessionCapped: pause.sessionCapped });
      return;
    }
    toast.error(humanizeError(err, fallback));
  }, [toast]);

  // ── Knowledge map ──────────────────────────────────────────────────────
  const refreshGraph = useCallback(async () => {
    if (!userId) return;
    try {
      const g = await getGraph(userId);
      if (!mounted.current) return;
      const nodes = ((g.nodes ?? []) as ApiNode[]).map((n) => apiToGraphNode(n, courses ?? []));
      const edges = ((g.edges ?? []) as ApiEdge[]).map((e) => ({
        source: e.source as string, target: e.target as string, strength: e.strength,
      }));
      setGraph({ nodes, edges });
    } catch {
      // the map is a convenience; the /tree link stays
    }
  }, [userId, courses]);

  // ── Session lifecycle ──────────────────────────────────────────────────
  const clearSessionView = useCallback(() => {
    streamAbort.current?.abort();
    streamAbort.current = null;
    dispatch({ type: "reset" });
    setReadOnly(null);
    setProbeItem(null);
    setProbeDraft(EMPTY_DRAFT);
    setProbeReference(null);
    setProbeNote(null);
    setProbeCount(0);
    setProbeFinished(false);
    setNoCheckItems(false);
    setPlan(null);
    setMessages([]);
    setStreamingText(null);
    setAttempt(EMPTY_DRAFT);
    setHint(null);
    setCheckNote(null);
    setClose(null);
    setCloseNote(null);
    countedAttempt.current = null;
  }, []);

  const loadPlan = useCallback(async (sid: string, g: number) => {
    try {
      const r = await getLoopPlan(sid, userId);
      if (g !== gen.current) return;
      setPlan(r.concepts ?? []);
      if (r.phase) dispatch({ type: "phase", phase: r.phase }); // an empty plan teaches at once
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't load today's plan.");
    }
  }, [userId, reportError]);

  const nextProbe = useCallback(async (sid: string, g: number) => {
    setProbeBusy(true);
    try {
      const r = await nextLoopProbe(sid, userId);
      if (g !== gen.current) return;
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
      if (g === gen.current) reportError(err, "Couldn't load the next question.");
    } finally {
      if (g === gen.current) setProbeBusy(false);
    }
  }, [userId, loadPlan, reportError]);

  /** A resumed check phase restores the open item's pose: /check/next returns
   *  the item being answered unchanged (no write, no model call). */
  const restoreCheck = useCallback(async (sid: string, g: number) => {
    try {
      const r = await nextLoopCheck(sid, userId);
      if (g !== gen.current) return;
      dispatch({ type: "check", item: r.check });
      dispatch({ type: "phase", phase: r.phase });
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't restore the current question.");
    }
  }, [userId, reportError]);

  const resume = useCallback(async (s: LoopOpenSession) => {
    const g = ++gen.current;
    clearSessionView();
    setSessionId(s.session_id);
    dispatch({ type: "phase", phase: s.phase });
    try {
      const r = await resumeSession(s.session_id);
      if (g !== gen.current) return;
      setMessages(toChat(r.messages));
    } catch (err) {
      if (g === gen.current) toast.error(humanizeError(err, "Couldn't load this session's messages."));
    }
    // Continue the phase — never a new session, and no turn is sent (§11.3).
    if (s.phase === "probe") await nextProbe(s.session_id, g);
    else if (s.phase === "plan") await loadPlan(s.session_id, g);
    else if (s.phase === "check") await restoreCheck(s.session_id, g);
  }, [clearSessionView, nextProbe, loadPlan, restoreCheck, toast]);

  const openReadOnly = useCallback(async (id: string) => {
    const g = ++gen.current;
    clearSessionView();
    setSessionId(null);
    try {
      const r = await resumeSession(id);
      if (g !== gen.current) return;
      setReadOnly({ id, topic: r.session?.topic ?? "", messages: toChat(r.messages) });
    } catch {
      // the same retry state as a failed /sessions — never a probe
      if (g === gen.current) setSessionsError(true);
    }
  }, [clearSessionView]);

  const newSession = useCallback(async () => {
    if (!courseId || !userId) return;
    // An explicit start wins over a boot that has not listed the sessions yet.
    bootKey.current = `${userId}:${courseId}`;
    const g = ++gen.current;
    clearSessionView();
    setSessionId(null);
    setStarting(true);
    try {
      const r = await startLoopSession(userId, courseId, course?.course_name ?? "");
      if (g !== gen.current) return;
      setSessionId(r.session_id);
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
          topic: course?.course_name ?? "",
          started_at: new Date().toISOString(),
          phase: "probe",
        };
        return [row, ...list];
      });
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't start a session.");
    } finally {
      if (g === gen.current) setStarting(false);
    }
  }, [courseId, userId, course, clearSessionView, nextProbe, reportError]);

  const loadSessions = useCallback(async () => {
    if (!courseId || !userId) return;
    const g = ++gen.current;
    let list: LoopOpenSession[];
    try {
      list = await listLoopSessions(userId, courseId);
    } catch {
      // never falls through to a new session or a probe (spec §11.3)
      if (g === gen.current) setSessionsError(true);
      return;
    }
    if (g !== gen.current) return;
    setSessionsError(false);
    setOpenSessions(list);
    const wanted = readResumeParam(searchParams);
    const named = wanted ? list.find((s) => s.session_id === wanted) : undefined;
    if (wanted && !named) await openReadOnly(wanted); // a legacy (or closed) session: read-only
    else if (named) await resume(named);
    else if (list.length > 0) await resume(list[0]);
    else await newSession();
  }, [courseId, userId, searchParams, openReadOnly, resume, newSession]);

  const loadCourses = useCallback(async () => {
    if (!userId) return;
    try {
      const r = await getCourses(userId);
      if (!mounted.current) return;
      const list = r.courses ?? [];
      setCourses(list);
      setCourseId((prev) => prev ?? list[0]?.course_id ?? null);
    } catch {
      if (mounted.current) setSessionsError(true);
    }
  }, [userId]);

  // ── Boot: courses → sessions (once per user + course) ───────────────────
  useEffect(() => {
    void loadCourses();
  }, [loadCourses]);

  useEffect(() => {
    if (!userId || !courseId) return;
    const key = `${userId}:${courseId}`;
    if (bootKey.current === key) return; // StrictMode re-runs must not start twice
    bootKey.current = key;
    void loadSessions();
  }, [userId, courseId, loadSessions]);

  useEffect(() => {
    if (courses) void refreshGraph();
  }, [courses, refreshGraph]);

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
      if (r.graded) {
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

  // ── Plan ───────────────────────────────────────────────────────────────
  const approvePlan = async () => {
    if (!sessionId || !plan || plan.length === 0 || planBusy) return;
    const g = gen.current;
    setPlanBusy(true);
    try {
      const r = await approveLoopPlan(sessionId, userId, plan.map((c) => c.node_id));
      if (g === gen.current) dispatch({ type: "phase", phase: r.phase });
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't save the plan.");
    } finally {
      if (g === gen.current) setPlanBusy(false);
    }
  };

  // ── Streamed turns (chat + explicit submissions) ─────────────────────────
  const applyActivated = useCallback((check: LoopCheckItem | null | undefined) => {
    if (!check) return;
    dispatch({ type: "check", item: check });
    // the server stores the pose as an assistant row too, so a reload shows it
    const pose = check.prompt;
    if (pose) setMessages((prev) => [...prev, asMsg("assistant", pose)]);
    setAttempt(EMPTY_DRAFT);
    setHint(null);
    setCheckNote(null);
  }, []);

  const runTurn = useCallback(async (
    run: (h: StreamChatHandlers) => Promise<LoopTurnResult>,
    { submission = false }: { submission?: boolean } = {},
  ): Promise<LoopTurnResult | null> => {
    streamAbort.current?.abort();
    const controller = new AbortController();
    streamAbort.current = controller;
    const g = gen.current;
    let streamed = "";
    let hardSeen = false;
    setStreamingText("");
    const handlers: StreamChatHandlers = {
      signal: controller.signal,
      onToken: (d) => {
        streamed += d;
        setStreamingText(streamed);
      },
      // A46: discard every token streamed so far; the current text follows
      onRetract: () => {
        streamed = "";
        setStreamingText("");
      },
      onPhase: (p) => dispatch({ type: "phase", phase: p }),
      onCheck: (c) => dispatch({ type: "check", item: c }),
      onHintOffer: (rung) => dispatch({ type: "hint_offer", rung }),
      onLearnerState: (s) => dispatch({ type: "learner_state", state: s }),
      onBudget: (b) => {
        if (b.level === "hard") hardSeen = true;
        dispatch({ type: "budget", level: b.level, resetAt: b.reset_at, sessionCapped: b.session_capped });
      },
    };
    try {
      const res = await run(handlers);
      if (g !== gen.current || streamAbort.current !== controller) return null;
      // done.reply is always the final, leak-stripped text (A46) — never the tokens
      const text = res.reply ?? streamed;
      if (text) setMessages((prev) => [...prev, asMsg("assistant", text)]);
      dispatch({ type: "done", leakRedacted: res.leak_redacted === true });
      if (submission && res.graded && !res.unavailable && !res.refused) {
        dispatch({ type: "check", item: null }); // graded: the item is closed
        setAttempt(EMPTY_DRAFT);
        setHint(null);
      }
      applyActivated(res.check);
      if (res.phase) dispatch({ type: "phase", phase: res.phase });
      if (res.budget?.level === "hard") {
        dispatch({ type: "budget", level: "hard", resetAt: res.budget.reset_at, sessionCapped: res.budget.session_capped });
      } else if (!hardSeen) {
        dispatch({ type: "budget_clear" }); // a tutor turn got through
      }
      return res;
    } catch (err) {
      if (g !== gen.current) return null;
      if (streamed) setMessages((prev) => [...prev, { ...asMsg("assistant", streamed), interrupted: true }]);
      if (controller.signal.aborted) return null;
      // At the hard level the stream ends with no `done`: that is the pause, not an error.
      if (hardSeen) return null;
      reportError(err, "The tutor couldn't answer. Try again.");
      return null;
    } finally {
      if (streamAbort.current === controller) {
        streamAbort.current = null;
        setStreamingText(null);
      }
    }
  }, [applyActivated, reportError]);

  const send = (text: string) => {
    if (!sessionId || paused) return;
    setMessages((prev) => [...prev, asMsg("user", text)]);
    void runTurn((h) => streamLoopChat(sessionId, userId, text, h));
  };

  const stop = () => streamAbort.current?.abort();

  const submitAttempt = async (idk: boolean) => {
    if (!sessionId || !item || attemptBusy) return;
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
    if (mounted.current) setAttemptBusy(false);
    if (res?.graded) void refreshGraph();
  };

  const askHint = async () => {
    if (!sessionId || !item || hintBusy) return;
    const g = gen.current;
    const qh = item.question_hash;
    setHintBusy(true);
    setHint(null);
    dispatch({ type: "hint_taken" });
    try {
      // The draft is the student's work: record it as an attempt first so the
      // hint gate can see it (judged for the gate only; never stored or graded).
      const draft = (item.format === "mc_reason"
        ? [attempt.option, attempt.reason].filter(Boolean).join(" — ")
        : attempt.answer).trim();
      if (draft && countedAttempt.current !== `${qh}:${draft}`) {
        const recorded = await postLoopAttempt(sessionId, userId, qh, draft);
        if (recorded.counted) countedAttempt.current = `${qh}:${draft}`;
      }
      const r = await requestLoopHint(sessionId, userId, qh);
      if (g !== gen.current) return;
      if (r.denied) {
        setHint({ denied: r.denied });
        return;
      }
      const t = await requestLoopHintTurn(sessionId, userId);
      if (g !== gen.current) return;
      setHint({ reply: t.reply });
      setMessages((prev) => [...prev, asMsg("assistant", t.reply)]);
      if (t.phase) dispatch({ type: "phase", phase: t.phase });
      if (t.budget?.level === "hard") {
        dispatch({ type: "budget", level: "hard", resetAt: t.budget.reset_at, sessionCapped: t.budget.session_capped });
      }
    } catch (err) {
      if (g === gen.current) reportError(err, "Couldn't get a hint.");
    } finally {
      if (g === gen.current) setHintBusy(false);
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
      if (r.check) applyActivated(r.check);
      else setCheckNote(r.plan_done ? PLAN_DONE_COPY : NO_ITEM_COPY);
      dispatch({ type: "phase", phase: r.phase });
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
      if (g !== gen.current) return;
      streamAbort.current?.abort();
      setClose(r);
      dispatch({ type: "check", item: null });
      dispatch({ type: "phase", phase: "close" });
      setOpenSessions((prev) => (prev ?? []).filter((s) => s.session_id !== sid));
      void refreshGraph();
    } catch (err) {
      if (g !== gen.current) return;
      const { status, detail } = extractErrorDetail(err);
      if (status === 409 && detail) {
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
    for (const n of graph.nodes) names.set(n.id, n.name);
    for (const c of plan ?? []) if (c.concept_name) names.set(c.node_id, c.concept_name);
    return names;
  }, [graph.nodes, plan]);
  const railGraph = useMemo(() => {
    const nodes = graph.nodes.filter((n) => n.course_id === courseId);
    if (nodes.length === 0) return graph;
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: graph.edges.filter((e) => ids.has(e.source as string) && ids.has(e.target as string)) };
  }, [graph, courseId]);
  const focusNodeId = state.focusNodeId;
  const learner = focusNodeId ? state.learnerState[focusNodeId] : undefined;
  const treeHref = focusNodeId ? `/tree?node=${encodeURIComponent(focusNodeId)}` : "/tree";
  const teaching = TEACHING.includes(state.phase);
  const stepIndex = STEPS.findIndex((s) => s.phases.includes(state.phase));
  const streaming = streamingText !== null;

  // ── Render ─────────────────────────────────────────────────────────────
  const noCourses = courses !== null && courses.length === 0;
  const loadingSessions =
    !sessionsError && !noCourses && !readOnly && (openSessions === null || (!sessionId && starting));

  const header = (
    <TopBar
      title={course ? course.course_name : "Learn"}
      subtitle={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {course?.course_code && <span>{course.course_code} ·</span>}
          {STEPS.map((s, i) => (
            <span
              key={s.label}
              aria-current={i === stepIndex ? "step" : undefined}
              style={{
                color: i === stepIndex ? "var(--accent)" : i < stepIndex ? "var(--text-dim)" : "var(--text-muted)",
                fontWeight: i === stepIndex ? 600 : 400,
              }}
            >
              {i > 0 && <span aria-hidden style={{ color: "var(--text-muted)", marginRight: 6 }}>›</span>}
              {s.label}
            </span>
          ))}
        </span>
      }
      actions={
        <>
          {courses && courses.length > 1 && (
            <CustomSelect<string>
              value={courseId ?? ""}
              options={courses.map((c) => ({ value: c.course_id, label: c.course_code || c.course_name }))}
              onChange={(v) => setCourseId(v)}
              ariaLabel="Course"
              size="sm"
            />
          )}
          <Link data-testid="loop-tree-link" href={treeHref} className="btn btn--sm btn--ghost">
            Knowledge map
          </Link>
          {teaching && sessionId && (
            <button
              data-testid="loop-close-button"
              className="btn btn--sm"
              onClick={() => void doClose()}
              disabled={closeBusy}
              title="Wrap up this session"
            >
              {closeBusy ? "Closing…" : "End session"}
            </button>
          )}
          <AIDisclaimerChip />
        </>
      }
    />
  );

  const sessionStrip = (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "10px 32px",
        borderBottom: "1px solid var(--border)",
        overflowX: "auto",
      }}
    >
      <span className="label-micro" style={{ flexShrink: 0 }}>Open sessions</span>
      <div data-testid="loop-session-picker" role="list" style={{ display: "flex", gap: 6, flex: 1, minWidth: 0 }}>
        {(openSessions ?? []).map((s) => {
          const current = s.session_id === sessionId;
          return (
            <div role="listitem" key={s.session_id} style={{ flexShrink: 0 }}>
              <button
                data-testid={`loop-session-${s.session_id}`}
                aria-current={current ? "true" : undefined}
                className={current ? "chip chip--accent" : "chip"}
                style={{ cursor: current ? "default" : "pointer", whiteSpace: "nowrap" }}
                onClick={() => { if (!current) void resume(s); }}
                title={current ? "Current session" : `Resume “${s.topic}”`}
              >
                {s.topic || "Session"}
                <span style={{ color: "var(--text-muted)", marginLeft: 6 }}>{shortDate(s.started_at)}</span>
              </button>
            </div>
          );
        })}
        {openSessions !== null && openSessions.length === 0 && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>None yet</span>
        )}
      </div>
      <button
        data-testid="loop-new-session"
        className="btn btn--sm"
        style={{ flexShrink: 0 }}
        onClick={() => void newSession()}
        disabled={!courseId || starting}
      >
        + New session
      </button>
    </div>
  );

  const notices = (paused || noCheckItems) && (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: "12px 32px 0" }}>
      {paused && (
        <BudgetPausedBanner
          testId="loop-budget-paused"
          resetAt={paused.resetAt}
          sessionCapped={paused.sessionCapped}
          message={tutorPauseMessage(paused.resetAt, paused.sessionCapped)}
        >
          {" "}
          <Link
            data-testid="loop-budget-study-link"
            href="/study?mode=cards"
            style={{ color: "var(--accent)", fontWeight: 500 }}
          >
            Review flashcards
          </Link>
        </BudgetPausedBanner>
      )}
      {noCheckItems && (
        <div
          data-testid="loop-no-check-items"
          role="status"
          style={{ padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--info-soft)", fontSize: 13 }}
        >
          {NO_CHECK_ITEMS_COPY}
        </div>
      )}
    </div>
  );

  const learnerChip = (
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

  let body: React.ReactNode;
  if (sessionsError) {
    body = (
      <CenteredCard testId="loop-sessions-error">
        <div className="h-serif" style={{ fontSize: 20, marginBottom: 6 }}>Couldn&apos;t load your sessions</div>
        <p style={{ color: "var(--text-dim)", fontSize: 14, margin: "0 0 16px" }}>
          Nothing was started. Try again to pick up where you left off.
        </p>
        <button data-testid="loop-sessions-retry" className="btn btn--primary" onClick={retrySessions}>
          Retry
        </button>
      </CenteredCard>
    );
  } else if (noCourses) {
    body = (
      <CenteredCard testId="loop-no-course">
        <div className="h-serif" style={{ fontSize: 20, marginBottom: 6 }}>Add a course to start learning</div>
        <p style={{ color: "var(--text-dim)", fontSize: 14, margin: 0 }}>
          The tutor works course by course — add one from your <Link href="/tree">knowledge map</Link>.
        </p>
      </CenteredCard>
    );
  } else if (readOnly) {
    body = (
      <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px" }}>
        <div style={{ maxWidth: 720, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span className="chip">Read-only</span>
            <span style={{ fontSize: 14, color: "var(--text-dim)" }}>
              {readOnly.topic ? `“${readOnly.topic}” — ` : ""}an earlier session. Start a new one to keep learning.
            </span>
            <div style={{ flex: 1 }} />
            <button
              data-testid="loop-readonly-new-session"
              className="btn btn--primary btn--sm"
              onClick={() => void newSession()}
            >
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
  } else if (loadingSessions) {
    body = <div style={{ padding: 40, color: "var(--text-dim)" }}>{starting ? "Starting your session…" : "Loading…"}</div>;
  } else if (state.phase === "probe") {
    body = (
      <ProbePanel
        item={probeItem}
        count={probeCount}
        draft={probeDraft}
        setDraft={setProbeDraft}
        reference={probeReference}
        note={probeNote}
        busy={probeBusy}
        greeting={messages.find((m) => m.role === "assistant")?.content ?? null}
        onSubmit={() => void submitProbe(false)}
        onIdk={() => void submitProbe(true)}
        onNext={() => void advanceProbe(probeFinished, gen.current)}
      />
    );
  } else if (state.phase === "plan") {
    body = <PlanPanel plan={plan} busy={planBusy} onApprove={() => void approvePlan()} />;
  } else if (state.phase === "close") {
    body = <ClosePanel close={close} names={conceptNames} />;
  } else {
    const firstConcept = plan?.[0];
    const chatHeader = (
      <div style={{ padding: "14px 32px 0", display: "flex", flexDirection: "column", gap: 10 }}>
        {item ? (
          <CheckCard
            item={item}
            draft={attempt}
            setDraft={setAttempt}
            busy={attemptBusy || streaming}
            hint={hint}
            hintBusy={hintBusy}
            hintOffer={state.hintOffer}
            onSubmit={() => void submitAttempt(false)}
            onIdk={() => void submitAttempt(true)}
            onHint={() => void askHint()}
          />
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            {state.phase === "feedback" && (
              <button
                data-testid="loop-continue"
                className="btn btn--sm btn--primary"
                onClick={() => send(CONTINUE_MESSAGE)}
                disabled={!!paused || streaming}
              >
                Continue
              </button>
            )}
            <button
              data-testid="loop-check-me"
              className="btn btn--sm"
              onClick={() => void checkMe()}
              disabled={checkBusy || streaming}
              title="Get a question on this concept"
            >
              Check me
            </button>
            {messages.length <= 1 && firstConcept && state.phase === "teach" && !paused && (
              <button
                data-testid="loop-teach-start"
                className="btn btn--sm btn--ghost"
                onClick={() => send(`Teach me about ${firstConcept.concept_name}.`)}
                disabled={streaming}
              >
                Start with {firstConcept.concept_name}
              </button>
            )}
            {checkNote && <span role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{checkNote}</span>}
          </div>
        )}
        {closeNote && <div role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{closeNote}</div>}
      </div>
    );
    body = (
      <div data-testid="loop-messages" style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <ChatPanel
          messages={messages}
          onSend={send}
          header={chatHeader}
          streamingText={streamingText}
          onStop={stop}
          disabled={!!paused}
          placeholder={paused ? "Tutor chat is paused — check answers still count." : "Ask the tutor…"}
        />
      </div>
    );
  }

  const showRail = !isMobile && !sessionsError && !noCourses;

  return (
    <FullHeightScreen>
      <DisclaimerModal />
      <div
        data-testid="loop-phase"
        data-phase={state.phase}
        data-session-id={sessionId ?? ""}
        style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}
      >
        {header}
        {sessionStrip}
        {notices}
        <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
          <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 32px 0" }}>
              {learnerChip}
            </div>
            {body}
          </div>
          {showRail && (
            <aside
              data-testid="loop-rail"
              aria-label="Knowledge map"
              style={{
                width: RAIL_WIDTH,
                flexShrink: 0,
                borderLeft: "1px solid var(--border)",
                background: "var(--bg-subtle)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
                padding: 14,
                overflowY: "auto",
              }}
            >
              <div className="label-micro">Knowledge map</div>
              {railGraph.nodes.length > 0 ? (
                <RailGraph nodes={railGraph.nodes} edges={railGraph.edges} highlightId={focusNodeId ?? undefined} />
              ) : (
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Concepts appear here as you learn.</div>
              )}
            </aside>
          )}
        </div>
      </div>
    </FullHeightScreen>
  );
}

// ── Pieces ─────────────────────────────────────────────────────────────────

function CenteredCard({ testId, children }: { testId: string; children: React.ReactNode }) {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 32 }}>
      <div data-testid={testId} className="card" style={{ maxWidth: 520, margin: "24px auto", padding: "var(--pad-xl)" }}>
        {children}
      </div>
    </div>
  );
}

/** The knowledge-map rail: `KnowledgeGraph` fed as Learn.tsx's
 *  SidebarKnowledgeGraph feeds it (measured width, fixed height). */
function RailGraph({ nodes, edges, highlightId }: { nodes: GraphNode[]; edges: GraphEdge[]; highlightId?: string }) {
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
    <div ref={ref} style={{ width: "100%" }}>
      {width > 0 && (
        <KnowledgeGraph nodes={nodes} edges={edges} width={width} height={RAIL_GRAPH_HEIGHT} highlightId={highlightId} />
      )}
    </div>
  );
}

function OptionList({
  options,
  selected,
  onSelect,
  testIdPrefix,
  disabled,
}: {
  options: { letter: string; text: string }[];
  selected: string;
  onSelect: (letter: string) => void;
  testIdPrefix: string;
  disabled?: boolean;
}) {
  // Served options in stored order; the UI never marks one correct (A22).
  return (
    <div role="radiogroup" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {options.map((o) => {
        const on = selected === o.letter;
        return (
          <button
            key={o.letter}
            type="button"
            role="radio"
            aria-checked={on}
            data-testid={`${testIdPrefix}-${o.letter}`}
            disabled={disabled}
            onClick={() => onSelect(o.letter)}
            style={{
              display: "flex",
              gap: 10,
              alignItems: "flex-start",
              textAlign: "left",
              padding: "9px 12px",
              borderRadius: "var(--r-md)",
              border: `1px solid ${on ? "var(--accent-border)" : "var(--border)"}`,
              background: on ? "var(--accent-soft)" : "var(--bg-panel)",
              fontSize: 14,
              cursor: disabled ? "default" : "pointer",
              color: "var(--text)",
            }}
          >
            <strong style={{ minWidth: 16 }}>{o.letter}</strong>
            <span>{o.text}</span>
          </button>
        );
      })}
    </div>
  );
}

function ProbePanel({
  item, count, draft, setDraft, reference, note, busy, greeting, onSubmit, onIdk, onNext,
}: {
  item: LoopProbeItem | null;
  count: number;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  reference: string | null;
  note: string | null;
  busy: boolean;
  /** The session opener (model-written, or the hard-level template, A27). */
  greeting: string | null;
  onSubmit: () => void;
  onIdk: () => void;
  onNext: () => void;
}) {
  const mc = item?.format === "mc_reason";
  const canSubmit = !!item && !busy && (mc ? draft.option !== "" : draft.answer.trim() !== "");
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px 32px" }}>
      <div style={{ maxWidth: 640, margin: "0 auto", display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <div className="h-serif" style={{ fontSize: 22 }}>Quick check-in</div>
          <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--text-dim)" }}>
            A few questions so the tutor knows where to start. Answer what you can — &ldquo;I don&apos;t know&rdquo; is a
            fine answer.
          </p>
        </div>
        {greeting && (
          <div
            style={{
              fontSize: 14,
              lineHeight: 1.5,
              padding: "10px 14px",
              borderRadius: "var(--r-md)",
              background: "var(--bg-soft)",
              whiteSpace: "pre-wrap",
            }}
          >
            <div className="label-micro" style={{ marginBottom: 2 }}>Tutor</div>
            {greeting}
          </div>
        )}
        {!item && busy && <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Loading the next question…</div>}
        {item && (
          <div
            data-testid="loop-probe-item"
            data-question-hash={item.question_hash}
            className="card"
            style={{ padding: "var(--pad-xl)", display: "flex", flexDirection: "column", gap: 12 }}
          >
            <div className="label-micro">Question {count + (reference === null ? 1 : 0)}</div>
            <div style={{ fontSize: 16, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{item.prompt}</div>
            {reference === null ? (
              <>
                {mc ? (
                  <>
                    <OptionList
                      options={item.options ?? []}
                      selected={draft.option}
                      onSelect={(letter) => setDraft((d) => ({ ...d, option: letter }))}
                      testIdPrefix="loop-probe-option"
                      disabled={busy}
                    />
                    <input
                      data-testid="loop-probe-reason"
                      style={FIELD_STYLE}
                      placeholder="In one sentence: why?"
                      value={draft.reason}
                      disabled={busy}
                      onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))}
                    />
                  </>
                ) : (
                  <textarea
                    data-testid="loop-probe-input"
                    style={FIELD_STYLE}
                    rows={3}
                    placeholder={item.format === "teachback" ? "Explain it in your own words" : "Your answer"}
                    value={draft.answer}
                    disabled={busy}
                    onChange={(e) => setDraft((d) => ({ ...d, answer: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) onSubmit();
                    }}
                  />
                )}
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button data-testid="loop-probe-submit" className="btn btn--primary" disabled={!canSubmit} onClick={onSubmit}>
                    {busy ? "Checking…" : "Submit"}
                  </button>
                  <button data-testid="loop-probe-idk" className="btn btn--ghost" disabled={busy} onClick={onIdk}>
                    I don&apos;t know
                  </button>
                </div>
              </>
            ) : (
              <>
                <div
                  data-testid="loop-probe-reference"
                  style={{
                    padding: "10px 14px",
                    borderRadius: "var(--r-md)",
                    background: "var(--bg-soft)",
                    fontSize: 14,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  <div className="label-micro" style={{ marginBottom: 4 }}>Here&apos;s the answer</div>
                  {reference}
                </div>
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
          </div>
        )}
        {note && <div role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{note}</div>}
      </div>
    </div>
  );
}

function PlanPanel({ plan, busy, onApprove }: { plan: LoopPlanConcept[] | null; busy: boolean; onApprove: () => void }) {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px 32px" }}>
      <div
        className="card"
        style={{ maxWidth: 640, margin: "0 auto", padding: "var(--pad-xl)", display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div>
          <div className="h-serif" style={{ fontSize: 22 }}>Today&apos;s plan</div>
          <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--text-dim)" }}>
            Built from your check-in: anything due for review first, then what&apos;s next to learn.
          </p>
        </div>
        {plan === null && <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Building your plan…</div>}
        {plan !== null && plan.length === 0 && (
          <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Nothing to plan right now — ask the tutor anything.</div>
        )}
        {plan && plan.length > 0 && (
          <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            {plan.map((c, i) => {
              const kind = KIND_LABEL[c.kind];
              return (
                <li
                  key={c.node_id}
                  data-testid={`loop-plan-concept-${c.node_id}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 12px",
                    borderRadius: "var(--r-md)",
                    background: "var(--bg-soft)",
                  }}
                >
                  <span style={{ width: 22, color: "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>{i + 1}</span>
                  <span style={{ flex: 1, fontSize: 14, fontWeight: 500 }}>{c.concept_name || "Concept"}</span>
                  {c.band && <span className="chip">{BAND_LABEL[c.band] ?? c.band}</span>}
                  {kind && <span className={kind.chip}>{kind.label}</span>}
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
            {busy ? "Saving…" : "Start learning"}
          </button>
        )}
      </div>
    </div>
  );
}

function CheckCard({
  item, draft, setDraft, busy, hint, hintBusy, hintOffer, onSubmit, onIdk, onHint,
}: {
  item: LoopCheckItem;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  busy: boolean;
  hint: HintView;
  hintBusy: boolean;
  hintOffer: number | null;
  onSubmit: () => void;
  onIdk: () => void;
  onHint: () => void;
}) {
  const mc = item.format === "mc_reason";
  const canSubmit = !busy && (mc ? draft.option !== "" : draft.answer.trim() !== "");
  return (
    <div
      className="card"
      style={{ padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10, borderColor: "var(--accent-border)" }}
    >
      <div
        data-testid="loop-check-prompt"
        data-question-hash={item.question_hash}
        data-format={item.format}
        style={{ display: "flex", flexDirection: "column", gap: 4 }}
      >
        <div className="label-micro">Check your understanding</div>
        <div style={{ fontSize: 15, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{item.prompt ?? ""}</div>
      </div>
      {mc ? (
        <>
          <OptionList
            options={item.options ?? []}
            selected={draft.option}
            onSelect={(letter) => setDraft((d) => ({ ...d, option: letter }))}
            testIdPrefix="loop-attempt-option"
            disabled={busy}
          />
          <input
            data-testid="loop-attempt-reason"
            style={FIELD_STYLE}
            placeholder="In one sentence: why?"
            value={draft.reason}
            disabled={busy}
            onChange={(e) => setDraft((d) => ({ ...d, reason: e.target.value }))}
          />
        </>
      ) : (
        <textarea
          data-testid="loop-attempt-input"
          style={FIELD_STYLE}
          rows={2}
          placeholder={item.format === "teachback" ? "Explain it in your own words" : "Your answer — this is what gets checked"}
          value={draft.answer}
          disabled={busy}
          onChange={(e) => setDraft((d) => ({ ...d, answer: e.target.value }))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) onSubmit();
          }}
        />
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button data-testid="loop-attempt-submit" className="btn btn--sm btn--primary" disabled={!canSubmit} onClick={onSubmit}>
          Submit answer
        </button>
        <button data-testid="loop-attempt-idk" className="btn btn--sm btn--ghost" disabled={busy} onClick={onIdk}>
          I don&apos;t know
        </button>
        <div style={{ flex: 1 }} />
        {hintOffer !== null && (
          <button data-testid="loop-hint-offer" className="btn btn--sm btn--ghost" disabled={hintBusy || busy} onClick={onHint}>
            Want a hint?
          </button>
        )}
        <button data-testid="loop-hint-button" className="btn btn--sm" disabled={hintBusy || busy} onClick={onHint}>
          {hintBusy ? "Hint…" : "Hint"}
        </button>
      </div>
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
      {hint && "reply" in hint && (
        <div
          data-testid="loop-hint-reply"
          style={{
            fontSize: 14,
            padding: "8px 12px",
            borderRadius: "var(--r-md)",
            background: "var(--info-soft)",
            whiteSpace: "pre-wrap",
          }}
        >
          {hint.reply}
        </div>
      )}
    </div>
  );
}

function ClosePanel({ close, names }: { close: LoopCloseResponse | null; names: Map<string, string> }) {
  if (!close) return <div style={{ padding: 40, color: "var(--text-dim)" }}>Wrapping up…</div>;
  const rec = close.close;
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px 32px" }}>
      <div
        className="card"
        style={{ maxWidth: 640, margin: "0 auto", padding: "var(--pad-xl)", display: "flex", flexDirection: "column", gap: 16 }}
      >
        <div className="h-serif" style={{ fontSize: 22 }}>Session wrap-up</div>
        <p data-testid="loop-close-summary" style={{ margin: 0, fontSize: 15, lineHeight: 1.55, whiteSpace: "pre-wrap" }}>
          {rec.summary}
        </p>
        {rec.concepts.length > 0 && (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}>
            {rec.concepts.map((c) => {
              const dir = c.p_after > c.p_before ? "up" : c.p_after < c.p_before ? "down" : "same";
              return (
                <li key={c.node_id} style={{ display: "flex", gap: 8, fontSize: 14 }}>
                  <span aria-hidden style={{ color: dir === "up" ? "var(--accent)" : "var(--text-muted)" }}>
                    {dir === "up" ? "↑" : dir === "down" ? "↓" : "→"}
                  </span>
                  <span>{names.get(c.node_id) ?? "A concept"}</span>
                  <span style={{ color: "var(--text-muted)" }}>
                    {dir === "up" ? "stronger" : dir === "down" ? "worth another look" : "about the same"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {/* A60: the self-evaluation is a reflection prompt only — nothing is saved. */}
        <div
          data-testid="loop-close-self-eval"
          style={{ padding: "12px 14px", borderRadius: "var(--r-md)", background: "var(--bg-soft)" }}
        >
          <div className="label-micro" style={{ marginBottom: 4 }}>Reflect</div>
          <div style={{ fontSize: 15, fontStyle: "italic" }}>{rec.self_eval}</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 6 }}>
            Take a moment with it — it&apos;s just for you, nothing is saved.
          </div>
        </div>
        {rec.if_then && (
          <div
            data-testid="loop-close-if-then"
            style={{ padding: "12px 14px", borderRadius: "var(--r-md)", background: "var(--accent-soft)" }}
          >
            <div className="label-micro" style={{ marginBottom: 4 }}>Your plan for next time</div>
            <div style={{ fontSize: 15 }}>{rec.if_then}</div>
          </div>
        )}
        <div
          data-testid="loop-close-done"
          style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 14, color: "var(--text-dim)" }}
        >
          <span>Session closed.</span>
          <Link href="/study?mode=cards" style={{ color: "var(--accent)" }}>Review what&apos;s due</Link>
        </div>
      </div>
    </div>
  );
}
