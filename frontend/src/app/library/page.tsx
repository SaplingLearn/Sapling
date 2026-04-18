'use client';

import { useEffect, useState, useMemo } from 'react';
import {
  getCourses,
  getDocuments,
  deleteDocument,
  type EnrolledCourse,
} from '@/lib/api';
import DocumentUploadModal, { type UploadedDoc } from '@/components/DocumentUploadModal';
import { getCourseColor } from '@/lib/graphUtils';
import { useUser } from '@/context/UserContext';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const GLASS: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid rgba(107, 114, 128, 0.15)',
  borderRadius: '10px',
};

type Category = 'all' | 'syllabus' | 'lecture_notes' | 'slides' | 'reading' | 'assignment' | 'study_guide' | 'other';

const CATEGORY_LABELS: Record<string, string> = {
  all: 'All',
  syllabus: 'Syllabus',
  lecture_notes: 'Lecture Notes',
  slides: 'Slides',
  reading: 'Reading',
  assignment: 'Assignment',
  study_guide: 'Study Guide',
  other: 'Other',
};

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  syllabus:      { bg: 'rgba(99,102,241,0.1)',  text: '#4338ca', border: 'rgba(99,102,241,0.25)'  },
  lecture_notes: { bg: 'rgba(13,148,136,0.1)',  text: '#0f766e', border: 'rgba(13,148,136,0.25)'  },
  slides:        { bg: 'rgba(217,119,6,0.1)',   text: '#b45309', border: 'rgba(217,119,6,0.25)'   },
  reading:       { bg: 'rgba(37,99,235,0.1)',   text: '#1d4ed8', border: 'rgba(37,99,235,0.25)'   },
  assignment:    { bg: 'rgba(220,38,38,0.1)',   text: '#b91c1c', border: 'rgba(220,38,38,0.25)'   },
  study_guide:   { bg: 'rgba(5,150,105,0.1)',   text: '#047857', border: 'rgba(5,150,105,0.25)'   },
  other:         { bg: 'rgba(107,114,128,0.1)', text: '#4b5563', border: 'rgba(107,114,128,0.25)' },
};

const CATEGORY_ORDER: Category[] = ['all', 'syllabus', 'lecture_notes', 'slides', 'reading', 'assignment', 'study_guide', 'other'];

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

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
}

type Doc = UploadedDoc;

