"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

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
    try {
      const res = await startSession(userId, t, mode, selectedCourseId || undefined, sharedCtx);
      setSessionId(res.session_id);
      setMessages([{ id: msgId(), role: "assistant", content: res.initial_message || "Let's begin." }]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't start session.");
      setMessages([]);
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

  const send = async () => {
    if (!input.trim() || !sessionId || !userId) return;
    const userText = input;
    const chatMode = CHAT_MODES.includes(mode) ? mode : "socratic";
    setInput("");
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
  };

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
      setInput(`Continue in ${newMode} mode on ${topic}…`);
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

  const startNextFromSummary = (concept: string) => {
    setSummary(null);
    setSessionId(null);
    setMessages([]);
    setTopicDraft(concept);
    setTopic(concept);
    router.replace(`/learn?topic=${encodeURIComponent(concept)}&mode=${mode}`, { scroll: false });
  };

  const modeOptions = useMemo(() => MODES.map(m => ({ value: m.id, label: m.name, description: m.tip })), []);

  // ────────── Entry screen (no active session) ──────────
  if (!sessionId && mode !== "quiz") {
    return (
      <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
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
            <div className="label-micro" style={{ marginBottom: 8 }}>Topic</div>
            <input
              value={topicDraft}
              onChange={e => setTopicDraft(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") handleStart(); }}
              placeholder="e.g. Eigenvalue decomposition"
              style={{
                width: "100%",
                padding: "12px 14px",
                border: "1px solid var(--border)",
                borderRadius: "var(--r-sm)",
                fontSize: 15,
                background: "var(--bg-input)",
                marginBottom: 16,
              }}
            />
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
      <TopBar
        breadcrumb={`Learn / ${topic}`}
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
            <ChatPanel
              messages={messages}
              input={input}
              onInputChange={setInput}
              onSend={send}
              onAction={handleAction}
              disabled={sending}
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
                  highlightId={(() => {
                    // Pre-revamp Learn honored ?suggest=<concept> from the Dashboard
                    // "Learn next" suggestion; restore that here, falling back to the
                    // current topic if no suggestion is active.
                    const suggest = searchParams.get("suggest");
                    const suggestMatch = suggest
                      ? graphNodes.find(n => n.name.toLowerCase() === suggest.trim().toLowerCase())
                      : null;
                    if (suggestMatch) return suggestMatch.id;
                    return graphNodes.find(n => n.name.toLowerCase() === topic.trim().toLowerCase())?.id;
                  })()}
                  onNodeClick={(n) => {
                    if (!n.is_subject_root) {
                      router.replace(`/learn?topic=${encodeURIComponent(n.name)}&mode=${mode}`, { scroll: false });
                    }
                  }}
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
