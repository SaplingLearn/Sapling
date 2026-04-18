'use client';

import { useEffect, useState, useRef, DragEvent } from 'react';
import {
  addCourse,
  getCourses,
  uploadDocument,
  deleteDocument,
  updateDocument,
  type EnrolledCourse,
} from '@/lib/api';
import CustomSelect from '@/components/CustomSelect';
import { PRESET_COURSE_COLORS } from '@/lib/graphUtils';

const UI_FONT = "var(--font-dm-sans), 'DM Sans', sans-serif";

const GLASS: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid rgba(107, 114, 128, 0.15)',
  borderRadius: '10px',
};

export interface UploadedDoc {
  id: string;
  course_id: string;
  file_name: string;
  category: string;
  summary: string | null;
  key_takeaways: string[] | null;
  flashcards: { question: string; answer: string }[] | null;
  created_at: string;
}

type UploadStep = 'pick' | 'reviewing';

const CATEGORY_LABELS: Record<string, string> = {
  syllabus: 'Syllabus',
  lecture_notes: 'Lecture Notes',
  slides: 'Slides',
  reading: 'Reading',
  assignment: 'Assignment',
  study_guide: 'Study Guide',
  other: 'Other',
};

const UPLOAD_CATEGORIES = ['syllabus', 'lecture_notes', 'slides', 'reading', 'assignment', 'study_guide', 'other'];

const MAX_FILES = 5;
const MAX_BYTES = 15 * 1024 * 1024;
const ALLOWED_EXTS = ['.pdf', '.docx', '.pptx'];
const UPLOAD_TIMEOUT_MS = 4 * 60 * 1000;

async function uploadDocumentWithTimeout(fd: FormData): Promise<UploadedDoc> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
  try {
    return await uploadDocument(fd, { signal: controller.signal });
  } catch (e: unknown) {
    const aborted =
      (typeof DOMException !== 'undefined' && e instanceof DOMException && e.name === 'AbortError') ||
      (e instanceof Error && e.name === 'AbortError');
    if (aborted) {
      throw new Error(
        'This is taking longer than expected (over 4 minutes). Check your connection and try again with a smaller file.'
      );
    }
    throw e;
  } finally {
    clearTimeout(timeoutId);
  }
}

interface UploadItem {
  file: File;
  status: 'uploading' | 'done' | 'error';
  result: UploadedDoc | null;
  error: string | null;
  resultCategory: string;
}

interface Props {
  open: boolean;
  onClose: (uploaded: UploadedDoc[]) => void;
  userId: string;
  courses: EnrolledCourse[];
  onCoursesChanged: (courses: EnrolledCourse[]) => void;
  onDocConfirmed?: (doc: UploadedDoc) => void;
  initialCourseId?: string;
  title?: string;
  subtitle?: string;
}

