'use client';

import { useEffect, useState, useMemo, useRef, DragEvent } from 'react';
import { getCourses, addCourse, getDocuments, uploadDocument, deleteDocument, updateDocument } from '@/lib/api';
import CustomSelect from '@/components/CustomSelect';
import { getCourseColor, PRESET_COURSE_COLORS } from '@/lib/graphUtils';
import { useUser } from '@/context/UserContext';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const GLASS: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid rgba(107, 114, 128, 0.15)',
  borderRadius: '10px',
};

type Category = 'all' | 'syllabus' | 'lecture_notes' | 'slides' | 'reading' | 'assignment' | 'study_guide' | 'other';
type UploadStep = 'pick' | 'processing' | 'confirm';

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
const UPLOAD_CATEGORIES = CATEGORY_ORDER.filter(c => c !== 'all') as Exclude<Category, 'all'>[];

const MAX_BYTES = 15 * 1024 * 1024;
const ALLOWED_EXTS = ['.pdf', '.docx', '.pptx'];

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
}

interface Course { id: string; course_name: string; color: string | null; node_count: number; }
interface Flashcard { question: string; answer: string; }
interface Doc {
  id: string; course_id: string; file_name: string; category: string;
  summary: string | null; key_takeaways: string[] | null;
  flashcards: Flashcard[] | null; created_at: string;
}