export default function LibraryPage() {
  const { userId, userReady } = useUser();
  const isMobile = useIsMobile();

  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(true);

  const [activeCourse, setActiveCourse] = useState<string>('all');
  const [activeCategory, setActiveCategory] = useState<Category>('all');

  const [panelDoc, setPanelDoc] = useState<Doc | null>(null);
  const [revealedCards, setRevealedCards] = useState<Set<number>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [showUpload, setShowUpload] = useState(false);

  function openPanel(doc: Doc) {
    setPanelDoc(doc);
    setRevealedCards(new Set());
    setConfirmDelete(false);
  }

  function closePanel() {
    setPanelDoc(null);
    setConfirmDelete(false);
    setDeleting(false);
  }

  async function handleDelete() {
    if (!panelDoc) return;
    setDeleting(true);
    try {
      await deleteDocument(panelDoc.id, userId);
      setDocs(prev => prev.filter(d => d.id !== panelDoc.id));
      closePanel();
    } catch (e) {
      console.error(e);
      setDeleting(false);
    }
  }

  useEffect(() => {
    if (!userReady) return;
    Promise.all([getCourses(userId), getDocuments(userId)])
      .then(([cd, dd]) => { setCourses(cd.courses); setDocs(dd.documents); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [userId, userReady]);

  const courseById = useMemo(() => {
    const m: Record<string, EnrolledCourse> = {};
    courses.forEach(c => {
      m[c.course_id] = c;
    });
    return m;
  }, [courses]);

  const filtered = useMemo(() =>
    docs.filter(d => {
      if (activeCourse !== 'all' && d.course_id !== activeCourse) return false;
      if (activeCategory !== 'all' && d.category !== activeCategory) return false;
      return true;
    }), [docs, activeCourse, activeCategory]);

  function handleUploadClose(uploaded: UploadedDoc[]) {
    setShowUpload(false);
    // Parallel uploads may have persisted docs before the user finished review — resync grid.
    if (uploaded.length > 0 && userId) {
      const sync = () =>
        getDocuments(userId)
          .then(d => setDocs(d.documents))
          .catch(() => {});
      sync();
      window.setTimeout(sync, 1500);
    }
  }

  function handleDocConfirmed(doc: UploadedDoc) {
    setDocs(prev => [doc, ...prev.filter(d => d.id !== doc.id)]);
  }

  const pillStyle = (active: boolean, color?: { bg: string; text: string; border: string }): React.CSSProperties => ({
    padding: '5px 13px', borderRadius: '20px', fontSize: '12px',
    fontWeight: active ? 600 : 400, cursor: 'pointer',
    border: active ? `1px solid ${color?.border ?? 'rgba(26,92,42,0.4)'}` : '1px solid rgba(107,114,128,0.2)',
    background: active ? (color?.bg ?? 'rgba(26,92,42,0.08)') : 'transparent',
    color: active ? (color?.text ?? '#1a5c2a') : '#6b7280',
    fontFamily: UI_FONT, transition: 'all 0.15s', whiteSpace: 'nowrap' as const,
  });

  return (
    <div style={{ padding: isMobile ? '12px' : '32px', maxWidth: '1100px', margin: '0 auto', fontFamily: UI_FONT }}>

      {/* Header */}
      <div className="panel-in panel-in-2" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '28px', flexDirection: isMobile ? 'column' as const : 'row' as const, gap: isMobile ? '12px' : undefined }}>
        <div>
          <h1 style={{
            fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif",
            fontSize: isMobile ? '22px' : '32px', fontWeight: 700, color: '#111827', margin: 0, letterSpacing: '-0.02em',
          }}>Library</h1>
          <p style={{ fontSize: '14px', color: '#6b7280', margin: '4px 0 0' }}>Your uploaded course documents.</p>
        </div>
        <button
          onClick={() => setShowUpload(true)}
          style={{
            padding: '8px 20px', background: '#1a5c2a', color: '#fff',
            border: 'none', borderRadius: '7px', fontSize: '13px', fontWeight: 600,
            cursor: 'pointer', fontFamily: UI_FONT, letterSpacing: '0.3px',
          }}
        >
          Upload Document
        </button>
      </div>

      {/* Filters */}
      <div className="panel-in panel-in-2" style={{ ...GLASS, padding: '16px 20px', marginBottom: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', minWidth: '60px' }}>Course</span>
          <button style={pillStyle(activeCourse === 'all')} onClick={() => setActiveCourse('all')}>All</button>
          {courses.map(c => {
            const col = getCourseColor(c.course_name, c.color);
            return (
              <button key={c.course_id} onClick={() => setActiveCourse(c.course_id)}
                style={pillStyle(activeCourse === c.course_id, { bg: col.bg, text: col.text, border: col.border })}>
                {c.course_name}
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', minWidth: '60px' }}>Type</span>
          {CATEGORY_ORDER.map(cat => (
            <button key={cat} onClick={() => setActiveCategory(cat)}
              style={pillStyle(activeCategory === cat, cat !== 'all' ? CATEGORY_COLORS[cat] : undefined)}>
              {CATEGORY_LABELS[cat]}
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      <div className="panel-in panel-in-3">
      {loading ? (
        <p style={{ fontSize: '14px', color: '#9ca3af', paddingTop: '20px' }}>Loading…</p>
      ) : docs.length === 0 ? (
        <div style={{ ...GLASS, padding: '60px 32px', textAlign: 'center' }}>
          <p style={{ fontSize: '16px', fontWeight: 500, color: '#6b7280', margin: 0 }}>No documents yet</p>
          <p style={{ fontSize: '13px', color: '#d1d5db', margin: '6px 0 0' }}>Upload one to get started.</p>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ ...GLASS, padding: '60px 32px', textAlign: 'center' }}>
          <p style={{ fontSize: '15px', fontWeight: 500, color: '#6b7280', margin: 0 }}>No documents match these filters.</p>
          <p style={{ fontSize: '13px', color: '#d1d5db', margin: '6px 0 0' }}>Try selecting a different course or category.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? '240px' : '280px'}, 1fr))`, gap: '14px' }}>
          {filtered.map(doc => {
            const course = courseById[doc.course_id];
            const courseColor = course ? getCourseColor(course.course_name, course.color) : null;
            const catColor = CATEGORY_COLORS[doc.category] ?? CATEGORY_COLORS.other;
            return (
              <div key={doc.id} onClick={() => openPanel(doc)} style={{ ...GLASS, padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px', cursor: 'pointer', transition: 'box-shadow 0.15s' }}
                onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.08)')}
                onMouseLeave={e => (e.currentTarget.style.boxShadow = 'none')}
              >
                <p style={{ fontSize: '14px', fontWeight: 600, color: '#111827', margin: 0, wordBreak: 'break-word', lineHeight: 1.35 }}>
                  {doc.file_name}
                </p>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: catColor.bg, color: catColor.text, border: `1px solid ${catColor.border}` }}>
                    {CATEGORY_LABELS[doc.category] ?? doc.category}
                  </span>
                  {course && courseColor && (
                    <span style={{ fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: courseColor.bg, color: courseColor.text, border: `1px solid ${courseColor.border}` }}>
                      {course.course_name}
                    </span>
                  )}
                </div>
                {doc.summary && (
                  <p style={{ fontSize: '12px', color: '#6b7280', margin: 0, lineHeight: 1.5, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                    {doc.summary}
                  </p>
                )}
                <p style={{ fontSize: '11px', color: '#9ca3af', margin: 0 }}>{formatDate(doc.created_at)}</p>
              </div>
            );
          })}
        </div>
      )}
      </div>

      {/* ── Detail Modal ─────────────────────────────────────────────────────── */}
      {panelDoc && (
        <div
          onClick={e => { if (e.target === e.currentTarget) closePanel(); }}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 80, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '40px 20px', overflowY: 'auto' }}
        >
          <div style={{
            background: '#fff', borderRadius: '12px', width: '620px', maxWidth: '95vw',
            maxHeight: '85vh', overflowY: 'auto', position: 'relative',
            border: '1px solid rgba(107,114,128,0.15)', boxShadow: '0 20px 60px rgba(0,0,0,0.15)',
            fontFamily: UI_FONT, display: 'flex', flexDirection: 'column',
          }}>
            <div style={{ padding: '20px 20px 14px', borderBottom: '1px solid rgba(107,114,128,0.1)', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px', marginBottom: '10px' }}>
                <p style={{ fontSize: '16px', fontWeight: 700, color: '#111827', margin: 0, wordBreak: 'break-word', lineHeight: 1.35, flex: 1 }}>
                  {panelDoc.file_name}
                </p>
                <button onClick={closePanel} style={{ background: 'none', border: 'none', fontSize: '18px', color: '#6b7280', cursor: 'pointer', lineHeight: 1, padding: '2px 4px', flexShrink: 0 }}>✕</button>
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {(() => {
                    const catColor = CATEGORY_COLORS[panelDoc.category] ?? CATEGORY_COLORS.other;
                    return (
                      <span style={{ fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: catColor.bg, color: catColor.text, border: `1px solid ${catColor.border}` }}>
                        {CATEGORY_LABELS[panelDoc.category] ?? panelDoc.category}
                      </span>
                    );
                  })()}
                  {(() => {
                    const course = courseById[panelDoc.course_id];
                    if (!course) return null;
                    const cc = getCourseColor(course.course_name, course.color);
                    return (
                      <span style={{ fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', padding: '2px 8px', borderRadius: '4px', background: cc.bg, color: cc.text, border: `1px solid ${cc.border}` }}>
                        {course.course_name}
                      </span>
                    );
                  })()}
                </div>
              </div>
              <p style={{ fontSize: '11px', color: '#9ca3af', margin: '10px 0 0' }}>{formatDate(panelDoc.created_at)}</p>
            </div>

            <div style={{ padding: '20px', flex: 1, display: 'flex', flexDirection: 'column', gap: '22px' }}>
              {panelDoc.summary && (
                <div>
                  <p style={{ fontSize: '10px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 8px' }}>Summary</p>
                  <p style={{ fontSize: '13px', color: '#374151', margin: 0, lineHeight: 1.65 }}>{panelDoc.summary}</p>
                </div>
              )}

              {panelDoc.key_takeaways && panelDoc.key_takeaways.length > 0 && (
                <div>
                  <p style={{ fontSize: '10px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 8px' }}>Key Takeaways</p>
                  <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {panelDoc.key_takeaways.map((t, i) => (
                      <li key={i} style={{ fontSize: '13px', color: '#374151', lineHeight: 1.55 }}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}

              {panelDoc.flashcards && panelDoc.flashcards.length > 0 && (
                <div>
                  <p style={{ fontSize: '10px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.1em', margin: '0 0 10px' }}>Flashcards</p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {panelDoc.flashcards.map((fc, i) => {
                      const revealed = revealedCards.has(i);
                      return (
                        <div key={i} style={{ border: '1px solid rgba(107,114,128,0.15)', borderRadius: '8px', overflow: 'hidden' }}>
                          <div style={{ padding: '10px 14px', background: '#f8faf8' }}>
                            <p style={{ fontSize: '13px', fontWeight: 500, color: '#111827', margin: 0, lineHeight: 1.4 }}>{fc.question}</p>
                          </div>
                          <div style={{ padding: '9px 14px', borderTop: '1px solid rgba(107,114,128,0.1)' }}>
                            {revealed ? (
                              <p style={{ fontSize: '13px', color: '#374151', margin: 0, lineHeight: 1.5 }}>{fc.answer}</p>
                            ) : (
                              <button
                                onClick={() => setRevealedCards(prev => new Set([...prev, i]))}
                                style={{ fontSize: '12px', color: '#1a5c2a', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', padding: 0, fontWeight: 500 }}
                              >
                                Reveal answer
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <div style={{ padding: '14px 20px', borderTop: '1px solid rgba(107,114,128,0.1)', flexShrink: 0 }}>
              {confirmDelete ? (
                <div>
                  <p style={{ fontSize: '13px', color: '#374151', margin: '0 0 10px', fontWeight: 500 }}>
                    Are you sure? This cannot be undone.
                  </p>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button onClick={() => setConfirmDelete(false)} style={{ flex: 1, padding: '8px', background: '#fff', color: '#374151', border: '1px solid rgba(107,114,128,0.25)', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', fontFamily: 'inherit' }}>
                      Cancel
                    </button>
                    <button onClick={handleDelete} disabled={deleting} style={{ flex: 1, padding: '8px', background: deleting ? '#f3f4f6' : '#dc2626', color: deleting ? '#9ca3af' : '#fff', border: 'none', borderRadius: '6px', fontSize: '13px', fontWeight: 600, cursor: deleting ? 'default' : 'pointer', fontFamily: 'inherit' }}>
                      {deleting ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                </div>
              ) : (
                <button onClick={() => setConfirmDelete(true)} style={{ width: '100%', padding: '8px', background: 'none', color: '#b91c1c', border: '1px solid rgba(220,38,38,0.25)', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', fontFamily: 'inherit' }}>
                  Delete document
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <DocumentUploadModal
        open={showUpload}
        onClose={handleUploadClose}
        userId={userId}
        courses={courses}
        onCoursesChanged={setCourses}
        onDocConfirmed={handleDocConfirmed}
      />
    </div>
  );
}
