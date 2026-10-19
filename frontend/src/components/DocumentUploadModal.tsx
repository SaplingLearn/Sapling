"use client";

import React from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { CustomSelect } from "./CustomSelect";
import { useOverlayBehaviour } from "./Dialog";
import { useToast } from "./ToastProvider";
import { BotanicalIcon, SaplingAction, StatusMessage } from "@/components/sapling";
import {
  uploadDocumentStream,
  updateDocumentCategory,
  addCourse,
  onboardingCoursesSearch,
  type EnrolledCourse,
  type OnboardingCourse,
  type UploadEvent,
} from "@/lib/api";
import styles from "./DocumentUploadModal.module.css";

const MAX_FILES = 5;
const MAX_SIZE = 100 * 1024 * 1024;
const ALLOWED = /\.(pdf|docx|pptx)$/i;
const UPLOAD_TIMEOUT_MS = 4 * 60 * 1000;
/** AbortController reason for a learner-initiated cancel (vs the timeout). */
const CANCEL_REASON = "cancelled";

type UploadStatus = "pending" | "uploading" | "processed" | "error" | "aborted" | "cancelled";

/**
 * Where an uploading row is. "sending" lasts until the server's first SSE
 * event (the file has arrived); "processing" is the server-side pipeline,
 * which only ends with the `result` event. Transport finishing is never
 * shown as the file being ready.
 */
type UploadPhase = "sending" | "processing";

export interface UploadItem {
  id: string;
  file: File;
  courseId: string;
  status: UploadStatus;
  phase?: UploadPhase;
  /** 1-based pipeline stage reported by the server's step names. */
  stage?: number;
  error?: string;
  docId?: string;
  category?: string;
  summary?: string;
  conceptNames?: string[];
  abort?: AbortController;
  /** Latest progress message from the SSE stream (visible while uploading). */
  progress?: string;
  /**
   * X-Request-ID minted for the current upload attempt. Captured before the
   * stream starts so a failed row can surface a "Reference: …" line for
   * support, and so retries can mint a fresh ID (the backend's idempotency
   * cache would otherwise short-circuit on the failed one).
   */
  requestId?: string;
}

interface Props {
  open: boolean;
  userId: string;
  courses: EnrolledCourse[];
  onClose: () => void;
  onComplete: (uploaded: UploadItem[]) => void;
}

/** The slice of a course the per-file dropdown + inline-add flow need. */
type CourseOption = Pick<EnrolledCourse, "course_id" | "course_code" | "course_name">;

const CATEGORY_OPTIONS = [
  { value: "syllabus", label: "Syllabus" },
  { value: "lecture_notes", label: "Lecture notes" },
  { value: "slides", label: "Slides" },
  { value: "reading", label: "Reading" },
  { value: "assignment", label: "Assignment" },
  { value: "study_guide", label: "Study guide" },
  { value: "other", label: "Other" },
];

/** The server pipeline's step names (routes/documents.py upload stream),
 *  grouped into the stages a learner can follow. */
export const PIPELINE_STAGES = ["Received", "Reading", "Classifying", "Summarizing", "Linking concepts"] as const;
const STEP_STAGE: Record<string, number> = {
  start: 1,
  extracting_text: 2, extracted_text: 2,
  classify: 3, classified: 3,
  extract: 4, extracted: 4,
  graph_update: 5, graph_updated: 5, finalize: 5,
};

interface Rejected { name: string; reason: string }