export default function LibraryPage() {
  const { userId, userReady } = useUser();

  const [courses, setCourses] = useState<Course[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(true);

  // Grid filters
  const [activeCourse, setActiveCourse] = useState<string>('all');
  const [activeCategory, setActiveCategory] = useState<Category>('all');

  // Detail panel state
  const [panelDoc, setPanelDoc] = useState<Doc | null>(null);
  const [revealedCards, setRevealedCards] = useState<Set<number>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

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

  // Upload modal state
  const [showUpload, setShowUpload] = useState(false);
  const [uploadStep, setUploadStep] = useState<UploadStep>('pick');
  const [pickedFile, setPickedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [selectedCourseId, setSelectedCourseId] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [result, setResult] = useState<Doc | null>(null);
  const [resultCategory, setResultCategory] = useState<string>('other');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Inline add-course state (inside upload modal)
  const [showAddCourse, setShowAddCourse] = useState(false);
  const [newCourseName, setNewCourseName] = useState('');
  const [courseAdding, setCourseAdding] = useState(false);
  const [courseAddError, setCourseAddError] = useState('');

  useEffect(() => {
    if (!userReady) return;
    Promise.all([getCourses(userId), getDocuments(userId)])
      .then(([cd, dd]) => { setCourses(cd.courses); setDocs(dd.documents); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [userId, userReady]);

  const courseById = useMemo(() => {
    const m: Record<string, Course> = {};
    courses.forEach(c => { m[c.id] = c; });
    return m;
  }, [courses]);

  const filtered = useMemo(() =>
    docs.filter(d => {
      if (activeCourse !== 'all' && d.course_id !== activeCourse) return false;
      if (activeCategory !== 'all' && d.category !== activeCategory) return false;
      return true;
    }), [docs, activeCourse, activeCategory]);

  // ── File picking ────────────────────────────────────────────────────────────
  function validateAndSet(file: File) {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ALLOWED_EXTS.includes(ext)) {
      setFileError(`Unsupported file type "${ext}". Only PDF, DOCX, and PPTX are accepted.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setFileError('File exceeds the 15 MB limit.');
      return;
    }
    setFileError('');
    setPickedFile(file);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) validateAndSet(f);
  }

  // ── Upload ──────────────────────────────────────────────────────────────────
  async function handleUpload() {
    if (!pickedFile || !selectedCourseId) return;
    setUploadStep('processing');
    setUploadError('');
    try {
      const fd = new FormData();
      fd.append('file', pickedFile);
      fd.append('course_id', selectedCourseId);
      fd.append('user_id', userId);
      const doc = await uploadDocument(fd);
      setResult(doc);
      setResultCategory(doc.category ?? 'other');
      setUploadStep('confirm');
    } catch (e: any) {
      setUploadError(e.message || 'Upload failed. Please try again.');
      setUploadStep('pick');
    }
  }

  // ── Save (close + refresh) ──────────────────────────────────────────────────
  async function handleSave() {
    if (result) {
      // Persist category change to backend if the user changed it
      if (resultCategory !== result.category) {
        try {
          await updateDocument(result.id, { category: resultCategory, user_id: userId });
        } catch (e) {
          console.error('Failed to update category:', e);
        }
      }
      setDocs(prev => [{ ...result, category: resultCategory }, ...prev.filter(d => d.id !== result.id)]);
    }
    closeModal();
  }

  // ── Re-analyze ──────────────────────────────────────────────────────────────
  async function handleReanalyze() {
    const previousId = result?.id;
    setResult(null);
    setUploadStep('processing');
    setUploadError('');
    try {
      // Delete the previous document to avoid duplicates
      if (previousId) {
        await deleteDocument(previousId, userId).catch(() => {});
      }
      const fd = new FormData();
      fd.append('file', pickedFile!);
      fd.append('course_id', selectedCourseId);
      fd.append('user_id', userId);
      const doc = await uploadDocument(fd);
      setResult(doc);
      setResultCategory(doc.category ?? 'other');
      setUploadStep('confirm');
    } catch (e: any) {
      setUploadError(e.message || 'Re-analysis failed.');
      setUploadStep('confirm');
    }
  }

  // ── Close modal ─────────────────────────────────────────────────────────────
  function closeModal() {
    setShowUpload(false);
    setUploadStep('pick');
    setPickedFile(null);
    setFileError('');
    setSelectedCourseId('');
    setUploadError('');
    setResult(null);
    setResultCategory('other');
    setShowAddCourse(false);
    setNewCourseName('');
    setCourseAddError('');
  }

  // ── Inline add course ───────────────────────────────────────────────────────
  async function handleAddCourse() {
    const name = newCourseName.trim();
    if (!name) return;
    setCourseAdding(true);
    setCourseAddError('');
    try {
      const usedColors = new Set(courses.map(c => c.color).filter(Boolean));
      const color = PRESET_COURSE_COLORS.find(c => !usedColors.has(c)) ?? PRESET_COURSE_COLORS[0];
      const res = await addCourse(userId, name, color);
      if (res.already_existed) {
        setCourseAddError(`"${name}" already exists.`);
      } else {
        const updated = await getCourses(userId);
        setCourses(updated.courses);
        const created = updated.courses.find(c => c.course_name === name);
        if (created) setSelectedCourseId(created.id);
        setNewCourseName('');
        setShowAddCourse(false);
      }
    } catch (e: any) {
      setCourseAddError(e.message || 'Failed to add course.');
    } finally {
      setCourseAdding(false);
    }
  }

  // ── Pill helper ─────────────────────────────────────────────────────────────
  const pillStyle = (active: boolean, color?: { bg: string; text: string; border: string }): React.CSSProperties => ({
    padding: '5px 13px', borderRadius: '20px', fontSize: '12px',
    fontWeight: active ? 600 : 400, cursor: 'pointer',
    border: active ? `1px solid ${color?.border ?? 'rgba(26,92,42,0.4)'}` : '1px solid rgba(107,114,128,0.2)',
    background: active ? (color?.bg ?? 'rgba(26,92,42,0.08)') : 'transparent',
    color: active ? (color?.text ?? '#1a5c2a') : '#6b7280',
    fontFamily: UI_FONT, transition: 'all 0.15s', whiteSpace: 'nowrap' as const,
  });

  return (
    <div className="animate-fade-in" style={{ padding: '32px', maxWidth: '1100px', margin: '0 auto', fontFamily: UI_FONT }}>

      {/* Header */}
      <div className="panel-in panel-in-2" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '28px' }}>
        <div>
          <h1 style={{
            fontFamily: "var(--font-spectral), 'Spectral', Georgia, serif",
            fontSize: '32px', fontWeight: 700, color: '#111827', margin: 0, letterSpacing: '-0.02em',
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
              <button key={c.id} onClick={() => setActiveCourse(c.id)}
                style={pillStyle(activeCourse === c.id, { bg: col.bg, text: col.text, border: col.border })}>
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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px' }}>
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
      </div>{/* end panel-in-3 */}

      {/* ── Detail Modal ───────────────────────────────────────────────────── */}
      {panelDoc && (
        <div
          onClick={e => { if (e.target === e.currentTarget) closePanel(); }}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
        >
          <div style={{
            background: '#fff', borderRadius: '12px', width: '620px', maxWidth: '95vw',
            maxHeight: '85vh', overflowY: 'auto', position: 'relative',
            border: '1px solid rgba(107,114,128,0.15)', boxShadow: '0 20px 60px rgba(0,0,0,0.15)',
            fontFamily: UI_FONT, display: 'flex', flexDirection: 'column',
          }}>
            {/* Modal header */}
            <div style={{ padding: '24px 24px 16px', position: 'sticky', top: 0, background: '#fff', zIndex: 1, borderBottom: '1px solid rgba(107,114,128,0.1)' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
                <p style={{ fontSize: '16px', fontWeight: 700, color: '#111827', margin: 0, wordBreak: 'break-word', lineHeight: 1.35, flex: 1 }}>
                  {panelDoc.file_name}
                </p>
                <button onClick={closePanel} style={{ background: 'none', border: 'none', fontSize: '18px', color: '#6b7280', cursor: 'pointer', lineHeight: 1, padding: '2px 4px', flexShrink: 0 }}>✕</button>
              </div>
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '10px' }}>
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
              <p style={{ fontSize: '11px', color: '#9ca3af', margin: '8px 0 0' }}>{formatDate(panelDoc.created_at)}</p>
            </div>

            {/* Modal body */}
            <div style={{ padding: '24px', flex: 1, display: 'flex', flexDirection: 'column', gap: '24px' }}>

              {/* Summary */}
              {panelDoc.summary && (
                <div>
                  <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Summary</p>
                  <p style={{ fontSize: '13px', color: '#374151', margin: 0, lineHeight: 1.65 }}>{panelDoc.summary}</p>
                </div>
              )}

              {/* Key Takeaways */}
              {panelDoc.key_takeaways && panelDoc.key_takeaways.length > 0 && (
                <div>
                  <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 8px' }}>Key Takeaways</p>
                  <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {panelDoc.key_takeaways.map((t, i) => (
                      <li key={i} style={{ fontSize: '13px', color: '#374151', lineHeight: 1.55 }}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Flashcards */}
              {panelDoc.flashcards && panelDoc.flashcards.length > 0 && (
                <div>
                  <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', margin: '0 0 10px' }}>Flashcards</p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {panelDoc.flashcards.map((fc, i) => {
                      const revealed = revealedCards.has(i);
                      return (
                        <div key={i} style={{ border: '1px solid rgba(107,114,128,0.15)', borderRadius: '8px', overflow: 'hidden' }}>
                          <div style={{ padding: '11px 14px', background: '#f8faf8' }}>
                            <p style={{ fontSize: '13px', fontWeight: 500, color: '#111827', margin: 0, lineHeight: 1.4 }}>{fc.question}</p>
                          </div>
                          <div style={{ padding: '10px 14px', borderTop: '1px solid rgba(107,114,128,0.1)' }}>
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

            {/* Delete footer */}
            <div style={{ padding: '16px 20px', borderTop: '1px solid rgba(107,114,128,0.1)', background: '#fff' }}>
              {confirmDelete ? (
                <div>
                  <p style={{ fontSize: '13px', color: '#374151', margin: '0 0 10px', fontWeight: 500 }}>
                    Are you sure? This cannot be undone.
                  </p>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => setConfirmDelete(false)}
                      style={{ flex: 1, padding: '8px', background: '#fff', color: '#374151', border: '1px solid rgba(107,114,128,0.25)', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', fontFamily: 'inherit' }}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleDelete}
                      disabled={deleting}
                      style={{ flex: 1, padding: '8px', background: deleting ? '#f3f4f6' : '#dc2626', color: deleting ? '#9ca3af' : '#fff', border: 'none', borderRadius: '6px', fontSize: '13px', fontWeight: 600, cursor: deleting ? 'default' : 'pointer', fontFamily: 'inherit' }}
                    >
                      {deleting ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmDelete(true)}
                  style={{ width: '100%', padding: '8px', background: 'none', color: '#b91c1c', border: '1px solid rgba(220,38,38,0.25)', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', fontFamily: 'inherit' }}
                >
                  Delete document
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Upload Modal ───────────────────────────────────────────────────── */}
      {showUpload && (
        <div
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
          onClick={e => { if (uploadStep !== 'processing' && e.target === e.currentTarget) closeModal(); }}
        >
          <div style={{ background: '#fff', borderRadius: '12px', padding: '28px', width: '520px', maxWidth: '95vw', maxHeight: '88vh', overflowY: 'auto', position: 'relative', border: '1px solid rgba(107,114,128,0.15)', boxShadow: '0 20px 60px rgba(0,0,0,0.15)', fontFamily: UI_FONT }}>

            {/* Close */}
            {uploadStep !== 'processing' && (
              <button onClick={closeModal} style={{ position: 'absolute', top: '16px', right: '16px', background: 'none', border: 'none', fontSize: '18px', cursor: 'pointer', color: '#6b7280', lineHeight: 1, padding: '4px 6px', borderRadius: '4px' }}>✕</button>
            )}

            {/* ── STEP: pick ── */}
            {uploadStep === 'pick' && (
              <>
                <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>Upload Document</h2>
                <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 20px' }}>PDF, DOCX, or PPTX up to 15 MB.</p>

                {/* Drop zone */}
                <div
                  onDrop={handleDrop}
                  onDragOver={e => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onClick={() => fileInputRef.current?.click()}
                  style={{
                    border: `2px dashed ${dragging ? '#1a5c2a' : 'rgba(107,114,128,0.3)'}`,
                    borderRadius: '8px', padding: '36px', textAlign: 'center', cursor: 'pointer',
                    background: dragging ? 'rgba(26,92,42,0.04)' : '#fafafa',
                    transition: 'all 0.15s', marginBottom: '8px',
                  }}
                >
                  {pickedFile ? (
                    <>
                      <p style={{ fontSize: '14px', fontWeight: 600, color: '#111827', margin: 0 }}>{pickedFile.name}</p>
                      <p style={{ fontSize: '12px', color: '#9ca3af', margin: '4px 0 0' }}>Click to replace</p>
                    </>
                  ) : (
                    <>
                      <p style={{ fontSize: '14px', color: '#6b7280', margin: 0 }}>Drop a file here or click to browse</p>
                      <p style={{ fontSize: '12px', color: '#9ca3af', margin: '6px 0 0' }}>PDF, DOCX, PPTX · Max 15 MB</p>
                    </>
                  )}
                </div>
                <input ref={fileInputRef} type="file" accept=".pdf,.docx,.pptx" style={{ display: 'none' }}
                  onChange={e => { const f = e.target.files?.[0]; if (f) validateAndSet(f); e.target.value = ''; }} />
                {fileError && <p style={{ fontSize: '12px', color: '#b91c1c', margin: '4px 0 0' }}>{fileError}</p>}

                {/* Course selector */}
                <div style={{ marginTop: '20px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <p style={{ fontSize: '11px', fontWeight: 500, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>Course</p>
                    <button
                      onClick={() => setShowAddCourse(v => !v)}
                      style={{ fontSize: '12px', color: '#1a5c2a', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', padding: 0 }}
                    >
                      + Add course
                    </button>
                  </div>
                  <CustomSelect
                    value={selectedCourseId}
                    onChange={setSelectedCourseId}
                    placeholder="Select a course…"
                    options={courses.map(c => ({ value: c.id, label: c.course_name }))}
                    style={{ width: '100%', display: 'block' }}
                  />

                  {/* Inline add-course form */}
                  {showAddCourse && (
                    <div style={{ marginTop: '10px', padding: '12px', background: '#f8faf8', borderRadius: '7px', border: '1px solid rgba(107,114,128,0.15)' }}>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <input
                          autoFocus
                          value={newCourseName}
                          onChange={e => { setNewCourseName(e.target.value); setCourseAddError(''); }}
                          onKeyDown={e => { if (e.key === 'Enter') handleAddCourse(); }}
                          placeholder="Course name…"
                          style={{ flex: 1, padding: '6px 10px', border: '1px solid rgba(107,114,128,0.25)', borderRadius: '5px', fontSize: '13px', fontFamily: 'inherit', outline: 'none', color: '#111827' }}
                        />
                        <button
                          onClick={handleAddCourse}
                          disabled={courseAdding || !newCourseName.trim()}
                          style={{ padding: '6px 14px', background: courseAdding || !newCourseName.trim() ? '#f3f4f6' : '#1a5c2a', color: courseAdding || !newCourseName.trim() ? '#9ca3af' : '#fff', border: 'none', borderRadius: '5px', fontSize: '13px', fontWeight: 600, cursor: courseAdding || !newCourseName.trim() ? 'default' : 'pointer', fontFamily: 'inherit', whiteSpace: 'nowrap' }}
                        >
                          {courseAdding ? '…' : 'Add'}
                        </button>
                      </div>
                      {courseAddError && <p style={{ fontSize: '12px', color: '#b91c1c', margin: '5px 0 0' }}>{courseAddError}</p>}
                    </div>
                  )}
                </div>

                {uploadError && <p style={{ fontSize: '12px', color: '#b91c1c', margin: '12px 0 0' }}>{uploadError}</p>}

                {/* Upload button */}
                <button
                  onClick={handleUpload}
                  disabled={!pickedFile || !selectedCourseId || !!fileError}
                  style={{
                    marginTop: '20px', width: '100%', padding: '10px',
                    background: (!pickedFile || !selectedCourseId || !!fileError) ? '#f3f4f6' : '#1a5c2a',
                    color: (!pickedFile || !selectedCourseId || !!fileError) ? '#9ca3af' : '#fff',
                    border: 'none', borderRadius: '7px', fontSize: '14px', fontWeight: 600,
                    cursor: (!pickedFile || !selectedCourseId || !!fileError) ? 'default' : 'pointer',
                    fontFamily: 'inherit', transition: 'background 0.15s',
                  }}
                >
                  Upload
                </button>
              </>
            )}

            {/* ── STEP: processing ── */}
            {uploadStep === 'processing' && (
              <div style={{ textAlign: 'center', padding: '40px 0' }}>
                <div style={{
                  width: '40px', height: '40px', borderRadius: '50%',
                  border: '3px solid rgba(26,92,42,0.15)', borderTopColor: '#1a5c2a',
                  margin: '0 auto 20px', animation: 'spin 0.8s linear infinite',
                }} />
                <p style={{ fontSize: '15px', fontWeight: 600, color: '#111827', margin: 0 }}>Analyzing your document…</p>
                <p style={{ fontSize: '13px', color: '#9ca3af', margin: '6px 0 0' }}>This may take a moment.</p>
                <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
              </div>
            )}

            {/* ── STEP: confirm ── */}
            {uploadStep === 'confirm' && result && (
              <>
                <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>Review</h2>
                <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 20px' }}>Confirm the AI-generated details before saving.</p>

                {/* Syllabus notice */}
                {result.category === 'syllabus' && (
                  <div style={{ background: 'rgba(26,92,42,0.07)', border: '1px solid rgba(26,92,42,0.2)', borderRadius: '7px', padding: '10px 14px', marginBottom: '16px', fontSize: '13px', color: '#1a5c2a', fontWeight: 500 }}>
                    Assignments have been added to your calendar.
                  </div>
                )}

                {/* Preview card */}
                <div style={{ ...GLASS, padding: '16px', marginBottom: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <p style={{ fontSize: '14px', fontWeight: 600, color: '#111827', margin: 0, wordBreak: 'break-word' }}>{result.file_name}</p>

                  {/* Category — editable */}
                  <div>
                    <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 5px' }}>Category</p>
                    <CustomSelect
                      value={resultCategory}
                      onChange={setResultCategory}
                      options={UPLOAD_CATEGORIES.map(cat => ({ value: cat, label: CATEGORY_LABELS[cat] }))}
                      style={{ width: '100%', display: 'block' }}
                    />
                  </div>

                  {/* Summary */}
                  {result.summary && (
                    <div>
                      <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 5px' }}>Summary</p>
                      <p style={{ fontSize: '13px', color: '#374151', margin: 0, lineHeight: 1.6 }}>{result.summary}</p>
                    </div>
                  )}

                  {/* Key takeaways */}
                  {result.key_takeaways && result.key_takeaways.length > 0 && (
                    <div>
                      <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 5px' }}>Key Takeaways</p>
                      <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {result.key_takeaways.map((t, i) => (
                          <li key={i} style={{ fontSize: '13px', color: '#374151', lineHeight: 1.5 }}>{t}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {uploadError && <p style={{ fontSize: '12px', color: '#b91c1c', margin: '0 0 12px' }}>{uploadError}</p>}

                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={handleReanalyze}
                    style={{ flex: 1, padding: '10px', background: '#fff', color: '#374151', border: '1px solid rgba(107,114,128,0.25)', borderRadius: '7px', fontSize: '13px', fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    Re-analyze
                  </button>
                  <button
                    onClick={handleSave}
                    style={{ flex: 2, padding: '10px', background: '#1a5c2a', color: '#fff', border: 'none', borderRadius: '7px', fontSize: '14px', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    Save to Library
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
