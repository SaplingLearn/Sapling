'use client';

import { useState, useEffect } from 'react';
import { useUser } from '@/context/UserContext';
import CustomSelect, { SelectOption } from '@/components/CustomSelect';

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

interface Course {
  id: string;
  course_name: string;
  color: string | null;
}

interface Exam {
  id: string;
  title: string;
  due_date: string;
  assignment_type: string;
}

interface StudyTopic {
  name: string;
  importance: string;
  concepts: string[];
}

interface StudyGuide {
  exam: string;
  due_date: string;
  overview: string;
  topics: StudyTopic[];
}

type PageState = 'selection' | 'loading' | 'guide';

export default function StudyClient() {
  const { userId, userReady } = useUser();

  const [courses, setCourses] = useState<Course[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState('');
  const [selectedExamId, setSelectedExamId] = useState('');
  const [pageState, setPageState] = useState<PageState>('selection');
  const [guide, setGuide] = useState<StudyGuide | null>(null);
  const [generatedAt, setGeneratedAt] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  useEffect(() => {
    if (!userReady || !userId) return;
    fetchJSON<{ courses: Course[] }>(`/api/study-guide/${userId}/courses`)
      .then(data => setCourses(data.courses ?? []))
      .catch(console.error);
  }, [userId, userReady]);

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
    setPageState('loading');
    setError(null);
    try {
      const data = await fetchJSON<{ guide: StudyGuide; generated_at: string; cached: boolean }>(
        `/api/study-guide/${userId}/guide?course_id=${selectedCourseId}&exam_id=${selectedExamId}`
      );
      setGuide(data.guide);
      setGeneratedAt(data.generated_at);
      setPageState('guide');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to generate study guide.');
      setPageState('selection');
    }
  };

  const handleRegenerate = async () => {
    if (!selectedCourseId || !selectedExamId) return;
    setRegenerating(true);
    setError(null);
    try {
      const data = await fetchJSON<{ guide: StudyGuide; generated_at: string }>(
        '/api/study-guide/regenerate',
        {
          method: 'POST',
          body: JSON.stringify({ user_id: userId, course_id: selectedCourseId, exam_id: selectedExamId }),
        }
      );
      setGuide(data.guide);
      setGeneratedAt(data.generated_at);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to regenerate study guide.');
    } finally {
      setRegenerating(false);
    }
  };

  const courseOptions: SelectOption[] = courses.map(c => ({ value: c.id, label: c.course_name }));
  const examOptions: SelectOption[] = exams.map(e => ({ value: e.id, label: e.title }));

  const selectedExam = exams.find(e => e.id === selectedExamId);

  // ── Loading state ─────────────────────────────────────────────────────────────
  if (pageState === 'loading') {
    return (
      <div style={{
        height: 'calc(100vh - 48px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f9fafb',
        fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
      }}>
        <div style={{ textAlign: 'center', color: '#6b7280' }}>
          <div style={{
            width: '32px',
            height: '32px',
            border: '2px solid rgba(26,92,42,0.2)',
            borderTop: '2px solid #1a5c2a',
            borderRadius: '50%',
            margin: '0 auto 16px',
            animation: 'spin 0.8s linear infinite',
          }} />
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          <p style={{ fontSize: '14px', fontWeight: 500, color: '#374151', margin: 0 }}>
            Generating your study guide...
          </p>
        </div>
      </div>
    );
  }

  // ── Guide display ─────────────────────────────────────────────────────────────
  if (pageState === 'guide' && guide) {
    const formattedDate = guide.due_date
      ? new Date(guide.due_date + 'T00:00:00').toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })
      : '';
    const formattedGeneratedAt = generatedAt
      ? new Date(generatedAt).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : '';

    return (
      <div style={{
        height: 'calc(100vh - 48px)',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
      }}>
        {/* Top bar */}
        <div style={{
          background: '#f0f5f0',
          borderBottom: '1px solid rgba(107,114,128,0.12)',
          padding: '0 20px',
          height: '52px',
          display: 'flex',
          alignItems: 'center',
          gap: '16px',
          flexShrink: 0,
        }}>
          <button
            onClick={() => { setPageState('selection'); setGuide(null); }}
            style={{ background: 'none', border: 'none', color: '#6b7280', fontSize: '18px', cursor: 'pointer', lineHeight: 1 }}
          >←</button>
          <span style={{ fontSize: '15px', fontWeight: 600, color: '#111827' }}>Study Guide</span>
          <span style={{ fontSize: '13px', color: '#9ca3af' }}>{guide.exam}</span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              onClick={handleRegenerate}
              disabled={regenerating}
              style={{
                padding: '5px 14px',
                background: 'rgba(26,92,42,0.08)',
                color: '#1a5c2a',
                border: '1px solid rgba(26,92,42,0.22)',
                borderRadius: '6px',
                fontSize: '12px',
                fontWeight: 500,
                cursor: regenerating ? 'default' : 'pointer',
                opacity: regenerating ? 0.5 : 1,
                fontFamily: 'inherit',
                transition: 'opacity 0.15s',
              }}
            >
              {regenerating ? 'Regenerating…' : 'Regenerate'}
            </button>
          </div>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflow: 'auto', padding: '32px 24px', background: '#f9fafb' }}>
          <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>

            {error && (
              <div style={{
                padding: '12px 16px',
                background: '#fef2f2',
                border: '1px solid #fca5a5',
                borderRadius: '8px',
                fontSize: '13px',
                color: '#dc2626',
              }}>
                {error}
              </div>
            )}

            {/* Header */}
            <div style={{
              background: '#ffffff',
              border: '1px solid rgba(107,114,128,0.15)',
              borderRadius: '12px',
              padding: '24px',
              boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
            }}>
              <p style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.08em', margin: '0 0 6px' }}>
                Exam
              </p>
              <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>
                {guide.exam}
              </h1>
              {formattedDate && (
                <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 16px' }}>
                  Due {formattedDate}
                </p>
              )}
              <p style={{ fontSize: '14px', color: '#374151', lineHeight: 1.7, margin: 0 }}>
                {guide.overview}
              </p>
            </div>

            {/* Topics */}
            {guide.topics.map((topic, i) => (
              <div
                key={i}
                style={{
                  background: '#ffffff',
                  border: '1px solid rgba(107,114,128,0.15)',
                  borderRadius: '12px',
                  padding: '20px 24px',
                  boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
                }}
              >
                <h2 style={{ fontSize: '16px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>
                  {topic.name}
                </h2>
                <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 14px', lineHeight: 1.5, fontStyle: 'italic' }}>
                  {topic.importance}
                </p>
                <ul style={{ margin: 0, paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {topic.concepts.map((concept, j) => (
                    <li key={j} style={{ fontSize: '13px', color: '#374151', lineHeight: 1.6 }}>
                      {concept}
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {/* Footer */}
            <p style={{ fontSize: '11px', color: '#9ca3af', textAlign: 'center', margin: 0 }}>
              Generated at {formattedGeneratedAt}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Selection state ───────────────────────────────────────────────────────────
  return (
    <div style={{
      height: 'calc(100vh - 48px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f9fafb',
      fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
      padding: '24px',
    }}>
      <div style={{
        background: '#ffffff',
        border: '1px solid rgba(107,114,128,0.15)',
        borderRadius: '16px',
        padding: '40px',
        width: '100%',
        maxWidth: '480px',
        boxShadow: '0 4px 24px rgba(0,0,0,0.06)',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
      }}>
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#111827', margin: '0 0 6px' }}>
            Study Guide
          </h1>
          <p style={{ fontSize: '13px', color: '#9ca3af', margin: 0 }}>
            Select a course and exam to generate your guide
          </p>
        </div>

        {error && (
          <div style={{
            padding: '12px 16px',
            background: '#fef2f2',
            border: '1px solid #fca5a5',
            borderRadius: '8px',
            fontSize: '13px',
            color: '#dc2626',
          }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontSize: '12px', fontWeight: 500, color: '#374151' }}>Course</label>
          <CustomSelect
            value={selectedCourseId}
            onChange={setSelectedCourseId}
            options={courseOptions}
            placeholder="Select a course…"
            style={{ width: '100%' }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontSize: '12px', fontWeight: 500, color: selectedCourseId ? '#374151' : '#9ca3af' }}>
            Exam
          </label>
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

        <button
          onClick={handleGenerate}
          disabled={!selectedCourseId || !selectedExamId}
          style={{
            padding: '11px 20px',
            background: selectedCourseId && selectedExamId ? '#1a5c2a' : 'rgba(107,114,128,0.1)',
            color: selectedCourseId && selectedExamId ? '#ffffff' : '#9ca3af',
            border: 'none',
            borderRadius: '8px',
            fontSize: '14px',
            fontWeight: 600,
            cursor: selectedCourseId && selectedExamId ? 'pointer' : 'default',
            fontFamily: 'inherit',
            transition: 'background 0.15s, color 0.15s',
          }}
        >
          Generate Guide
        </button>
      </div>
    </div>
  );
}
