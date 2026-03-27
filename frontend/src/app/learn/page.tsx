'use client';

import { useEffect, useState, useRef, Suspense, useMemo, useCallback } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import KnowledgeGraph from '@/components/KnowledgeGraph';
import ChatPanel from '@/components/ChatPanel';
import ModeSelector from '@/components/ModeSelector';
import QuizPanel from '@/components/QuizPanel';
import SessionSummary from '@/components/SessionSummary';
import SessionFeedbackFlow from '@/components/SessionFeedbackFlow';
import { GraphNode, GraphEdge, ChatMessage, TeachingMode, SessionSummary as SessionSummaryType } from '@/lib/types';
import { startSession, sendChat, sendAction, endSession, getGraph, getSessions, resumeSession, switchMode, deleteSession } from '@/lib/api';
import Link from 'next/link';
import { getMasteryLabel } from '@/lib/graphUtils';
import { useUser } from '@/context/UserContext';
import CustomSelect from '@/components/CustomSelect';
import SharedContextToggle from '@/components/SharedContextToggle';
import AIDisclaimerChip from '@/components/AIDisclaimerChip';

function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [breakpoint]);
  return isMobile;
}

function LearnInner() {
  const { userId: USER_ID, userReady } = useUser();
  const searchParams = useSearchParams();
  const router = useRouter();
  const topicParam = searchParams.get('topic') ?? '';
  const modeParam = searchParams.get('mode') ?? 'socratic';
  const suggestConcept = searchParams.get('suggest') ?? '';
  const initialQuiz = modeParam === 'quiz';

  const [mode, setMode] = useState<TeachingMode>(
    ['socratic', 'expository', 'teachback'].includes(modeParam) ? (modeParam as TeachingMode) : 'socratic'
  );
  const [quizMode, setQuizMode] = useState(initialQuiz);

  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [graphReady, setGraphReady] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [summary, setSummary] = useState<SessionSummaryType | null>(null);
  const [showSessionFeedback, setShowSessionFeedback] = useState(
    () => searchParams.get('testFeedback') === 'session'
  );
  const [graphDimensions, setGraphDimensions] = useState({ width: 0, height: 0 });
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const hasDimensionsRef = useRef(false);
  const pendingNavRef = useRef<string | null>(null);
  const feedbackDueRef = useRef(false);
  const deletedSessionIds = useRef<Set<string>>(new Set());

  const SESSION_COUNT_KEY = 'sapling_session_end_count';
  const SESSION_FEEDBACK_EVERY_N = 5;
  const [sessionError, setSessionError] = useState<string | null>(null);

  const [topic, setTopic] = useState(topicParam);
  const [selectedCourse, setSelectedCourse] = useState('');
  const [prefillInput, setPrefillInput] = useState('');
  const [recentSessions, setRecentSessions] = useState<{ id: string; topic: string; name?: string; course_name?: string; mode: string; started_at: string; is_active: boolean }[]>([]);
  const [useSharedContext, setUseSharedContext] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const saved = localStorage.getItem('sapling_shared_ctx');
    return saved === null ? true : saved === 'true';
  });
  const [mobileView, setMobileView] = useState<'chat' | 'graph'>('chat');

  const isMobile = useIsMobile();

  const toggleSharedContext = () => {
    setUseSharedContext(prev => {
      const next = !prev;
      localStorage.setItem('sapling_shared_ctx', String(next));
      return next;
    });
  };

  const courses = [...new Set(nodes.map(n => n.subject).filter(Boolean))].sort();

  // Node matching the Navbar "learn next" suggestion
  const suggestNode = useMemo(
    () => (suggestConcept ? nodes.find(n => n.concept_name === suggestConcept) ?? null : null),
    [nodes, suggestConcept]
  );

  // Strip edges that cross subject boundaries so CS101 and CS112 stay separate
  const filteredEdges = useMemo(() => {
    const nodeSubjectMap = new Map(nodes.map(n => [n.id, n.subject]));
    return edges.filter(e => {
      const srcId = e.source as string;
      const tgtId = e.target as string;
      if (srcId.startsWith('subject_root__') || tgtId.startsWith('subject_root__')) return true;
      const srcSubj = nodeSubjectMap.get(srcId);
      const tgtSubj = nodeSubjectMap.get(tgtId);
      return !srcSubj || !tgtSubj || srcSubj === tgtSubj;
    });
  }, [nodes, edges]);

  // Flag active session for nav-away feedback trigger
  useEffect(() => {
    if (messages.length > 0 && sessionId) {
      localStorage.setItem('sapling_learn_had_session', 'true');
    }
  }, [messages.length, sessionId]);

  // Load initial graph — re-runs when the active user changes
  useEffect(() => {
    if (!userReady) return;
    getGraph(USER_ID).then(data => {
      setNodes(data.nodes);
      setEdges(data.edges);
      setGraphReady(true);
    }).catch(console.error);
  }, [USER_ID, userReady]);

  // Load recent sessions filtered by selected course
  useEffect(() => {
    if (!userReady) return;
    getSessions(USER_ID, 10, selectedCourse || undefined).then(data =>
      setRecentSessions(data.sessions.filter(s => s.message_count > 0))
    ).catch(console.error);
  }, [USER_ID, userReady, selectedCourse]);

  useEffect(() => {
    const el = graphContainerRef.current;
    if (!el) return;
    let timer: ReturnType<typeof setTimeout>;
    const obs = new ResizeObserver(entries => {
      const r = entries[0];
      if (!r) return;
      const { width, height } = r.contentRect;
      if (!hasDimensionsRef.current) {
        hasDimensionsRef.current = true;
        setGraphDimensions({ width, height });
      } else {
        clearTimeout(timer);
        timer = setTimeout(() => setGraphDimensions(prev => {
          if (Math.abs(prev.width - width) < 5 && Math.abs(prev.height - height) < 5) return prev;
          return { width, height };
        }), 200);
      }
    });
    obs.observe(el);
    return () => { obs.disconnect(); clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!topicParam || quizMode) return;
    beginSession(topicParam, mode);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const beginSession = async (t: string, m: TeachingMode) => {
    setSessionLoading(true);
    setSessionError(null);
    setMessages([]);
    setSessionId(null);
    setPrefillInput('');
    try {
      const res = await startSession(USER_ID, t, m, useSharedContext);
      setSessionId(res.session_id);
      setNodes(res.graph_state.nodes);
      setEdges(res.graph_state.edges);
      setMessages([{
        id: `msg_${Date.now()}`,
        role: 'assistant',
        content: res.initial_message,
        timestamp: new Date().toISOString(),
      }]);
    } catch (e: any) {
      console.error(e);
      let msg: string = e?.message || 'Failed to start session. Check that the backend is running.';
      try { msg = JSON.parse(msg)?.detail ?? msg; } catch {}
      setSessionError(msg);
    } finally {
      setSessionLoading(false);
    }
  };

  const handleSend = async (message: string) => {
    if (!sessionId) return;
    setPrefillInput('');
    const userMsg: ChatMessage = {
      id: `msg_${Date.now()}`,
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setChatLoading(true);
    try {
      const res = await sendChat(sessionId, USER_ID, message, mode, useSharedContext);
      setMessages(prev => [...prev, {
        id: `msg_${Date.now() + 1}`,
        role: 'assistant',
        content: res.reply,
        timestamp: new Date().toISOString(),
      }]);
      getGraph(USER_ID).then(data => { setNodes(data.nodes); setEdges(data.edges); }).catch(console.error);
      if (messages.filter(m => m.role === 'user').length === 0) {
        getSessions(USER_ID, 10, selectedCourse || undefined).then(data =>
          setRecentSessions(data.sessions.filter(s => s.message_count > 0 && !deletedSessionIds.current.has(s.id)))
        ).catch(console.error);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setChatLoading(false);
    }
  };

  const handleAction = async (action: 'hint' | 'confused' | 'skip') => {
    if (!sessionId) return;
    setChatLoading(true);
    try {
      const res = await sendAction(sessionId, USER_ID, action, mode, useSharedContext);
      setMessages(prev => [...prev, {
        id: `msg_${Date.now()}`,
        role: 'assistant',
        content: res.reply,
        timestamp: new Date().toISOString(),
      }]);
      getGraph(USER_ID).then(data => { setNodes(data.nodes); setEdges(data.edges); }).catch(console.error);
    } catch (e) {
      console.error(e);
    } finally {
      setChatLoading(false);
    }
  };

  const handleEndSession = async () => {
    if (!sessionId) return;
    try {
      const res = await endSession(sessionId, USER_ID);
      setSummary(res.summary);

      const count = parseInt(localStorage.getItem(SESSION_COUNT_KEY) ?? '0', 10) + 1;
      if (count >= SESSION_FEEDBACK_EVERY_N) {
        feedbackDueRef.current = true;
        localStorage.setItem(SESSION_COUNT_KEY, '0');
      } else {
        feedbackDueRef.current = false;
        localStorage.setItem(SESSION_COUNT_KEY, String(count));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleModeChange = async (newMode: TeachingMode) => {
    if (newMode === mode) return;
    setMode(newMode);
    if (sessionId) {
      try {
        const res = await switchMode(sessionId, USER_ID, newMode);
        setPrefillInput(`Continue in ${newMode} mode on ${topic || 'this topic'}...`);
        setMessages(prev => [...prev, {
          id: `msg_${Date.now()}`,
          role: 'assistant',
          content: res.reply,
          timestamp: new Date().toISOString(),
        }]);
        setRecentSessions(prev => prev.map(s =>
          s.id === sessionId ? { ...s, mode: newMode } : s
        ));
      } catch (e) {
        console.error(e);
      }
    }
  };

  const handleSelectCourse = (course: string) => {
    if (!course) return;
    setSelectedCourse(course);
    setTopic(course);
    beginSession(course, mode);
  };

  const handleDeleteSession = async (sid: string) => {
    deletedSessionIds.current.add(sid);
    setRecentSessions(prev => prev.filter(s => s.id !== sid));
    if (sid === sessionId) {
      setSessionId(null);
      setMessages([]);
      setTopic('');
    }
    try {
      await deleteSession(sid, USER_ID);
    } catch (e) {
      console.error(e);
      // Restore session on failure
      deletedSessionIds.current.delete(sid);
      getSessions(USER_ID, 10, selectedCourse || undefined).then(data =>
        setRecentSessions(data.sessions.filter(s => s.message_count > 0 && !deletedSessionIds.current.has(s.id)))
      ).catch(console.error);
    }
  };

  const handleResumeSession = async (sid: string) => {
    if (!sid) return;
    setSessionLoading(true);
    try {
      const res = await resumeSession(sid);
      setSessionId(res.session.id);
      setTopic(res.session.topic);
      setMode(res.session.mode as TeachingMode);
      setMessages(res.messages.map(m => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        timestamp: m.created_at,
      })));
    } catch (e) {
      console.error(e);
    } finally {
      setSessionLoading(false);
    }
  };

  // Stable node-click handler — ref keeps latest mode/beginSession without invalidating the
  // D3 useEffect dep array on every render (onNodeClick is a dep in KnowledgeGraph).
  const nodeClickPayloadRef = useRef<{ mode: TeachingMode; beginSession: typeof beginSession }>({ mode, beginSession });
  nodeClickPayloadRef.current = { mode, beginSession };
  const handleNodeClick = useCallback((n: GraphNode) => {
    const { mode: m, beginSession: bs } = nodeClickPayloadRef.current;
    setTopic(n.concept_name);
    bs(n.concept_name, m);
  }, []);

  const topicNode = nodes.find(n => n.concept_name.toLowerCase() === topic.toLowerCase());

  // Pre-select the suggested/topic concept when the quiz panel opens
  const quizPreselectId = useMemo(() => {
    const concept = suggestConcept || topicParam;
    if (!concept) return '';
    return nodes.find(n => n.concept_name.toLowerCase() === concept.toLowerCase())?.id ?? '';
  }, [nodes, suggestConcept, topicParam]);

  return (
    <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column' }}>
      {/* Top bar */}
      <div className="panel-in panel-in-1" style={{
        background: 'rgba(255, 255, 255, 0.32)',
        backdropFilter: 'blur(16px) saturate(1.5)',
        WebkitBackdropFilter: 'blur(16px) saturate(1.5)',
        borderBottom: '1px solid rgba(255, 255, 255, 0.55)',
        padding: isMobile ? '8px 10px' : '0 20px',
        height: isMobile ? 'auto' : '52px',
        minHeight: isMobile ? '48px' : undefined,
        display: 'flex',
        alignItems: 'center',
        gap: isMobile ? '8px' : '16px',
        flexWrap: isMobile ? 'wrap' : undefined,
        flexShrink: 0,
        position: 'relative',
        zIndex: 20,
      }}>
        <Link href="/" style={{ color: '#6b7280', textDecoration: 'none', fontSize: '18px', lineHeight: 1 }}>
          ←
        </Link>

        {!isMobile && (
          <CustomSelect
            value={selectedCourse}
            onChange={handleSelectCourse}
            placeholder="Select a course…"
            options={courses.map(c => ({ value: c, label: c }))}
            style={{ minWidth: '160px' }}
          />
        )}

        {/* Resume past session */}
        {!isMobile && recentSessions.length > 0 && (
          <CustomSelect
            value={sessionId ?? ""}
            onChange={sid => handleResumeSession(sid)}
            placeholder="Resume session…"
            options={recentSessions.map(s => {
              const date = new Date(s.started_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
              return { value: s.id, label: `${s.name || s.topic} · ${s.mode} · ${date}` };
            })}
            onDelete={handleDeleteSession}
            style={{ minWidth: '200px' }}
          />
        )}

        {!isMobile && topic && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {topic !== selectedCourse && <span style={{ fontSize: '13px', color: '#6b7280' }}>→</span>}
            <span style={{ fontSize: '14px', fontWeight: 500, color: '#111827' }}>
              {topic !== selectedCourse ? topic : ''}
            </span>
            {topicNode && (
              <span style={{ fontSize: '12px', color: '#6b7280' }}>
                {getMasteryLabel(topicNode.mastery_score)}
              </span>
            )}
          </div>
        )}

        {sessionLoading && <span style={{ fontSize: '13px', color: '#6b7280' }}>Starting…</span>}

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginLeft: 'auto' }}>
          {!isMobile && (
            <>
              <AIDisclaimerChip />
              <SharedContextToggle enabled={useSharedContext} onToggle={toggleSharedContext} />
            </>
          )}

          <ModeSelector
            mode={mode}
            onChange={handleModeChange}
            showQuiz
            quizActive={quizMode}
            onToggleQuiz={() => setQuizMode(q => !q)}
          />
        </div>
      </div>

      {/* Main split */}
      <div className="panel-in panel-in-2" style={{ flex: 1, display: 'flex', flexDirection: isMobile ? 'column' : undefined, overflow: 'hidden' }}>
        {isMobile && (
          <div style={{ display: 'flex', borderBottom: '1px solid rgba(107,114,128,0.12)', flexShrink: 0 }}>
            <button onClick={() => setMobileView('chat')} style={{ flex: 1, padding: '8px', fontSize: '13px', fontWeight: mobileView === 'chat' ? 600 : 400, color: mobileView === 'chat' ? '#1a5c2a' : '#6b7280', background: mobileView === 'chat' ? 'rgba(26,92,42,0.06)' : 'transparent', border: 'none', borderBottom: mobileView === 'chat' ? '2px solid #1a5c2a' : '2px solid transparent', cursor: 'pointer' }}>Chat</button>
            <button onClick={() => setMobileView('graph')} style={{ flex: 1, padding: '8px', fontSize: '13px', fontWeight: mobileView === 'graph' ? 600 : 400, color: mobileView === 'graph' ? '#1a5c2a' : '#6b7280', background: mobileView === 'graph' ? 'rgba(26,92,42,0.06)' : 'transparent', border: 'none', borderBottom: mobileView === 'graph' ? '2px solid #1a5c2a' : '2px solid transparent', cursor: 'pointer' }}>Graph</button>
          </div>
        )}
        <div style={{ flex: 1, borderRight: isMobile ? undefined : '1px solid rgba(107,114,128,0.12)', overflow: 'hidden', display: isMobile && mobileView !== 'chat' ? 'none' : undefined, height: isMobile ? '100%' : undefined }}>
          {quizMode ? (
            <div style={{ height: '100%', overflow: 'hidden' }}>
              <QuizPanel
                nodes={nodes}
                userId={USER_ID}
                selectedCourse={selectedCourse}
                preselectedNodeId={quizPreselectId}
                useSharedContext={useSharedContext}
                onLearnConcept={concept => {
                  setQuizMode(false);
                  if (concept) { setTopic(concept); beginSession(concept, mode); }
                }}
              />
            </div>
          ) : (
            <>
              {sessionError && (
                <div style={{
                  margin: '16px',
                  padding: '12px 16px',
                  background: '#fef2f2',
                  border: '1px solid #fca5a5',
                  borderRadius: '8px',
                  fontSize: '13px',
                  color: '#dc2626',
                }}>
                  <strong>Session error:</strong> {sessionError}
                </div>
              )}
              <ChatPanel
                messages={messages}
                onSend={handleSend}
                onAction={handleAction}
                onEndSession={handleEndSession}
                loading={chatLoading || sessionLoading}
                mode={mode}
                prefillInput={prefillInput}
              />
            </>
          )}
        </div>

        <div style={{ flex: 1, position: 'relative', display: isMobile && mobileView !== 'graph' ? 'none' : 'flex', flexDirection: 'column', height: isMobile ? '100%' : undefined }}>
          <div ref={graphContainerRef} style={{ flex: 1 }}>
            {graphDimensions.width > 0 && graphReady && (
              <KnowledgeGraph
                nodes={nodes}
                edges={filteredEdges}
                width={graphDimensions.width}
                height={graphDimensions.height}
                animate
                interactive
                highlightId={suggestNode?.id ?? topicNode?.id}
                onNodeClick={handleNodeClick}
              />
            )}
          </div>
          <div style={{ position: 'absolute', bottom: '12px', right: '12px' }}>
            <Link href="/tree" style={{ fontSize: '12px', color: '#475569', textDecoration: 'none' }}>
              View Full Tree
            </Link>
          </div>

          {/* AI "learn next" suggestion popup */}
          {suggestConcept && suggestNode && (
            <div className="panel-in-centered panel-in-1" style={{
              position: 'absolute',
              bottom: '44px',
              left: '50%',
              background: 'rgba(255, 255, 255, 0.78)',
              backdropFilter: 'blur(20px) saturate(1.5)',
              WebkitBackdropFilter: 'blur(20px) saturate(1.5)',
              border: '1px solid rgba(255, 255, 255, 0.72)',
              borderRadius: '10px',
              padding: '14px 18px',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.90), 0 8px 32px rgba(26,92,42,0.12)',
              zIndex: 20,
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
              minWidth: isMobile ? '0' : '300px',
              maxWidth: isMobile ? 'calc(100% - 16px)' : '400px',
              width: isMobile ? 'calc(100% - 16px)' : undefined,
              fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
                <span style={{ fontSize: '20px', lineHeight: 1, flexShrink: 0 }}>✨</span>
                <div>
                  <p style={{ fontSize: '11px', fontWeight: 500, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 3px' }}>
                    AI Recommendation
                  </p>
                  <p style={{ fontSize: '15px', fontWeight: 600, color: '#111827', margin: 0 }}>
                    {suggestConcept}
                  </p>
                  <p style={{ fontSize: '12px', color: '#6b7280', margin: '4px 0 0', lineHeight: 1.5 }}>
                    This concept will have the highest impact on your mastery.
                  </p>
                </div>
              </div>
              <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => {
                    const params = new URLSearchParams(searchParams.toString());
                    params.delete('suggest');
                    const q = params.toString();
                    router.replace(q ? `/learn?${q}` : '/learn');
                  }}
                  style={{ padding: '6px 14px', background: 'transparent', color: '#6b7280', border: '1px solid rgba(107,114,128,0.22)', borderRadius: '6px', fontSize: '12px', fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  Dismiss
                </button>
                <button
                  onClick={() => router.push(`/learn?topic=${encodeURIComponent(suggestConcept)}&mode=quiz`)}
                  style={{ padding: '6px 16px', background: '#1a5c2a', color: '#ffffff', border: 'none', borderRadius: '6px', fontSize: '12px', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  Start Quiz →
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {summary && (
        <SessionSummary
          summary={summary}
          onDashboard={() => { setSummary(null); if (feedbackDueRef.current) { pendingNavRef.current = '/dashboard'; setShowSessionFeedback(true); } else { router.push('/dashboard'); } }}
          onNewSession={() => { setSummary(null); setSessionId(null); setMessages([]); if (feedbackDueRef.current) setShowSessionFeedback(true); }}
        />
      )}

      <SessionFeedbackFlow
        visible={showSessionFeedback}
        topic={topic}
        sessionId={sessionId ?? undefined}
        onDismiss={() => { setShowSessionFeedback(false); feedbackDueRef.current = false; if (pendingNavRef.current) { router.push(pendingNavRef.current); pendingNavRef.current = null; } }}
      />
    </div>
  );
}

export default function LearnPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40, color: '#9ca3af' }}>Loading...</div>}>
      <LearnInner />
    </Suspense>
  );
}
