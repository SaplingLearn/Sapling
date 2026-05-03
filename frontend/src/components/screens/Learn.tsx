"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { TopBar } from "../TopBar";
import { Icon } from "../Icon";
import { CustomSelect } from "../CustomSelect";
import { ChatPanel, type ChatMsg } from "../ChatPanel";
import { SessionSummary } from "../SessionSummary";
import { SharedContextToggle, useSharedContext } from "../SharedContextToggle";
import { DisclaimerModal } from "../DisclaimerModal";
import { AIDisclaimerChip } from "../AIDisclaimerChip";
import { QuizPanel } from "../QuizPanel";
import { KnowledgeGraph } from "../KnowledgeGraph";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useIsMobile } from "@/lib/useIsMobile";
import { useUser } from "@/context/UserContext";
import {
  startSession,
  sendChat,
  getSessions,
  resumeSession,
  deleteSession,
  endSession,
  switchMode,
  learnAction,
  getCourses,
  getGraph,
  type Session,
  type SessionSummaryData,
  type EnrolledCourse,
} from "@/lib/api";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "@/lib/types";
import type { GraphNode, GraphEdge } from "@/lib/data";

function apiToGraphNode(n: ApiNode, courses: EnrolledCourse[]): GraphNode {
  const course = courses.find((c) => c.course_name === n.subject);
  return {
    id: n.id,
    name: n.concept_name,
    subject: n.subject,
    color: n.course_color || course?.color || "var(--c-sage)",
    is_subject_root: n.is_subject_root,
    mastery_tier: n.mastery_tier === "subject_root" ? "mastered" : n.mastery_tier,
    mastery_score: n.mastery_score,
    course_id: n.course_id || course?.course_id || "",
    last_studied_at: n.last_studied_at || undefined,
  };
}

function apiToGraphEdge(e: ApiEdge): GraphEdge {
  return { source: e.source as string, target: e.target as string, strength: e.strength };
}

type Mode = "socratic" | "expository" | "teachback" | "quiz";

const MODES: { id: Mode; name: string; tip: string }[] = [
  { id: "socratic", name: "Socratic", tip: "Asks guiding questions" },
  { id: "expository", name: "Expository", tip: "Explains directly" },
  { id: "teachback", name: "Teach-back", tip: "You teach, AI listens" },
  { id: "quiz", name: "Quiz", tip: "Rapid recall checks" },
];

const VALID_MODES: Mode[] = ["socratic", "expository", "teachback", "quiz"];
const CHAT_MODES: Mode[] = ["socratic", "expository", "teachback"];
const SESSION_END_COUNT_KEY = "sapling_session_end_count";
const LAST_SESSION_CTX_KEY = "sapling_last_session_context";

function normalizeMode(input: string | null): Mode {
  if (!input) return "socratic";
  return (VALID_MODES as string[]).includes(input) ? (input as Mode) : "socratic";
}

export function Learn() {
  return (
    <Suspense fallback={<div style={{ padding: 40, color: "var(--text-dim)" }}>Loading…</div>}>
      <LearnInner />
    </Suspense>
  );
}

function LearnInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { userId, userReady } = useUser();
  const toast = useToast();
  const isMobile = useIsMobile();

  const [sharedCtx, setSharedCtx] = useSharedContext();

  const initialTopic = searchParams.get("topic") ?? "";
  const initialMode = normalizeMode(searchParams.get("mode"));

  const [mode, setMode] = useState<Mode>(initialMode);
  const [topic, setTopic] = useState<string>(initialTopic);
  const [topicDraft, setTopicDraft] = useState<string>(initialTopic);
  const [selectedCourseId, setSelectedCourseId] = useState<string | "">("");

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [sending, setSending] = useState(false);
  const [starting, setStarting] = useState(false);

  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [concepts, setConcepts] = useState<{ id: string; name: string; course_id: string | null; course_code: string | null }[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);

  const [summary, setSummary] = useState<SessionSummaryData | null>(null);
  const [mobileTab, setMobileTab] = useState<"chat" | "graph">("chat");
  const idCounter = useRef(0);
  const msgId = () => `m-${++idCounter.current}`;

  // Initial data load
  useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        const [sRes, cRes, gRes] = await Promise.all([
          getSessions(userId, 10).catch(() => ({ sessions: [] })),
          getCourses(userId).catch(() => ({ courses: [] })),
          getGraph(userId).catch(() => ({ nodes: [] as any[], edges: [] as any[], stats: {} })),
        ]);
        if (cancelled) return;
        setRecentSessions((sRes.sessions ?? []).filter(s => s.message_count > 0));
        setCourses(cRes.courses ?? []);
        const nodes = (gRes.nodes ?? []) as Array<{ id: string; concept_name?: string; name?: string; course_id?: string | null; is_subject_root?: boolean }>;
        const courseById = new Map((cRes.courses ?? []).map(c => [c.course_id, c]));
        setConcepts(
          nodes
            .filter(n => !n.is_subject_root)
            .map(n => ({
              id: n.id,
              name: n.concept_name || n.name || "Concept",
              course_id: n.course_id ?? null,
              course_code: n.course_id ? (courseById.get(n.course_id)?.course_code ?? null) : null,
            })),
        );
        const apiNodes = (gRes.nodes ?? []) as ApiNode[];
        const apiEdges = (gRes.edges ?? []) as ApiEdge[];
        setGraphNodes(apiNodes.map(n => apiToGraphNode(n, cRes.courses ?? [])));
        setGraphEdges(apiEdges.map(apiToGraphEdge));
      } catch (err) {
        console.error("learn bootstrap failed", err);
      }
    })();
    return () => { cancelled = true; };
  }, [userReady, userId]);

  // Sync URL params when mode changes (preserve other params)
  useEffect(() => {
    const current = searchParams.get("mode");
    if (current === mode) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("mode", mode);
    router.replace(`/learn?${params.toString()}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const handleStart = async () => {
    const t = topicDraft.trim();
    if (!t || !userId) return;
    if (mode === "quiz") {
      setTopic(t);
      return; // QuizPanel handles its own flow
    }
    setTopic(t);
    setMessages([{ id: msgId(), role: "assistant", content: "", loading: true }]);
    setStarting(true);
    try {
      const res = await startSession(userId, t, mode, selectedCourseId || undefined, sharedCtx);
      setSessionId(res.session_id);
      setMessages([{ id: msgId(), role: "assistant", content: res.initial_message || "Let's begin." }]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't start session.");
      setMessages([]);
    } finally {
      setStarting(false);
    }
  };

  const handleResume = async (s: Session) => {
    try {
      const res = await resumeSession(s.id);
      setSessionId(s.id);
      setTopic(s.topic);
      setMode(normalizeMode(s.mode));
      setMessages(
        (res.messages ?? []).map(m => ({
          id: msgId(),
          role: m.role === "user" ? "user" : "assistant",
          content: m.content,
        })),
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Resume failed.");
    }
  };

  const handleDeleteSession = async (s: Session) => {
    if (!userId) return;
    try {
      await deleteSession(s.id, userId);
      setRecentSessions(prev => prev.filter(p => p.id !== s.id));
      toast.success("Session deleted.");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed.");
    }
  };

  const send = useCallback(async (userText: string) => {
    if (!userText.trim() || !sessionId || !userId) return;
    const chatMode = CHAT_MODES.includes(mode) ? mode : "socratic";
    setMessages(m => [
      ...m,
      { id: msgId(), role: "user", content: userText },
      { id: msgId(), role: "assistant", content: "", loading: true },
    ]);
    setSending(true);
    try {
      const res = await sendChat(sessionId, userId, userText, chatMode, sharedCtx);
      setMessages(m => {
        const next = [...m];
        next[next.length - 1] = { id: next[next.length - 1].id, role: "assistant", content: res.reply || "" };
        return next;
      });
    } catch (err) {
      setMessages(m => {
        const next = [...m];
        next[next.length - 1] = { id: next[next.length - 1].id, role: "assistant", content: `Error: ${err instanceof Error ? err.message : "unknown"}` };
        return next;
      });
    } finally {
      setSending(false);
    }
  }, [sessionId, userId, mode, sharedCtx]);

  const handleAction = async (action: "hint" | "confused" | "skip") => {
    if (!sessionId || !userId) return;
    const chatMode = CHAT_MODES.includes(mode) ? mode : "socratic";
    const labelMap = { hint: "(Requested a hint)", confused: "(Said I'm confused)", skip: "(Asked to skip)" };
    setMessages(m => [
      ...m,
      { id: msgId(), role: "user", content: labelMap[action] },
      { id: msgId(), role: "assistant", content: "", loading: true },
    ]);
    setSending(true);
    try {
      const res = await learnAction(sessionId, userId, action, chatMode, sharedCtx);
      setMessages(m => {
        const next = [...m];
        next[next.length - 1] = { id: next[next.length - 1].id, role: "assistant", content: res.reply || "" };
        return next;
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Action failed.");
      setMessages(m => m.slice(0, -2));
    } finally {
      setSending(false);
    }
  };

  const handleModeSwitch = async (newMode: Mode) => {
    if (newMode === mode) return;
    if (!sessionId || !userId) {
      setMode(newMode);
      return;
    }
    if (newMode === "quiz") {
      // Quiz mode is UI-driven — don't call mode-switch.
      setMode(newMode);
      return;
    }
    const prev = mode;
    setMode(newMode);
    try {
      const res = await switchMode(sessionId, userId, newMode);
      if (res.reply) {
        setMessages(m => [...m, { id: msgId(), role: "assistant", content: res.reply }]);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Mode switch failed.");
      setMode(prev);
    }
  };

  const handleEndSession = useCallback(async () => {
    if (!sessionId || !userId) return;
    try {
      const res = await endSession(sessionId, userId);
      setSummary(res.summary ?? null);
      // Write session context for navigate-away feedback
      try {
        sessionStorage.setItem(LAST_SESSION_CTX_KEY, JSON.stringify({ sessionId, topic }));
      } catch {}
      // Bump end-count for every-3 session-feedback trigger
      try {
        const n = Number(localStorage.getItem(SESSION_END_COUNT_KEY) ?? "0") + 1;
        localStorage.setItem(SESSION_END_COUNT_KEY, String(n));
      } catch {}
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "End session failed.");
    }
  }, [sessionId, userId, topic, toast]);

  const endConfirm = useConfirm(() => { handleEndSession(); }, 3000);

  const closeSummary = () => {
    setSummary(null);
    setSessionId(null);
    setMessages([]);
    setTopic("");
    setTopicDraft("");
  };

  const handleBackToLearn = () => {
    setSessionId(null);
    setMessages([]);
    setTopic("");
    setTopicDraft("");
    router.replace(`/learn?mode=${mode}`, { scroll: false });
  };

  const startNextFromSummary = (concept: string) => {
    setSummary(null);
    setSessionId(null);
    setMessages([]);
    setTopicDraft(concept);
    setTopic(concept);
    router.replace(`/learn?topic=${encodeURIComponent(concept)}&mode=${mode}`, { scroll: false });
  };

  const modeOptions = useMemo(() => MODES.map(m => ({ value: m.id, label: m.name, description: m.tip })), []);

  const suggestParam = searchParams.get("suggest");
  const highlightId = useMemo(() => {
    // Pre-revamp Learn honored ?suggest=<concept> from the Dashboard
    // "Learn next" suggestion; restore that here, falling back to the
    // current topic if no suggestion is active.
    const suggestMatch = suggestParam
      ? graphNodes.find(n => n.name.toLowerCase() === suggestParam.trim().toLowerCase())
      : null;
    if (suggestMatch) return suggestMatch.id;
    return graphNodes.find(n => n.name.toLowerCase() === topic.trim().toLowerCase())?.id;
  }, [suggestParam, graphNodes, topic]);

  const handleNodeClick = useCallback((n: GraphNode) => {
    if (!n.is_subject_root) {
      router.replace(`/learn?topic=${encodeURIComponent(n.name)}&mode=${mode}`, { scroll: false });
    }
  }, [router, mode]);

  const topicNode = useMemo(
    () => graphNodes.find(n => n.id === highlightId),
    [graphNodes, highlightId],
  );

  const neighborIds = useMemo(() => {
    if (!topicNode) return new Set<string>();
    const ids = new Set<string>();
    for (const e of graphEdges) {
      if (e.source === topicNode.id) ids.add(e.target as string);
      else if (e.target === topicNode.id) ids.add(e.source as string);
    }
    return ids;
  }, [topicNode, graphEdges]);

  const progressItems = useMemo(() => {
    if (!topicNode) return [];
    return graphNodes
      .filter(n => neighborIds.has(n.id) && !n.is_subject_root)
      .slice(0, 6)
      .map(n => ({ name: n.name, complete: n.mastery_tier === "mastered" }));
  }, [graphNodes, neighborIds, topicNode]);

  const relatedItems = useMemo(() => {
    if (!topicNode) return [] as string[];
    return graphNodes
      .filter(n =>
        n.id !== topicNode.id &&
        !n.is_subject_root &&
        !neighborIds.has(n.id) &&
        n.course_id === topicNode.course_id,
      )
      .sort((a, b) => (b.mastery_score ?? 0) - (a.mastery_score ?? 0))
      .slice(0, 4)
      .map(n => n.name);
  }, [graphNodes, neighborIds, topicNode]);

  const startSessionFromConcept = useCallback((concept: string) => {
    setSessionId(null);
    setMessages([]);
    setTopicDraft(concept);
    setTopic(concept);
    router.replace(`/learn?topic=${encodeURIComponent(concept)}&mode=${mode}`, { scroll: false });
  }, [router, mode]);

  // ────────── Entry screen (no active session) ──────────
  if (!sessionId && !starting && mode !== "quiz") {
    return (
      <div className="fade-in" style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
        <DisclaimerModal />
        <TopBar
          breadcrumb="Learn"
          title="Start a session"
          subtitle="Pick a topic. Sapling will adapt to your chosen mode."
          actions={<AIDisclaimerChip />}
        />
        <div
          style={{
            padding: 32,
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : "minmax(0, 1fr) 320px",
            gap: 24,
            flex: 1,
            overflowY: "auto",
          }}
        >
          <div className="card" style={{ padding: "var(--pad-xl)" }}>
            <div className="label-micro" style={{ marginBottom: 8 }}>Course (optional)</div>
            <CustomSelect<string>
              value={selectedCourseId}
              options={[
                { value: "", label: "No course" },
                ...courses.map(c => ({ value: c.course_id, label: `${c.course_code} — ${c.course_name}` })),
              ]}
              onChange={setSelectedCourseId}
              style={{ width: "100%", marginBottom: 16 }}
            />
            <div className="label-micro" style={{ marginBottom: 8 }}>Topic</div>
            <TopicPicker
              value={topicDraft}
              onChange={setTopicDraft}
              onSubmit={handleStart}
              concepts={concepts}
              courses={courses}
              selectedCourseId={selectedCourseId}
            />
            <div className="label-micro" style={{ marginBottom: 8 }}>Mode</div>
            <div style={{ display: "flex", gap: 6, marginBottom: 20, flexWrap: "wrap" }}>
              {MODES.map(m => (
                <button
                  key={m.id}
                  onClick={() => setMode(m.id)}
                  title={m.tip}
                  style={{
                    padding: "8px 16px",
                    borderRadius: "var(--r-full)",
                    fontSize: 13,
                    fontWeight: 500,
                    background: mode === m.id ? "var(--accent)" : "var(--bg-subtle)",
                    color: mode === m.id ? "var(--accent-fg)" : "var(--text-dim)",
                    border: mode === m.id ? "1px solid var(--accent)" : "1px solid var(--border)",
                  }}
                >
                  {m.name}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <SharedContextToggle enabled={sharedCtx} onChange={setSharedCtx} />
              <button className="btn btn--primary" onClick={handleStart} disabled={!topicDraft.trim() || !userId}>
                <Icon name="sparkle" size={13} /> Start learning
              </button>
            </div>
          </div>

          <div className="card" style={{ padding: "var(--pad-lg)" }}>
            <div className="label-micro" style={{ marginBottom: 10 }}>Recent sessions</div>
            {recentSessions.length === 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No recent sessions yet.</div>
            )}
            {recentSessions.map(s => (
              <SessionRow key={s.id} s={s} onResume={handleResume} onDelete={handleDeleteSession} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ────────── Quiz mode entry (no chat session) ──────────
  if (!sessionId && mode === "quiz") {
    return (
      <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
        <DisclaimerModal />
        <TopBar
          breadcrumb="Learn / Quiz"
          title="Quiz"
          subtitle="Pick a concept and test what you know."
          actions={
            <>
              <AIDisclaimerChip />
              <button className="btn btn--sm" onClick={() => setMode("socratic")}>
                <Icon name="x" size={13} /> Back to Learn
              </button>
            </>
          }
        />
        <div style={{ padding: 32, flex: 1, overflowY: "auto" }}>
          {userId ? (
            <QuizPanel
              userId={userId}
              concepts={concepts}
              onExit={() => { setMode("socratic"); setTopic(""); }}
            />
          ) : (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Sign in to take a quiz.</div>
          )}
        </div>
      </div>
    );
  }

  // ────────── Active session ──────────
  return (
    <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
      <DisclaimerModal />

      {isMobile && (
        <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
          {(["chat", "graph"] as const).map(t => (
            <button
              key={t}
              onClick={() => setMobileTab(t)}
              style={{
                flex: 1,
                padding: "10px 0",
                fontSize: 12,
                fontWeight: 500,
                textTransform: "capitalize",
                color: mobileTab === t ? "var(--accent)" : "var(--text-dim)",
                borderBottom: mobileTab === t ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >
              {t}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {(!isMobile || mobileTab === "chat") && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
            <TopBar
              breadcrumb={<BackToLearnLink onClick={handleBackToLearn} />}
              title={topic}
              subtitle={`${mode} tutor · ${messages.length} msgs`}
              actions={
                <>
                  <AIDisclaimerChip />
                  <SharedContextToggle enabled={sharedCtx} onChange={setSharedCtx} />
                  <button
                    className={endConfirm.armed ? "btn btn--danger btn--sm" : "btn btn--sm"}
                    onClick={endConfirm.trigger}
                    title={endConfirm.armed ? "Click again to confirm" : "End session"}
                  >
                    {endConfirm.armed ? "Confirm end" : "End session"}
                  </button>
                </>
              }
            />
            <div style={{ display: "flex", gap: 6, padding: "10px 32px", borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
              {MODES.filter(m => m.id !== "quiz").map(m => (
                <button
                  key={m.id}
                  onClick={() => handleModeSwitch(m.id)}
                  style={{
                    padding: "6px 14px",
                    borderRadius: "var(--r-full)",
                    fontSize: 12,
                    fontWeight: 500,
                    background: mode === m.id ? "var(--accent)" : "var(--bg-subtle)",
                    color: mode === m.id ? "var(--accent-fg)" : "var(--text-dim)",
                    border: mode === m.id ? "1px solid var(--accent)" : "1px solid var(--border)",
                  }}
                >
                  {m.name}
                </button>
              ))}
              <div style={{ flex: 1 }} />
              <button className="btn btn--sm" onClick={() => handleModeSwitch("quiz")}>
                <Icon name="bolt" size={12} /> Quick quiz
              </button>
            </div>
            <ChatPanel
              messages={messages}
              onSend={send}
              onAction={handleAction}
              disabled={sending || starting}
            />
          </div>
        )}

        {(!isMobile || mobileTab === "graph") && (
          <aside
            style={{
              width: isMobile ? "100%" : 320,
              borderLeft: isMobile ? "none" : "1px solid var(--border)",
              background: "var(--bg-subtle)",
              padding: 20,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 16,
            }}
          >
            <div>
              <div className="label-micro">Session</div>
              <div className="h-serif" style={{ fontSize: 18, marginTop: 4 }}>{topic}</div>
            </div>
            {graphNodes.length > 0 && (
              <div
                className="card"
                style={{ padding: 8, display: "flex", flexDirection: "column", gap: 4 }}
              >
                <div className="label-micro" style={{ padding: "4px 6px" }}>Knowledge graph</div>
                <KnowledgeGraph
                  nodes={graphNodes}
                  edges={graphEdges}
                  width={isMobile ? 320 : 280}
                  height={280}
                  variant="organism"
                  highlightId={highlightId}
                  onNodeClick={handleNodeClick}
                />
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div className="card" style={{ padding: 12 }}>
                <div className="label-micro" style={{ marginBottom: 4 }}>Mode</div>
                <div style={{ fontSize: 13, fontWeight: 500, textTransform: "capitalize" }}>{mode}</div>
              </div>
              <div className="card" style={{ padding: 12 }}>
                <div className="label-micro" style={{ marginBottom: 4 }}>Messages</div>
                <div className="mono" style={{ fontSize: 16 }}>{messages.length}</div>
              </div>
            </div>
            <div className="card" style={{ padding: 12 }}>
              <div className="label-micro" style={{ marginBottom: 4 }}>Context</div>
              <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
                {sharedCtx ? "Class intel: on" : "Class intel: off"}
              </div>
            </div>
            {progressItems.length > 0 && <ProgressCard items={progressItems} />}
            {relatedItems.length > 0 && (
              <RelatedConceptsCard items={relatedItems} onSelect={startSessionFromConcept} />
            )}
          </aside>
        )}
      </div>

      {summary && (
        <SessionSummary
          summary={summary}
          onClose={closeSummary}
          onStartNext={startNextFromSummary}
        />
      )}
    </div>
  );
}

function BackToLearnLink({ onClick }: { onClick: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "0 0 4px",
        background: "transparent",
        border: "none",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: 13,
        fontWeight: 400,
        letterSpacing: "normal",
        textTransform: "none",
        color: hover ? "var(--accent)" : "var(--text-muted)",
        transition: "color var(--dur-fast) var(--ease)",
      }}
    >
      <ChevronLeft
        size={14}
        style={{
          transform: hover ? "translateX(-2px)" : "translateX(0)",
          transition: "transform var(--dur-fast) var(--ease)",
        }}
      />
      Back to Learn
    </button>
  );
}

function SessionRow({ s, onResume, onDelete }: {
  s: Session;
  onResume: (s: Session) => void;
  onDelete: (s: Session) => void;
}) {
  const del = useConfirm(() => onDelete(s), 3000);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "8px 10px",
        borderRadius: "var(--r-md)",
        background: "var(--bg-subtle)",
        marginBottom: 6,
      }}
    >
      <button
        onClick={() => onResume(s)}
        style={{
          flex: 1,
          textAlign: "left",
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600 }}>{s.topic}</span>
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
          {s.mode} · {s.message_count} msg{s.message_count === 1 ? "" : "s"}
        </span>
      </button>
      <button
        className={del.armed ? "btn btn--danger btn--sm" : "btn btn--ghost btn--sm"}
        onClick={del.trigger}
        aria-label={del.armed ? "Confirm delete" : "Delete session"}
        title={del.armed ? "Click again to confirm" : "Delete"}
      >
        {del.armed ? "Confirm" : <Icon name="x" size={12} />}
      </button>
    </div>
  );
}

function ProgressCard({ items }: { items: { name: string; complete: boolean }[] }) {
  return (
    <div className="card" style={{ padding: 12 }}>
      <div className="label-micro" style={{ marginBottom: 8 }}>Progress</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {items.map(item => (
          <div key={item.name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 12,
                height: 12,
                borderRadius: "50%",
                flexShrink: 0,
                background: item.complete ? "var(--accent)" : "transparent",
                border: item.complete ? "1px solid var(--accent)" : "1.5px solid var(--border-strong)",
              }}
            />
            <span
              style={{
                fontSize: 12,
                color: item.complete ? "var(--text)" : "var(--text-dim)",
                lineHeight: 1.3,
              }}
            >
              {item.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RelatedConceptsCard({
  items,
  onSelect,
}: {
  items: string[];
  onSelect: (name: string) => void;
}) {
  return (
    <div className="card" style={{ padding: 12 }}>
      <div className="label-micro" style={{ marginBottom: 8 }}>Related</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map(name => (
          <button
            key={name}
            onClick={() => onSelect(name)}
            style={{
              padding: "5px 10px",
              borderRadius: "var(--r-full)",
              fontSize: 12,
              fontWeight: 500,
              border: "1px solid var(--border)",
              background: "transparent",
              color: "var(--text-dim)",
              cursor: "pointer",
              transition: "background 120ms",
            }}
            onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-subtle)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
          >
            {name}
          </button>
        ))}
      </div>
    </div>
  );
}

const GENERAL_TOPIC = "Course overview — pick the next concept I should learn next.";

function TopicPicker({
  value, onChange, onSubmit, concepts, courses, selectedCourseId,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  concepts: { id: string; name: string; course_id: string | null; course_code: string | null }[];
  courses: EnrolledCourse[];
  selectedCourseId: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const selectedCourse = useMemo(
    () => courses.find(c => c.course_id === selectedCourseId) || null,
    [courses, selectedCourseId],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return concepts
      .filter(c => !selectedCourseId || c.course_id === selectedCourseId)
      .filter(c => !q || c.name.toLowerCase().includes(q))
      .slice(0, 80);
  }, [concepts, query, selectedCourseId]);

  const isGeneral = value === GENERAL_TOPIC;
  const courseLabel = selectedCourse
    ? (selectedCourse.course_code || selectedCourse.course_name)
    : "this course";
  const generalLabel = selectedCourse
    ? `General — pick what's next in ${courseLabel}`
    : "General — pick what to study next";

  const pickGeneral = () => {
    onChange(GENERAL_TOPIC);
    setOpen(false);
  };
  const pickConcept = (name: string) => {
    onChange(name);
    setOpen(false);
  };
  const pickCustom = () => {
    const q = query.trim();
    if (!q) return;
    onChange(q);
    setOpen(false);
  };

  const displayLabel = isGeneral ? generalLabel : (value || "Pick or type a topic…");

  return (
    <div ref={wrapRef} style={{ position: "relative", marginBottom: 16 }}>
      <button
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === "Enter" && !open && value.trim()) onSubmit(); }}
        style={{
          width: "100%",
          padding: "12px 14px",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          fontSize: 15,
          background: "var(--bg-input)",
          textAlign: "left",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          color: value ? "var(--text)" : "var(--text-muted)",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {displayLabel}
        </span>
        <Icon name="chev" size={12} />
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0, right: 0,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-sm)",
            boxShadow: "var(--shadow-md)",
            zIndex: 30,
            maxHeight: 360,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Escape") setOpen(false);
              if (e.key === "Enter") {
                if (filtered.length > 0) pickConcept(filtered[0].name);
                else if (query.trim()) pickCustom();
              }
            }}
            placeholder="Search concepts or type a custom topic…"
            style={{
              width: "100%",
              padding: "10px 12px",
              fontSize: 13,
              border: "none",
              borderBottom: "1px solid var(--border)",
              background: "transparent",
              outline: "none",
            }}
          />
          <div style={{ overflowY: "auto", flex: 1 }}>
            <button
              onClick={pickGeneral}
              style={{
                width: "100%", padding: "10px 12px", textAlign: "left",
                background: isGeneral ? "var(--accent-soft)" : "transparent",
                border: "none", cursor: "pointer", fontSize: 13,
                display: "flex", flexDirection: "column", gap: 2,
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span style={{ fontWeight: 600, color: "var(--text)" }}>{generalLabel}</span>
              <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
                Tutor scans your graph and chooses the next concept.
              </span>
            </button>
            {filtered.length === 0 && query.trim() && (
              <button
                onClick={pickCustom}
                style={{
                  width: "100%", padding: "10px 12px", textAlign: "left",
                  background: "transparent", border: "none", cursor: "pointer", fontSize: 13,
                  color: "var(--text)",
                }}
              >
                Use custom topic: <strong>“{query.trim()}”</strong>
              </button>
            )}
            {filtered.length === 0 && !query.trim() && (
              <div style={{ padding: "16px 12px", fontSize: 12, color: "var(--text-muted)" }}>
                {selectedCourseId
                  ? "No concepts in this course yet — upload a syllabus or scan to populate the graph."
                  : "No concepts in your graph yet."}
              </div>
            )}
            {filtered.map(c => {
              const isSel = value === c.name;
              return (
                <button
                  key={c.id}
                  onClick={() => pickConcept(c.name)}
                  style={{
                    width: "100%", padding: "8px 12px", textAlign: "left",
                    background: isSel ? "var(--accent-soft)" : "transparent",
                    border: "none", cursor: "pointer", fontSize: 13,
                    display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8,
                  }}
                >
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text)" }}>
                    {c.name}
                  </span>
                  {c.course_code && (
                    <span className="mono" style={{ fontSize: 10, color: "var(--text-muted)", flexShrink: 0 }}>
                      {c.course_code}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
