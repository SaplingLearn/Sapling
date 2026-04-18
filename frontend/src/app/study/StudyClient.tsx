'use client';

import { useState, useEffect } from 'react';
import { useUser } from '@/context/UserContext';
import CustomSelect, { SelectOption } from '@/components/CustomSelect';
import FlashcardsPanel from './FlashcardsPanel';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
}

interface Course { id: string; course_name: string; color: string | null; }
interface Exam { id: string; title: string; due_date: string; assignment_type: string; }
interface StudyTopic { name: string; importance: string; concepts: string[]; }
interface StudyGuide { exam: string; due_date: string; overview: string; topics: StudyTopic[]; }
interface CachedGuide { id: string; course_id: string; exam_id: string; course_name: string; exam_title: string; overview: string; generated_at: string; }

type Mode = 'flashcards' | 'study-guide';
type GuideState = 'selection' | 'loading' | 'guide';

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

export default function StudyClient() {
  const { userId, userReady } = useUser();
  const isMobile = useIsMobile();

  const [mode, setMode] = useState<Mode>('study-guide');
  const [flashcardStudyMode, setFlashcardStudyMode] = useState(false);

  const [guideState, setGuideState] = useState<GuideState>('selection');
  const [courses, setCourses] = useState<Course[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [cachedGuides, setCachedGuides] = useState<CachedGuide[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState('');
  const [selectedExamId, setSelectedExamId] = useState('');
  const [guide, setGuide] = useState<StudyGuide | null>(null);
  const [generatedAt, setGeneratedAt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  const loadCached = () => {
    if (!userId) return;
    fetchJSON<{ guides: CachedGuide[] }>(`/api/study-guide/${userId}/cached`)
      .then(data => setCachedGuides(data.guides ?? []))
      .catch(console.error);
  };

  useEffect(() => {
    if (!userReady || !userId) return;
    fetchJSON<{ courses: Course[] }>(`/api/study-guide/${userId}/courses`)
      .then(data => setCourses(data.courses ?? []))
      .catch(console.error);
    loadCached();
  }, [userId, userReady]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedCourseId || !userId) return;
    setSelectedExamId('');
    setExams([]);
    fetchJSON<{ exams: Exam[] }>(`/api/study-guide/${userId}/exams?course_id=${selectedCourseId}`)
      .then(data => setExams(data.exams ?? []))
      .catch(console.error);
  }, [selectedCourseId, userId]);

  const handleGenerate = async () => {
    if (!selectedCourseId || !selectedExamId) return;
    setGuideState('loading');
    setError(null);
    try {
      const data = await fetchJSON<{ guide: StudyGuide; generated_at: string }>(
        `/api/study-guide/${userId}/guide?course_id=${selectedCourseId}&exam_id=${selectedExamId}`
      );
      setGuide(data.guide);
      setGeneratedAt(data.generated_at);
      setGuideState('guide');
      loadCached();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to generate study guide.');
      setGuideState('selection');
    }
  };

  const handleOpenCached = (cached: CachedGuide) => {
    setSelectedCourseId(cached.course_id);
    setSelectedExamId(cached.exam_id);
    setGuideState('loading');
    setError(null);
    fetchJSON<{ guide: StudyGuide; generated_at: string }>(
      `/api/study-guide/${userId}/guide?course_id=${cached.course_id}&exam_id=${cached.exam_id}`
    ).then(data => {
      setGuide(data.guide);
      setGeneratedAt(data.generated_at);
      setGuideState('guide');
    }).catch(e => {
      setError(e instanceof Error ? e.message : 'Failed to load guide.');
      setGuideState('selection');
    });
  };

  const handleRegenerate = async () => {
    if (!selectedCourseId || !selectedExamId) return;
    setRegenerating(true);
    setError(null);
    try {
      const data = await fetchJSON<{ guide: StudyGuide; generated_at: string }>(
        '/api/study-guide/regenerate',
        { method: 'POST', body: JSON.stringify({ user_id: userId, course_id: selectedCourseId, exam_id: selectedExamId }) }
      );
      setGuide(data.guide);
      setGeneratedAt(data.generated_at);
      loadCached();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to regenerate study guide.');
    } finally {
      setRegenerating(false);
    }
  };

  const courseOptions: SelectOption[] = courses.map(c => ({ value: c.id, label: c.course_name }));
  const examOptions: SelectOption[] = exams.map(e => ({ value: e.id, label: e.title }));
  const selectedExam = exams.find(e => e.id === selectedExamId);
  const font = "var(--font-dm-sans), 'DM Sans', sans-serif";

  const ModeToggle = () => (
    <div style={{
      background: '#f0f5f0',
      borderBottom: '1px solid rgba(107,114,128,0.12)',
      padding: '0 20px',
      height: '52px',
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      flexShrink: 0,
    }}>
      <div style={{ display: 'flex', background: 'rgba(107,114,128,0.1)', borderRadius: '8px', padding: '3px', gap: '2px' }}>
        {(['study-guide', 'flashcards'] as Mode[]).map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            padding: '4px 14px',
            background: mode === m ? '#ffffff' : 'transparent',
            color: mode === m ? '#111827' : '#6b7280',
            border: 'none', borderRadius: '6px', fontSize: '13px',
            fontWeight: mode === m ? 600 : 400,
            cursor: 'pointer', fontFamily: font,
            boxShadow: mode === m ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
            transition: 'all 0.15s',
          }}>
            {m === 'study-guide' ? 'Study Guide' : 'Flashcards'}
          </button>
        ))}
      </div>
    </div>
  );

  // ── Guide display (full takeover) ─────────────────────────────────────────────
  if (mode === 'study-guide' && guideState === 'guide' && guide) {
    const fmtDate = guide.due_date ? new Date(guide.due_date + 'T00:00:00').toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) : '';
    const fmtGen = generatedAt ? new Date(generatedAt).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
    return (
      <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', fontFamily: font }}>
        <div style={{ background: '#f0f5f0', borderBottom: '1px solid rgba(107,114,128,0.12)', padding: '0 20px', height: '52px', display: 'flex', alignItems: 'center', gap: '16px', flexShrink: 0, flexWrap: 'wrap' }}>
          <button onClick={() => { setGuideState('selection'); setGuide(null); }} style={{ background: 'none', border: 'none', color: '#6b7280', fontSize: '18px', cursor: 'pointer', lineHeight: 1 }}>←</button>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#111827' }}>Study Guide</span>
          <span style={{ fontSize: '13px', color: '#9ca3af' }}>{guide.exam}</span>
          <div style={{ marginLeft: 'auto' }}>
            <button onClick={handleRegenerate} disabled={regenerating} style={{ padding: '5px 14px', background: 'rgba(26,92,42,0.08)', color: '#1a5c2a', border: '1px solid rgba(26,92,42,0.22)', borderRadius: '6px', fontSize: '12px', fontWeight: 500, cursor: regenerating ? 'default' : 'pointer', opacity: regenerating ? 0.5 : 1, fontFamily: font, transition: 'opacity 0.15s' }}>
              {regenerating ? 'Regenerating…' : 'Regenerate'}
            </button>
          </div>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: '32px 24px', background: '#f0f5f0' }}>
          <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {error && <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '8px', fontSize: '13px', color: '#dc2626' }}>{error}</div>}
            <div style={{ background: '#ffffff', border: '1px solid rgba(107,114,128,0.15)', borderRadius: '12px', padding: '24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
              <p style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 6px' }}>Exam</p>
              <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>{guide.exam}</h1>
              {fmtDate && <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 16px' }}>Due {fmtDate}</p>}
              <p style={{ fontSize: '14px', color: '#374151', lineHeight: 1.7, margin: 0 }}>{guide.overview}</p>
            </div>
            {guide.topics.map((topic, i) => (
              <div key={i} style={{ background: '#ffffff', border: '1px solid rgba(107,114,128,0.15)', borderRadius: '12px', padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
                <h2 style={{ fontSize: '16px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>{topic.name}</h2>
                <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 14px', lineHeight: 1.5, fontStyle: 'italic' }}>{topic.importance}</p>
                <ul style={{ margin: 0, paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {topic.concepts.map((c, j) => <li key={j} style={{ fontSize: '13px', color: '#374151', lineHeight: 1.6 }}>{c}</li>)}
                </ul>
              </div>
            ))}
            <p style={{ fontSize: '11px', color: '#9ca3af', textAlign: 'center', margin: 0 }}>Generated at {fmtGen}</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Loading (full takeover) ───────────────────────────────────────────────────
  if (mode === 'study-guide' && guideState === 'loading') {
    return (
      <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', fontFamily: font }}>
        <ModeToggle />
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ width: '32px', height: '32px', border: '2px solid rgba(26,92,42,0.2)', borderTop: '2px solid #1a5c2a', borderRadius: '50%', margin: '0 auto 16px', animation: 'spin 0.8s linear infinite' }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            <p style={{ fontSize: '14px', fontWeight: 500, color: '#374151', margin: 0 }}>Generating your study guide...</p>
          </div>
        </div>
      </div>
    );
  }

  // ── Main layout — FlashcardsPanel always mounted for caching ──────────────────
  return (
    <div style={{ height: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column', fontFamily: font }}>
      {!flashcardStudyMode && <ModeToggle />}

      {/* FlashcardsPanel — always mounted, hidden when not active */}
      <div style={{ display: mode === 'flashcards' ? 'flex' : 'none', flex: 1, flexDirection: 'column', minHeight: 0 }}>
        <FlashcardsPanel onStudyModeChange={setFlashcardStudyMode} />
      </div>

      {/* Study guide selection */}
      {mode === 'study-guide' && (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', flexDirection: isMobile ? 'column' as const : 'row' as const }}>
          {/* Left — generator */}
          <div style={{ width: isMobile ? '100%' : '380px', ...(isMobile ? {} : { flexShrink: 0 }), borderRight: '1px solid rgba(107,114,128,0.12)', padding: '24px 20px', display: 'flex', flexDirection: 'column', gap: '20px', background: '#f9fafb', overflowY: 'auto' }}>
            <p style={{ fontSize: '15px', fontWeight: 600, color: '#111827', margin: '0 0 4px' }}>Generate study guide</p>
            {error && <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '8px', fontSize: '13px', color: '#dc2626' }}>{error}</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontSize: '12px', color: '#6b7280' }}>Course</label>
              <CustomSelect value={selectedCourseId} onChange={setSelectedCourseId} options={courseOptions} placeholder="Select a course…" style={{ width: '100%' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ fontSize: '12px', color: '#6b7280' }}>Exam</label>
              <CustomSelect
                value={selectedExamId}
                onChange={setSelectedExamId}
                options={examOptions}
                placeholder={selectedCourseId ? (exams.length === 0 ? 'No exams found…' : 'Select an exam…') : 'Select a course first…'}
                style={{ width: '100%', opacity: selectedCourseId ? 1 : 0.5, pointerEvents: selectedCourseId ? 'auto' : 'none' } as React.CSSProperties}
                openUpward
              />
            </div>
            {selectedExam?.due_date && (
              <p style={{ fontSize: '12px', color: '#6b7280', margin: 0 }}>
                Due {new Date(selectedExam.due_date + 'T00:00:00').toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })}
              </p>
            )}
            <button onClick={handleGenerate} disabled={!selectedCourseId || !selectedExamId} style={{
              padding: '11px 20px',
              background: selectedCourseId && selectedExamId ? '#1a5c2a' : 'rgba(107,114,128,0.1)',
              color: selectedCourseId && selectedExamId ? '#ffffff' : '#9ca3af',
              border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: 600,
              cursor: selectedCourseId && selectedExamId ? 'pointer' : 'default',
              fontFamily: font, transition: 'background 0.15s, color 0.15s',
            }}>Generate Guide</button>
          </div>

          {/* Right — recent guides (no background, matches flashcard right panel) */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '32px 28px' }}>
            <p style={{ fontSize: '13px', fontWeight: 600, color: '#374151', margin: '0 0 16px' }}>Recent guides</p>
            {cachedGuides.length === 0 ? (
              <div style={{ textAlign: 'center', marginTop: '80px', color: '#9ca3af' }}>
                <p style={{ fontSize: '14px', fontWeight: 500, color: '#6b7280', margin: '0 0 4px' }}>No guides yet</p>
                <p style={{ fontSize: '13px', margin: 0 }}>Generate your first study guide on the left.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {cachedGuides.map(g => {
                  const ts = new Date(g.generated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
                  return (
                    <button key={g.id} onClick={() => handleOpenCached(g)} style={{
                      background: '#ffffff', border: '1px solid rgba(107,114,128,0.15)', borderRadius: '12px',
                      padding: '16px 20px', textAlign: 'left', cursor: 'pointer', fontFamily: font,
                      boxShadow: '0 1px 4px rgba(0,0,0,0.04)', transition: 'border-color 0.15s, box-shadow 0.15s',
                      display: 'flex', flexDirection: 'column', gap: '6px',
                    }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = 'rgba(26,92,42,0.3)'; e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.08)'; }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(107,114,128,0.15)'; e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.04)'; }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 600, color: '#111827' }}>{g.exam_title}</span>
                        <span style={{ fontSize: '10px', fontWeight: 600, color: '#1a5c2a', background: 'rgba(26,92,42,0.08)', padding: '2px 8px', borderRadius: '10px', whiteSpace: 'nowrap', flexShrink: 0 }}>{g.course_name}</span>
                      </div>
                      {g.overview && <p style={{ fontSize: '12px', color: '#6b7280', margin: 0, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{g.overview}</p>}
                      <span style={{ fontSize: '11px', color: '#9ca3af' }}>Generated {ts}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