export default function DocumentUploadModal({
  open,
  onClose,
  userId,
  courses,
  onCoursesChanged,
  onDocConfirmed,
  initialCourseId,
  title = 'Upload Documents',
  subtitle,
}: Props) {
  const [uploadStep, setUploadStep] = useState<UploadStep>('pick');
  const [pickedFiles, setPickedFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState('');
  const [dragging, setDragging] = useState(false);
  const [selectedCourseId, setSelectedCourseId] = useState(initialCourseId ?? '');
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [confirmedDocs, setConfirmedDocs] = useState<UploadedDoc[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [showAddCourse, setShowAddCourse] = useState(false);
  const [newCourseName, setNewCourseName] = useState('');
  const [courseAdding, setCourseAdding] = useState(false);
  const [courseAddError, setCourseAddError] = useState('');

  useEffect(() => {
    if (open) {
      setSelectedCourseId(initialCourseId ?? '');
    }
  }, [open, initialCourseId]);

  if (!open) return null;

  const defaultSubtitle = `PDF, DOCX, or PPTX · Up to ${MAX_FILES} files · Max 15 MB each.`;

  function validateAndSetMultiple(files: File[]) {
    const limited = files.slice(0, MAX_FILES);
    const valid: File[] = [];
    const errors: string[] = [];

    if (files.length > MAX_FILES) {
      errors.push(`Only up to ${MAX_FILES} files at a time. First ${MAX_FILES} selected.`);
    }

    for (const file of limited) {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      if (!ALLOWED_EXTS.includes(ext)) {
        errors.push(`"${file.name}": unsupported type (PDF, DOCX, PPTX only).`);
        continue;
      }
      if (file.size > MAX_BYTES) {
        errors.push(`"${file.name}" exceeds the 15 MB limit.`);
        continue;
      }
      valid.push(file);
    }

    setFileError(
      errors.length === 0
        ? ''
        : errors.length === 1
          ? errors[0]
          : `${errors.slice(0, 2).join(' · ')}${errors.length > 2 ? ` (+${errors.length - 2} more)` : ''}`
    );
    setPickedFiles(valid);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) validateAndSetMultiple(files);
  }

  async function handleUpload() {
    if (!pickedFiles.length || !selectedCourseId) return;

    const items: UploadItem[] = pickedFiles.map(f => ({
      file: f, status: 'uploading', result: null, error: null, resultCategory: 'other',
    }));
    setUploadItems(items);
    setReviewIndex(0);
    setUploadStep('reviewing');

    pickedFiles.forEach((file, idx) => {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('course_id', selectedCourseId);
      fd.append('user_id', userId);
      uploadDocumentWithTimeout(fd)
        .then(doc => {
          setUploadItems(prev => prev.map((it, i) =>
            i === idx ? { ...it, status: 'done', result: doc, resultCategory: doc.category ?? 'other' } : it
          ));
        })
        .catch((e: any) => {
          setUploadItems(prev => prev.map((it, i) =>
            i === idx ? { ...it, status: 'error', error: e.message || 'Upload failed.' } : it
          ));
        });
    });
  }

  async function handleConfirm() {
    const item = uploadItems[reviewIndex];
    if (!item?.result) return;

    if (item.resultCategory !== item.result.category) {
      try {
        await updateDocument(item.result.id, { category: item.resultCategory, user_id: userId });
      } catch (e) {
        console.error('Failed to update category:', e);
      }
    }
    const finalDoc = { ...item.result, category: item.resultCategory };
    setConfirmedDocs(prev => [...prev, finalDoc]);
    onDocConfirmed?.(finalDoc);

    if (reviewIndex < uploadItems.length - 1) {
      setReviewIndex(prev => prev + 1);
    } else {
      closeModal([...confirmedDocs, finalDoc]);
    }
  }

  function handleSkip() {
    if (reviewIndex < uploadItems.length - 1) {
      setReviewIndex(prev => prev + 1);
    } else {
      closeModal(confirmedDocs);
    }
  }

  function setItemCategory(idx: number, cat: string) {
    setUploadItems(prev => prev.map((it, i) => i === idx ? { ...it, resultCategory: cat } : it));
  }

  async function handleReanalyze() {
    const item = uploadItems[reviewIndex];
    if (!item) return;

    const prevResult = item.result;
    setUploadItems(prev => prev.map((it, i) =>
      i === reviewIndex ? { ...it, status: 'uploading', error: null } : it
    ));

    const fd = new FormData();
    fd.append('file', item.file);
    fd.append('course_id', selectedCourseId);
    fd.append('user_id', userId);

    try {
      const doc = await uploadDocumentWithTimeout(fd);
      if (prevResult && doc.id !== prevResult.id) {
        await deleteDocument(prevResult.id, userId).catch(() => {});
      }
      setUploadItems(prev => prev.map((it, i) =>
        i === reviewIndex ? { ...it, status: 'done', result: doc, resultCategory: doc.category ?? 'other', error: null } : it
      ));
    } catch (e: any) {
      setUploadItems(prev => prev.map((it, i) =>
        i === reviewIndex ? { ...it, status: prevResult ? 'done' : 'error', result: prevResult, error: e.message || 'Re-analysis failed.' } : it
      ));
    }
  }

  function closeModal(uploaded: UploadedDoc[]) {
    setUploadStep('pick');
    setPickedFiles([]);
    setFileError('');
    setSelectedCourseId(initialCourseId ?? '');
    setUploadItems([]);
    setReviewIndex(0);
    setConfirmedDocs([]);
    setShowAddCourse(false);
    setNewCourseName('');
    setCourseAddError('');
    onClose(uploaded);
  }

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
        onCoursesChanged(updated.courses);
        const created = updated.courses.find(c => c.course_id === res.course_id);
        if (created) setSelectedCourseId(created.course_id);
        setNewCourseName('');
        setShowAddCourse(false);
      }
    } catch (e: any) {
      let msg = e.message || 'Failed to add course.';
      try {
        const j = JSON.parse(msg);
        if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      } catch { /* keep msg */ }
      setCourseAddError(msg);
    } finally {
      setCourseAdding(false);
    }
  }

  const hasActiveUploads = uploadItems.some(it => it.status === 'uploading');

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px' }}
      onClick={e => { if (!hasActiveUploads && e.target === e.currentTarget) closeModal(confirmedDocs); }}
    >
      <div style={{ background: '#fff', borderRadius: '12px', padding: '28px', width: '520px', maxWidth: '95vw', maxHeight: '88vh', overflowY: 'auto', position: 'relative', border: '1px solid rgba(107,114,128,0.15)', boxShadow: '0 20px 60px rgba(0,0,0,0.15)', fontFamily: UI_FONT }}>

        {!hasActiveUploads && (
          <button onClick={() => closeModal(confirmedDocs)} style={{ position: 'absolute', top: '16px', right: '16px', background: 'none', border: 'none', fontSize: '18px', cursor: 'pointer', color: '#6b7280', lineHeight: 1, padding: '4px 6px', borderRadius: '4px' }}>✕</button>
        )}

        {uploadStep === 'pick' && (
          <>
            <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>{title}</h2>
            <p style={{ fontSize: '13px', color: '#6b7280', margin: '0 0 20px' }}>{subtitle ?? defaultSubtitle}</p>

            <div
              onDrop={handleDrop}
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: `2px dashed ${dragging ? '#1a5c2a' : 'rgba(107,114,128,0.3)'}`,
                borderRadius: '8px', padding: '28px', textAlign: 'center', cursor: 'pointer',
                background: dragging ? 'rgba(26,92,42,0.04)' : '#fafafa',
                transition: 'all 0.15s', marginBottom: '8px',
              }}
            >
              {pickedFiles.length > 0 ? (
                <>
                  <p style={{ fontSize: '13px', fontWeight: 600, color: '#111827', margin: '0 0 8px' }}>
                    {pickedFiles.length} file{pickedFiles.length > 1 ? 's' : ''} selected
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginBottom: '8px' }}>
                    {pickedFiles.map((f, i) => (
                      <p key={i} style={{ fontSize: '12px', color: '#6b7280', margin: 0 }}>{f.name}</p>
                    ))}
                  </div>
                  <p style={{ fontSize: '12px', color: '#9ca3af', margin: 0 }}>Click to replace</p>
                </>
              ) : (
                <>
                  <p style={{ fontSize: '14px', color: '#6b7280', margin: 0 }}>Drop files here or click to browse</p>
                  <p style={{ fontSize: '12px', color: '#9ca3af', margin: '6px 0 0' }}>PDF, DOCX, PPTX · Up to {MAX_FILES} files · Max 15 MB each</p>
                </>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,.pptx"
              multiple
              style={{ display: 'none' }}
              onChange={e => {
                const files = Array.from(e.target.files || []);
                if (files.length) validateAndSetMultiple(files);
                e.target.value = '';
              }}
            />
            {fileError && <p style={{ fontSize: '12px', color: '#b45309', margin: '4px 0 0' }}>{fileError}</p>}

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
                options={courses.map(c => ({ value: c.course_id, label: c.course_name }))}
                style={{ width: '100%', display: 'block' }}
              />

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

            <button
              onClick={handleUpload}
              disabled={!pickedFiles.length || !selectedCourseId}
              style={{
                marginTop: '20px', width: '100%', padding: '10px',
                background: (!pickedFiles.length || !selectedCourseId) ? '#f3f4f6' : '#1a5c2a',
                color: (!pickedFiles.length || !selectedCourseId) ? '#9ca3af' : '#fff',
                border: 'none', borderRadius: '7px', fontSize: '14px', fontWeight: 600,
                cursor: (!pickedFiles.length || !selectedCourseId) ? 'default' : 'pointer',
                fontFamily: 'inherit', transition: 'background 0.15s',
              }}
            >
              Upload {pickedFiles.length > 1 ? `${pickedFiles.length} Files` : 'File'}
            </button>
          </>
        )}

        {uploadStep === 'reviewing' && (() => {
          const item = uploadItems[reviewIndex];
          const isLast = reviewIndex === uploadItems.length - 1;
          if (!item) return null;

          return (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
                <div>
                  <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#111827', margin: '0 0 2px' }}>Review</h2>
                  <p style={{ fontSize: '13px', color: '#6b7280', margin: 0 }}>
                    {reviewIndex + 1} of {uploadItems.length}
                  </p>
                </div>
                {uploadItems.length > 1 && (
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                    {uploadItems.map((it, i) => (
                      <div key={i} style={{
                        width: i === reviewIndex ? '20px' : '7px',
                        height: '7px',
                        borderRadius: '4px',
                        background: i < reviewIndex
                          ? '#1a5c2a'
                          : i === reviewIndex
                            ? '#1a5c2a'
                            : 'rgba(107,114,128,0.25)',
                        transition: 'all 0.2s',
                        opacity: it.status === 'error' ? 0.4 : 1,
                      }} />
                    ))}
                  </div>
                )}
              </div>

              {item.status === 'uploading' && (
                <div style={{ textAlign: 'center', padding: '40px 0' }}>
                  <div className="sapling-upload-spinner" role="status" aria-live="polite" aria-label="Analyzing document" />
                  <p style={{ fontSize: '15px', fontWeight: 600, color: '#111827', margin: '0' }}>Analyzing…</p>
                  <p style={{ fontSize: '13px', color: '#9ca3af', margin: '6px 0 0', wordBreak: 'break-word' }}>{item.file.name}</p>
                  <p style={{ fontSize: '12px', color: '#9ca3af', margin: '4px 0 0' }}>Large files can take one to several minutes.</p>
                </div>
              )}

              {item.status === 'error' && (
                <>
                  <div style={{ background: 'rgba(220,38,38,0.06)', border: '1px solid rgba(220,38,38,0.2)', borderRadius: '7px', padding: '14px 16px', marginBottom: '20px' }}>
                    <p style={{ fontSize: '13px', fontWeight: 600, color: '#b91c1c', margin: '0 0 4px', wordBreak: 'break-word' }}>{item.file.name}</p>
                    <p style={{ fontSize: '13px', color: '#b91c1c', margin: 0 }}>{item.error}</p>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={handleReanalyze}
                      style={{ flex: 1, padding: '10px', background: '#fff', color: '#374151', border: '1px solid rgba(107,114,128,0.25)', borderRadius: '7px', fontSize: '13px', fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}
                    >
                      Retry
                    </button>
                    <button
                      onClick={handleSkip}
                      style={{ flex: 2, padding: '10px', background: '#f3f4f6', color: '#6b7280', border: 'none', borderRadius: '7px', fontSize: '13px', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
                    >
                      {isLast ? 'Close' : 'Skip'}
                    </button>
                  </div>
                </>
              )}

              {item.status === 'done' && item.result && (
                <>
                  {item.result.category === 'syllabus' && (
                    <div style={{ background: 'rgba(26,92,42,0.07)', border: '1px solid rgba(26,92,42,0.2)', borderRadius: '7px', padding: '10px 14px', marginBottom: '16px', fontSize: '13px', color: '#1a5c2a', fontWeight: 500 }}>
                      Assignments have been added to your calendar.
                    </div>
                  )}

                  <div style={{ ...GLASS, padding: '16px', marginBottom: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <p style={{ fontSize: '14px', fontWeight: 600, color: '#111827', margin: 0, wordBreak: 'break-word' }}>{item.result.file_name}</p>

                    <div>
                      <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 5px' }}>Category</p>
                      <CustomSelect
                        value={item.resultCategory}
                        onChange={cat => setItemCategory(reviewIndex, cat)}
                        options={UPLOAD_CATEGORIES.map(cat => ({ value: cat, label: CATEGORY_LABELS[cat] }))}
                        style={{ width: '100%', display: 'block' }}
                      />
                    </div>

                    {item.result.summary && (
                      <div>
                        <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 5px' }}>Summary</p>
                        <p style={{ fontSize: '13px', color: '#374151', margin: 0, lineHeight: 1.6 }}>{item.result.summary}</p>
                      </div>
                    )}

                    {item.result.key_takeaways && item.result.key_takeaways.length > 0 && (
                      <div>
                        <p style={{ fontSize: '11px', fontWeight: 500, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 5px' }}>Key Takeaways</p>
                        <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {item.result.key_takeaways.map((t, i) => (
                            <li key={i} style={{ fontSize: '13px', color: '#374151', lineHeight: 1.5 }}>{t}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  {item.error && <p style={{ fontSize: '12px', color: '#b91c1c', margin: '0 0 12px' }}>{item.error}</p>}

                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={handleReanalyze}
                      style={{ flex: 1, padding: '10px', background: '#fff', color: '#374151', border: '1px solid rgba(107,114,128,0.25)', borderRadius: '7px', fontSize: '13px', fontWeight: 500, cursor: 'pointer', fontFamily: 'inherit' }}
                    >
                      Re-analyze
                    </button>
                    <button
                      onClick={handleConfirm}
                      style={{ flex: 2, padding: '10px', background: '#1a5c2a', color: '#fff', border: 'none', borderRadius: '7px', fontSize: '14px', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
                    >
                      {isLast ? 'Save' : 'Confirm & Next →'}
                    </button>
                  </div>
                </>
              )}
            </>
          );
        })()}
      </div>
    </div>
  );
}