export function DocumentUploadModal({ open, userId, courses, onClose, onComplete }: Props) {
  const toast = useToast();
  const [items, setItems] = React.useState<UploadItem[]>([]);
  const [rejected, setRejected] = React.useState<Rejected[]>([]);
  const [dragging, setDragging] = React.useState(false);
  const [courseQuery, setCourseQuery] = React.useState("");
  const [courseResults, setCourseResults] = React.useState<OnboardingCourse[]>([]);
  const [addingCourse, setAddingCourse] = React.useState(false);
  // Courses added inline this session (#186). `courses` is a read-only prop
  // the parent only refreshes via onComplete (fired at done/close), so a
  // just-added course must be merged locally to be selectable right away.
  const [extraCourses, setExtraCourses] = React.useState<CourseOption[]>([]);


  React.useEffect(() => {
    if (!open) {
      setItems([]);
      setRejected([]);
      setCourseQuery("");
      setCourseResults([]);
      setExtraCourses([]);
    }
  }, [open]);

  React.useEffect(() => {
    if (!courseQuery.trim()) { setCourseResults([]); return; }
    const t = setTimeout(() => {
      onboardingCoursesSearch(courseQuery).then(r => setCourseResults(r.courses ?? [])).catch(() => setCourseResults([]));
    }, 200);
    return () => clearTimeout(t);
  }, [courseQuery]);

  const allCourses = React.useMemo<CourseOption[]>(() => {
    const seen = new Set(courses.map(c => c.course_id));
    return [...courses, ...extraCourses.filter(c => !seen.has(c.course_id))];
  }, [courses, extraCourses]);

  const activeUploads = items.filter(it => it.status === "uploading").length;
  const processedCount = items.filter(it => it.status === "processed").length;
  const failedCount = items.filter(it => it.status === "error" || it.status === "aborted" || it.status === "cancelled").length;

  const handleClose = () => {
    if (activeUploads > 0) {
      if (!window.confirm(`${activeUploads} upload${activeUploads === 1 ? "" : "s"} still running. Abort and close?`)) return;
      items.forEach(it => it.abort?.abort(CANCEL_REASON));
    }
    // Files that already finished stay saved; let the library pick them up
    // even when the learner leaves through Close/Cancel instead of Done.
    if (items.some(it => it.status === "processed")) onComplete(items);
    onClose();
  };

  const courseSearchRef = React.useRef<HTMLInputElement>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const { mounted, panelRef, onKeyDown } = useOverlayBehaviour({ open, onClose: handleClose, initialFocusRef: courseSearchRef });
  const titleId = React.useId();
  const limitsId = React.useId();

  const addFiles = (fileList: File[]) => {
    const defaultCourseId = allCourses[0]?.course_id || "";
    const room = Math.max(0, MAX_FILES - items.length);
    const nextRejected: Rejected[] = fileList.slice(room).map(f => ({
      name: f.name,
      reason: `not added: at most ${MAX_FILES} files per upload.`,
    }));
    const candidates = fileList
      .slice(0, room)
      .filter(f => {
        if (!ALLOWED.test(f.name)) {
          toast.error(`${f.name}: only PDF / DOCX / PPTX are accepted.`);
          nextRejected.push({ name: f.name, reason: "only PDF / DOCX / PPTX are accepted." });
          return false;
        }
        if (f.size > MAX_SIZE) {
          toast.error(`${f.name}: exceeds the 100 MB limit.`);
          nextRejected.push({ name: f.name, reason: "exceeds the 100 MB limit." });
          return false;
        }
        return true;
      })
      .map<UploadItem>(f => ({
        id: `${f.name}-${f.size}-${f.lastModified}-${Math.random().toString(36).slice(2, 6)}`,
        file: f,
        courseId: defaultCourseId,
        status: "pending",
      }));
    setRejected(nextRejected);
    if (candidates.length === 0) return;
    setItems(prev => [...prev, ...candidates]);
  };

  const startUpload = async (item: UploadItem) => {
    if (!item.courseId) {
      setItems(prev => prev.map(i => i.id === item.id ? { ...i, status: "error", error: "Pick a course first." } : i));
      return;
    }
    const ac = new AbortController();
    const timeout = setTimeout(() => ac.abort(), UPLOAD_TIMEOUT_MS);
    // Mint a fresh request_id per attempt so retries don't collide with the
    // backend's idempotency cache (which keys on X-Request-ID).
    const requestId =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `up-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    setItems(prev => prev.map(i => i.id === item.id ? {
      ...i, status: "uploading", phase: "sending", stage: 0, abort: ac, progress: "Sending file…", requestId,
    } : i));
    // The terminal in-band failure message, so the row shows the server's
    // reason instead of the generic "stream ended" error the client throws.
    let inBandFailure: string | null = null;
    let reachedServer = false;
    try {
      const fd = new FormData();
      fd.append("file", item.file);
      fd.append("course_id", item.courseId);
      fd.append("user_id", userId);
      const resp = await uploadDocumentStream(fd, (ev: UploadEvent) => {
        reachedServer = true;
        // Mirror backend SaplingEvent.message into the row's live label.
        if (ev.type === "status" && ev.step === "done") return; // final state covered below

        // Capture any backend-supplied request_id (matches what we sent, but
        // some events may carry the canonical one if the backend re-issues).
        const evRid = (ev.data as { request_id?: unknown } | undefined)?.request_id;
        if (typeof evRid === "string" && evRid.length > 0) {
          setItems(prev => prev.map(i => i.id === item.id ? { ...i, requestId: evRid } : i));
        }

        if (ev.type === "error") {
          // The streaming route's only error step is "failed" — terminal
          // (#151b retired the legacy pipeline and its step === "fallback"
          // event with it). Anything else we treat as informational and skip
          // toasting to avoid double-firing alongside the catch-block toast.
          if (ev.step === "failed") {
            inBandFailure = ev.message;
            toast.error(`Upload failed: ${ev.message}`);
          }
          setItems(prev => prev.map(i => i.id === item.id ? { ...i, phase: "processing", progress: ev.message } : i));
          return;
        }

        const stage = STEP_STAGE[ev.step];
        setItems(prev => prev.map(i => i.id === item.id ? {
          ...i,
          phase: "processing",
          progress: ev.message,
          stage: stage ? Math.max(stage, i.stage ?? 0) : Math.max(1, i.stage ?? 0),
        } : i));
      }, ac.signal, requestId);
      clearTimeout(timeout);
      setItems(prev => prev.map(i => i.id === item.id ? {
        ...i,
        status: "processed",
        phase: undefined,
        progress: undefined,
        docId: resp?.id,
        category: resp?.classification?.category || resp?.category || "other",
        summary: resp?.summary?.abstract ?? resp?.summary,
        conceptNames: extractConceptNames(resp),
      } : i));
    } catch (err: any) {
      clearTimeout(timeout);
      const aborted = ac.signal.aborted;
      const cancelled = aborted && ac.signal.reason === CANCEL_REASON;
      const errorMsg = cancelled
        ? reachedServer
          ? "Cancelled. The server had already received this file, so it may still finish and appear in your library after a refresh."
          : "Cancelled before the file was sent."
        : aborted
          ? "Processing took longer than 4 minutes — try a smaller file."
          : inBandFailure ?? String(err?.message || err);
      setItems(prev => prev.map(i => i.id === item.id ? {
        ...i,
        status: cancelled ? "cancelled" : aborted ? "aborted" : "error",
        phase: undefined,
        progress: undefined,
        error: errorMsg,
      } : i));
      // Toast on terminal stream failure (the catch covers cases where the
      // SSE stream throws or aborts, distinct from in-band error events).
      if (!aborted) toast.error(`Upload failed: ${errorMsg}`);
    }
  };

  const startAll = () => {
    items.filter(i => i.status === "pending").forEach(i => { void startUpload(i); });
  };

  const reanalyze = (item: UploadItem) => {
    setItems(prev => prev.map(i => i.id === item.id ? { ...i, status: "pending", error: undefined } : i));
    void startUpload({ ...item, status: "pending" });
  };

  /**
   * Retry a failed or aborted upload. Resets the row to a clean "pending"
   * state — including clearing the previous requestId so startUpload mints
   * a fresh one (the old one would short-circuit in the backend's
   * idempotency cache).
   */
  const retry = (item: UploadItem) => {
    setItems(prev => prev.map(i => i.id === item.id ? {
      ...i,
      status: "pending",
      error: undefined,
      progress: undefined,
      requestId: undefined,
    } : i));
    void startUpload({
      ...item,
      status: "pending",
      error: undefined,
      progress: undefined,
      requestId: undefined,
    });
  };

  const setItemField = (id: string, updater: (prev: UploadItem) => UploadItem) => {
    setItems(prev => prev.map(i => i.id === id ? updater(i) : i));
  };

  const handleCategoryChange = async (item: UploadItem, next: string) => {
    setItemField(item.id, prev => ({ ...prev, category: next }));
    if (item.docId) {
      try {
        await updateDocumentCategory(item.docId, userId, next);
        toast.success("Category updated");
      } catch (err) {
        toast.error(`Failed: ${String(err)}`);
      }
    }
  };

  const addCourseInline = async (course: OnboardingCourse) => {
    setAddingCourse(true);
    try {
      const resp = await addCourse(userId, course.id);
      toast.success(`Added ${course.course_code}`);
      setCourseQuery("");
      setCourseResults([]);
      // Parent refreshes courses via onComplete (fired at done/close), so
      // merge the new course locally to make it selectable this session.
      const courseId = resp?.course_id || course.id;
      setExtraCourses(prev => prev.some(c => c.course_id === courseId)
        ? prev
        : [...prev, { course_id: courseId, course_code: course.course_code, course_name: course.course_name }]);
    } catch (err) {
      toast.error(`Failed: ${String(err)}`);
    } finally {
      setAddingCourse(false);
    }
  };

  const allFinished = items.length > 0 && items.every(i => i.status !== "uploading" && i.status !== "pending");

  const done = () => {
    onComplete(items);
    onClose();
  };

  if (!open || !mounted) return null;

  return createPortal(
    <div className={`sapling-surface ${styles.backdrop}`} onClick={handleClose}>
      <div
        data-testid="upload-modal"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={limitsId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        onClick={e => e.stopPropagation()}
        className={`slide-up ${styles.panel}`}
      >
        <div className={styles.header}>
          <div>
            <p className="sapling-eyebrow">Upload</p>
            <h2 id={titleId} className={styles.title}>Add course materials</h2>
          </div>
          <button data-testid="upload-modal-close" type="button" className={styles.iconButton} onClick={handleClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div className={styles.body}>
          <div
            data-testid="upload-modal-dropzone"
            className={styles.dropzone}
            data-dragging={dragging || undefined}
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => {
              e.preventDefault();
              setDragging(false);
              addFiles(Array.from(e.dataTransfer.files));
            }}
          >
            <BotanicalIcon name="paper" size={30} className={styles.paper} />
            <p className={styles.dropTitle}>
              {dragging ? "Drop to add files" : "Drag & drop up to 5 files"}
            </p>
            <p id={limitsId} className={styles.dropLimits}>
              PDF, DOCX, PPTX · max 100 MB each
            </p>
            <label data-testid="upload-modal-browse" className={`btn btn--primary sapling-action sapling-action--primary ${styles.browse}`}
              role="button" tabIndex={0} aria-label="Browse files"
              onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInputRef.current?.click(); } }}>
              <Icon name="up" size={14} /> Browse
              <input
                data-testid="upload-modal-file-input"
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.docx,.pptx"
                hidden
                onChange={e => {
                  if (e.target.files) addFiles(Array.from(e.target.files));
                  e.target.value = "";
                }}
              />
            </label>
          </div>

          {rejected.length > 0 && (
            <div className={styles.block}>
              <StatusMessage tone="error" title="Some files weren't added" testid="upload-modal-rejected">
                <ul className={styles.rejectedList}>
                  {rejected.map((r, i) => (
                    <li key={`${r.name}-${i}`}><span className={styles.fileName}>{r.name}</span>: {r.reason}</li>
                  ))}
                </ul>
              </StatusMessage>
            </div>
          )}

          {allCourses.length === 0 && (
            <div className={styles.block}>
              <StatusMessage tone="info" title="Add a course first" testid="upload-modal-no-course">
                Every material is saved to a course. Search for yours below, then pick it for each file.
              </StatusMessage>
            </div>
          )}

          {allCourses.length < 10 && (
            <div className={styles.block}>
              <label htmlFor={`${titleId}-course-search`} className={styles.label}>+ Add a course</label>
              <input
                id={`${titleId}-course-search`}
                data-testid="upload-modal-course-search"
                aria-label="Search for a course to add"
                ref={courseSearchRef}
                value={courseQuery}
                onChange={e => setCourseQuery(e.target.value)}
                placeholder="Search a course to add"
                className={styles.input}
              />
              {courseResults.length > 0 && (
                <div className={styles.results}>
                  {courseResults.map(c => (
                    <button
                      key={c.id}
                      type="button"
                      data-testid={`upload-modal-course-result-${c.id}`}
                      disabled={addingCourse}
                      onClick={() => addCourseInline(c)}
                      className={styles.result}
                    >
                      <span><strong>{c.course_code}</strong> · {c.course_name}</span>
                      <Icon name="plus" size={12} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className={styles.block}>
            {items.length === 0 && (
              <p className={styles.muted}>Files you add will appear here.</p>
            )}
            <ul className={styles.files}>
              {items.map((item, idx) => {
                const fileTitleId = `${item.id}-name`;
                return (
                  <li
                    key={item.id}
                    data-testid={`upload-modal-file-row-${idx}`}
                    data-status={item.status}
                    className={styles.file}
                  >
                    <div className={styles.fileHead}>
                      <BotanicalIcon name="paper" size={22} className={styles.paper} />
                      <div className={styles.fileText}>
                        <div id={fileTitleId} className={styles.fileName}>{item.file.name}</div>
                        <div className={styles.muted}>
                          {(item.file.size / 1024 / 1024).toFixed(1)} MB · {item.file.name.split(".").pop()?.toUpperCase()}
                        </div>
                      </div>
                      <StatusBadge status={item.status} phase={item.phase} />
                      {item.status === "uploading" ? (
                        <button
                          type="button"
                          data-testid={`upload-modal-file-cancel-${idx}`}
                          className={styles.textButton}
                          onClick={() => item.abort?.abort(CANCEL_REASON)}
                          aria-label={`Cancel uploading ${item.file.name}`}
                        >
                          Cancel
                        </button>
                      ) : (
                        <button
                          type="button"
                          data-testid={`upload-modal-file-remove-${idx}`}
                          className={styles.iconButton}
                          aria-label={`Remove ${item.file.name}`}
                          onClick={() => setItems(prev => prev.filter(i => i.id !== item.id))}
                        >
                          <Icon name="x" size={12} />
                        </button>
                      )}
                    </div>
                    <div className={styles.fileControls}>
                      <span className={styles.muted}>Course:</span>
                      <CustomSelect
                        size="sm"
                        value={item.courseId || ""}
                        onChange={(v) => setItemField(item.id, p => ({ ...p, courseId: v }))}
                        placeholder="Pick a course"
                        ariaLabel="Course"
                        disabled={item.status === "uploading"}
                        options={allCourses.map(c => ({ value: c.course_id, label: c.course_code || c.course_name }))}
                      />
                      {item.status === "processed" && (
                        <>
                          <span className={styles.muted}>Category:</span>
                          <CustomSelect
                            size="sm"
                            value={item.category || "other"}
                            onChange={(v) => handleCategoryChange(item, v)}
                            options={CATEGORY_OPTIONS}
                            ariaLabel="Category"
                          />
                          <button type="button" data-testid={`upload-modal-file-reanalyze-${idx}`} className={styles.textButton} onClick={() => reanalyze(item)}>
                            <Icon name="sparkle" size={12} /> Re-analyze
                          </button>
                        </>
                      )}
                      {(item.status === "error" || item.status === "aborted" || item.status === "cancelled") && (
                        <button type="button" data-testid={`upload-modal-file-retry-${idx}`} className={styles.textButton} onClick={() => retry(item)}>
                          <Icon name="sparkle" size={12} /> Retry
                        </button>
                      )}
                    </div>
                    {item.status === "uploading" && (
                      <UploadProgress item={item} testid={`upload-modal-file-progress-${idx}`} />
                    )}
                    {item.summary && (
                      <p className={styles.summary}>{item.summary}</p>
                    )}
                    {item.conceptNames && item.conceptNames.length > 0 && (
                      <div className={styles.chips}>
                        {item.conceptNames.slice(0, 4).map(t => (
                          <span key={t} className={styles.chip}>{t}</span>
                        ))}
                      </div>
                    )}
                    {item.error && (
                      <p className={styles.error} data-testid={`upload-modal-file-error-${idx}`}>
                        <span aria-hidden="true">⚠ </span>{item.error}
                      </p>
                    )}
                    {item.status === "error" && item.requestId && (
                      <div className={styles.reference}>
                        <span>Reference: {item.requestId.slice(0, 8)}…</span>
                        <button
                          type="button"
                          data-testid={`upload-modal-file-copy-request-id-${idx}`}
                          onClick={() => {
                            const rid = item.requestId || "";
                            if (navigator.clipboard) {
                              navigator.clipboard.writeText(rid).then(
                                () => toast.info("Copied"),
                                () => toast.error("Couldn't copy"),
                              );
                            }
                          }}
                          className={styles.textButton}
                        >
                          copy
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>

        <div className={styles.footer}>
          <p className={styles.muted} aria-live="polite" data-testid="upload-modal-summary">
            {items.length} file{items.length === 1 ? "" : "s"} queued
            {activeUploads > 0 && ` · ${activeUploads} uploading`}
            {allFinished && processedCount > 0 && failedCount > 0 &&
              ` · ${processedCount} saved, ${failedCount} not saved (retry above)`}
          </p>
          <div className={styles.footerActions}>
            <SaplingAction tone="quiet" data-testid="upload-modal-cancel" onClick={handleClose}>Cancel</SaplingAction>
            {allFinished ? (
              <SaplingAction data-testid="upload-modal-done" onClick={done}>Done</SaplingAction>
            ) : (
              <SaplingAction
                data-testid="upload-modal-submit"
                disabled={items.length === 0 || items.every(i => i.status !== "pending")}
                onClick={startAll}
              >
                <Icon name="up" size={14} /> Start upload
              </SaplingAction>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function UploadProgress({ item, testid }: { item: UploadItem; testid: string }) {
  const sending = item.phase !== "processing";
  const stage = Math.min(item.stage ?? 0, PIPELINE_STAGES.length);
  const label = sending
    ? "Sending file to Sapling…"
    : `Processing on Sapling · step ${Math.max(stage, 1)} of ${PIPELINE_STAGES.length}: ${PIPELINE_STAGES[Math.max(stage, 1) - 1]}`;
  return (
    <div className={styles.progress} data-testid={testid} data-phase={sending ? "sending" : "processing"}>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-label={`Upload progress for ${item.file.name}`}
        aria-valuemin={0}
        aria-valuemax={PIPELINE_STAGES.length}
        aria-valuenow={sending ? 0 : Math.max(stage, 1)}
        aria-valuetext={label}
      >
        <span
          className={styles.progressFill}
          data-indeterminate={sending || undefined}
          style={{ width: sending ? undefined : `${(Math.max(stage, 1) / (PIPELINE_STAGES.length + 1)) * 100}%` }}
        />
      </div>
      <p className={styles.progressLabel}>{label}</p>
      {!sending && item.progress && (
        <p aria-live="polite" className={styles.progressMessage}>{item.progress}</p>
      )}
    </div>
  );
}

/**
 * Pull concept names out of either the orchestrator result shape
 * ({ concepts: { concepts: [{ name, ... }] } }) or the persisted-row
 * shape ({ concept_notes: [{ name }] }) that idempotent replays and
 * /upload/sync responses carry. Returns at most a flat string[].
 */
function extractConceptNames(resp: any): string[] {
  const fromOrchestrator = resp?.concepts?.concepts;
  if (Array.isArray(fromOrchestrator)) {
    return fromOrchestrator
      .map((c: { name?: unknown }) => c?.name)
      .filter((n: unknown): n is string => typeof n === "string" && n.length > 0);
  }
  const fromRow = resp?.concept_notes;
  if (Array.isArray(fromRow)) {
    return fromRow
      .map((n: { name?: unknown }) => n?.name)
      .filter((n: unknown): n is string => typeof n === "string" && n.length > 0);
  }
  return [];
}

function StatusBadge({ status, phase }: { status: UploadStatus; phase?: UploadPhase }) {
  const meta = statusMeta(status, phase);
  return (
    <span className={styles.badge} data-tone={meta.tone}>
      {meta.label}
    </span>
  );
}

function statusMeta(s: UploadStatus, phase?: UploadPhase): { label: string; tone: string } {
  switch (s) {
    case "pending": return { label: "Queued", tone: "neutral" };
    case "uploading": return phase === "processing"
      ? { label: "Processing…", tone: "pending" }
      : { label: "Sending…", tone: "pending" };
    case "processed": return { label: "Saved", tone: "success" };
    case "aborted": return { label: "Timed out", tone: "error" };
    case "cancelled": return { label: "Cancelled", tone: "neutral" };
    case "error": return { label: "Failed", tone: "error" };
  }
}
