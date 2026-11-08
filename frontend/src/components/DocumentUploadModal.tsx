"use client";

import React from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { CustomSelect } from "./CustomSelect";
import { useScrollLock } from "@/lib/useScrollLock";
import { useToast } from "./ToastProvider";
import {
  uploadDocumentStream,
  updateDocumentCategory,
  addCourse,
  onboardingCoursesSearch,
  type EnrolledCourse,
  type OnboardingCourse,
  type UploadEvent,
  type UploadResultData,
} from "@/lib/api";

const MAX_FILES = 5;
const MAX_SIZE = 100 * 1024 * 1024;
const ALLOWED = /\.(pdf|docx|pptx)$/i;
const UPLOAD_TIMEOUT_MS = 4 * 60 * 1000;
const TIMEOUT_MESSAGE = "Processing took longer than 4 minutes — try a smaller file.";
const CANCELLED_MESSAGE = "Upload cancelled.";

/**
 * Why an upload's AbortController fired (#759): the 4-minute timer, or the
 * user closing the modal / the parent closing it. Kept beside the controller
 * rather than read off `signal.reason`, which not every runtime carries.
 */
type AbortReason = "timeout" | "cancelled";
const abortReasons = new WeakMap<AbortController, AbortReason>();
function abortWith(ac: AbortController, reason: AbortReason) {
  if (!abortReasons.has(ac)) abortReasons.set(ac, reason);
  ac.abort();
}

function mintRequestId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `up-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

type UploadStatus = "pending" | "uploading" | "processed" | "error" | "aborted";

interface UploadItem {
  id: string;
  file: File;
  courseId: string;
  status: UploadStatus;
  error?: string;
  docId?: string;
  category?: string;
  summary?: string;
  conceptNames?: string[];
  abort?: AbortController;
  /** Latest progress message from the SSE stream (visible while uploading). */
  progress?: string;
  /**
   * X-Request-ID of the current upload attempt, surfaced on a failed row as
   * "Reference: …" for support. Retry of the SAME file to the SAME course
   * reuses it (#759), so a document the server saved after the client gave
   * up (timeout, dropped connection) comes back through the backend's
   * idempotent replay instead of being processed twice; a failure persists
   * nothing, so a reused id simply re-runs. Re-analyze mints a fresh one.
   */
  requestId?: string;
  /** The course `requestId` was minted for; a course change mints anew. */
  requestCourseId?: string;
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

export function DocumentUploadModal({ open, userId, courses, onClose, onComplete }: Props) {
  const toast = useToast();
  const [mounted, setMounted] = React.useState(false);
  const [items, setItems] = React.useState<UploadItem[]>([]);
  const [dragging, setDragging] = React.useState(false);
  const [courseQuery, setCourseQuery] = React.useState("");
  const [courseResults, setCourseResults] = React.useState<OnboardingCourse[]>([]);
  const [addingCourse, setAddingCourse] = React.useState(false);
  // Courses added inline this session (#186). `courses` is a read-only prop
  // the parent only refreshes via onComplete (fired at done/close), so a
  // just-added course must be merged locally to be selectable right away.
  const [extraCourses, setExtraCourses] = React.useState<CourseOption[]>([]);

  // Every in-flight upload's controller, so any route that closes the modal
  // — including the parent flipping `open` itself — aborts them (#759).
  const controllersRef = React.useRef(new Set<AbortController>());
  const abortAll = React.useCallback(() => {
    controllersRef.current.forEach(ac => abortWith(ac, "cancelled"));
    controllersRef.current.clear();
  }, []);

  React.useEffect(() => setMounted(true), []);
  React.useEffect(() => abortAll, [abortAll]);

  useScrollLock(open);

  React.useEffect(() => {
    if (!open) {
      abortAll();
      setItems([]);
      setCourseQuery("");
      setCourseResults([]);
      setExtraCourses([]);
    }
  }, [open, abortAll]);

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

  /**
   * Every close route (Done, Cancel, X, backdrop) ends here (#759): abort
   * what is still running, and tell the parent to refresh whenever this
   * session changed something it shows — a processed upload, or a course
   * added inline. onComplete receives the processed rows only.
   */
  const finish = () => {
    abortAll();
    const processed = items.filter(i => i.status === "processed");
    if (processed.length > 0 || extraCourses.length > 0) onComplete(processed);
    onClose();
  };

  const handleClose = () => {
    if (activeUploads > 0) {
      if (!window.confirm(`${activeUploads} upload${activeUploads === 1 ? "" : "s"} still running. Abort and close?`)) return;
    }
    finish();
  };

  const addFiles = (fileList: File[]) => {
    const defaultCourseId = allCourses[0]?.course_id || "";
    const candidates = fileList
      .slice(0, MAX_FILES - items.length)
      .filter(f => {
        if (!ALLOWED.test(f.name)) {
          toast.error(`${f.name}: only PDF / DOCX / PPTX are accepted.`);
          return false;
        }
        if (f.size > MAX_SIZE) {
          toast.error(`${f.name}: exceeds the 100 MB limit.`);
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
    if (candidates.length === 0) return;
    setItems(prev => [...prev, ...candidates]);
  };

  const startUpload = async (item: UploadItem, opts: { reuseRequestId?: boolean } = {}) => {
    if (!item.courseId) {
      setItems(prev => prev.map(i => i.id === item.id ? { ...i, status: "error", error: "Pick a course first." } : i));
      return;
    }
    const ac = new AbortController();
    controllersRef.current.add(ac);
    const timeout = setTimeout(() => abortWith(ac, "timeout"), UPLOAD_TIMEOUT_MS);
    const requestId =
      opts.reuseRequestId && item.requestId && item.requestCourseId === item.courseId
        ? item.requestId
        : mintRequestId();
    // Every attempt starts from a clean row: a re-analyze must not keep the
    // previous run's docId/summary/concepts on screen (#759).
    setItems(prev => prev.map(i => i.id === item.id ? {
      ...i,
      status: "uploading", abort: ac, progress: "Starting upload…",
      requestId, requestCourseId: item.courseId,
      error: undefined, docId: undefined, category: undefined,
      summary: undefined, conceptNames: undefined,
    } : i));
    const settle = (patch: Partial<UploadItem>) =>
      setItems(prev => prev.map(i => i.id === item.id ? { ...i, progress: undefined, ...patch } : i));
    try {
      const fd = new FormData();
      fd.append("file", item.file);
      fd.append("course_id", item.courseId);
      fd.append("user_id", userId);
      const outcome = await uploadDocumentStream(fd, (ev: UploadEvent) => {
        // Terminal events are read off the resolved outcome below; the row
        // only mirrors the live message here (no toasts — one per failure).
        if (ev.type === "status" && ev.step === "done") return;
        const evRid = (ev.data as { request_id?: unknown } | undefined)?.request_id;
        setItems(prev => prev.map(i => i.id === item.id ? {
          ...i,
          progress: ev.message,
          ...(typeof evRid === "string" && evRid.length > 0 ? { requestId: evRid } : {}),
        } : i));
      }, ac.signal, requestId);
      if (outcome.kind === "processed") {
        const resp = outcome.result;
        settle({
          status: "processed",
          docId: outcome.documentId,
          category: resp.classification?.category || "other",
          summary: resp.summary?.abstract || undefined,
          conceptNames: extractConceptNames(resp),
        });
      } else {
        // The server's error is the row's error, shown once (#759) — also
        // after a `result`: that means nothing was saved.
        settle({
          status: "error",
          error: outcome.message,
          ...(outcome.requestId ? { requestId: outcome.requestId } : {}),
        });
        toast.error(`Upload failed: ${outcome.message}`);
      }
    } catch (err: unknown) {
      const reason = abortReasons.get(ac);
      if (reason) {
        settle({ status: "aborted", error: reason === "timeout" ? TIMEOUT_MESSAGE : CANCELLED_MESSAGE });
      } else {
        const errorMsg = String((err as { message?: unknown } | null)?.message || err);
        settle({ status: "error", error: errorMsg });
        toast.error(`Upload failed: ${errorMsg}`);
      }
    } finally {
      clearTimeout(timeout);
      controllersRef.current.delete(ac);
    }
  };

  const startAll = () => {
    items.filter(i => i.status === "pending").forEach(i => { void startUpload(i); });
  };

  /** Re-run a processed file as a NEW analysis: fresh request id, clean row. */
  const reanalyze = (item: UploadItem) => {
    void startUpload(item);
  };

  /**
   * Retry a failed or aborted upload. Reuses the attempt's request id while
   * the course is unchanged, so a document the server saved after the client
   * gave up is replayed rather than processed twice (#759).
   */
  const retry = (item: UploadItem) => {
    void startUpload(item, { reuseRequestId: true });
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

  if (!open || !mounted) return null;

  return createPortal(
    <div
      onClick={handleClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(25, 37, 11,0.45)",
        zIndex: 200, display: "grid", placeItems: "center", padding: 20,
      }}
    >
      <div
        data-testid="upload-modal"
        onClick={e => e.stopPropagation()}
        className="card slide-up"
        style={{ width: "min(720px, 100%)", maxHeight: "88vh", overflow: "hidden", padding: 0, display: "flex", flexDirection: "column" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
          <div>
            <div className="label-micro">Upload</div>
            <div className="h-serif" style={{ fontSize: 20 }}>Add course materials</div>
          </div>
          <button data-testid="upload-modal-close" className="btn btn--ghost btn--sm" onClick={handleClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div style={{ padding: 20, overflowY: "auto" }}>
          <div
            data-testid="upload-modal-dropzone"
            onDragOver={e => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={e => {
              e.preventDefault();
              setDragging(false);
              addFiles(Array.from(e.dataTransfer.files));
            }}
            style={{
              border: `2px dashed ${dragging ? "var(--accent)" : "var(--border-strong)"}`,
              borderRadius: "var(--r-md)", padding: 28, textAlign: "center",
              background: dragging ? "var(--accent-soft)" : "var(--bg-subtle)",
              transition: "all var(--dur-fast) var(--ease)",
            }}
          >
            <div className="h-serif" style={{ fontSize: 17, marginBottom: 6 }}>
              {dragging ? "Drop to add files" : "Drag & drop up to 5 files"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
              PDF, DOCX, PPTX · max 100 MB each
            </div>
            <label data-testid="upload-modal-browse" className="btn btn--primary btn--sm">
              <Icon name="upload" size={12} /> Browse
              <input
                data-testid="upload-modal-file-input"
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

          {allCourses.length < 10 && (
            <div style={{ marginTop: 16 }}>
              <div className="label-micro" style={{ marginBottom: 6 }}>+ Add a course</div>
              <input
                data-testid="upload-modal-course-search"
                value={courseQuery}
                onChange={e => setCourseQuery(e.target.value)}
                placeholder="Search a course to add"
                style={{
                  width: "100%", padding: "7px 12px", fontSize: 13,
                  border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
                  background: "var(--bg-input)",
                }}
              />
              {courseResults.length > 0 && (
                <div style={{ marginTop: 6, border: "1px solid var(--border)", borderRadius: "var(--r-sm)", maxHeight: 140, overflowY: "auto" }}>
                  {courseResults.map(c => (
                    <button
                      key={c.id}
                      data-testid={`upload-modal-course-result-${c.id}`}
                      disabled={addingCourse}
                      onClick={() => addCourseInline(c)}
                      style={{
                        width: "100%", padding: "7px 12px", fontSize: 12,
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                        borderBottom: "1px solid var(--border)", textAlign: "left",
                      }}
                    >
                      <span><strong>{c.course_code}</strong> · {c.course_name}</span>
                      <Icon name="plus" size={12} />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <div style={{ marginTop: 20 }}>
            {items.length === 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Files you add will appear here.</div>
            )}
            {items.map((item, idx) => (
              <div
                key={item.id}
                data-testid={`upload-modal-file-row-${idx}`}
                className="card"
                style={{ padding: 14, marginBottom: 10, display: "flex", flexDirection: "column", gap: 10 }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <div style={{
                    width: 28, height: 36, borderRadius: "var(--r-xs)",
                    background: "var(--accent-soft)", color: "var(--accent)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    <Icon name="doc" size={14} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.file.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {(item.file.size / 1024 / 1024).toFixed(1)} MB · {item.file.name.split(".").pop()?.toUpperCase()}
                    </div>
                  </div>
                  <StatusBadge status={item.status} />
                  <button
                    data-testid={`upload-modal-file-remove-${idx}`}
                    className="btn btn--ghost btn--sm"
                    disabled={item.status === "uploading"}
                    onClick={() => {
                      if (item.status === "uploading") item.abort?.abort();
                      setItems(prev => prev.filter(i => i.id !== item.id));
                    }}
                  >
                    <Icon name="x" size={12} />
                  </button>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Course:</span>
                  <CustomSelect
                    size="sm"
                    value={item.courseId || ""}
                    onChange={(v) => setItemField(item.id, p => ({ ...p, courseId: v }))}
                    placeholder="Pick a course"
                    ariaLabel="Course"
                    options={allCourses.map(c => ({ value: c.course_id, label: c.course_code || c.course_name }))}
                  />
                  {item.status === "processed" && (
                    <>
                      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>Category:</span>
                      <CustomSelect
                        size="sm"
                        value={item.category || "other"}
                        onChange={(v) => handleCategoryChange(item, v)}
                        options={CATEGORY_OPTIONS}
                        ariaLabel="Category"
                      />
                      <button data-testid={`upload-modal-file-reanalyze-${idx}`} className="btn btn--ghost btn--sm" onClick={() => reanalyze(item)}>
                        <Icon name="sparkle" size={12} /> Re-analyze
                      </button>
                    </>
                  )}
                  {(item.status === "error" || item.status === "aborted") && (
                    <button data-testid={`upload-modal-file-retry-${idx}`} className="btn btn--ghost btn--sm" onClick={() => retry(item)}>
                      <Icon name="sparkle" size={12} /> Retry
                    </button>
                  )}
                </div>
                {item.status === "uploading" && item.progress && (
                  <div
                    aria-live="polite"
                    style={{
                      fontSize: 12,
                      color: "var(--text-muted)",
                      fontStyle: "italic",
                      lineHeight: 1.4,
                    }}
                  >
                    {item.progress}
                  </div>
                )}
                {item.summary && (
                  <div style={{ fontSize: 12, color: "var(--text-dim)", lineHeight: 1.5 }}>{item.summary}</div>
                )}
                {item.conceptNames && item.conceptNames.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {item.conceptNames.slice(0, 4).map(t => (
                      <span key={t} className="chip chip--accent">{t}</span>
                    ))}
                  </div>
                )}
                {item.error && (
                  <div style={{ fontSize: 11, color: "var(--err)" }}>{item.error}</div>
                )}
                {item.status === "error" && item.requestId && (
                  <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", gap: 6, alignItems: "center" }}>
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
                      className="btn btn--ghost btn--sm"
                      style={{ padding: "0 6px", fontSize: 10 }}
                    >
                      copy
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 20px", borderTop: "1px solid var(--border)" }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {items.length} file{items.length === 1 ? "" : "s"} queued
            {activeUploads > 0 && ` · ${activeUploads} uploading`}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button data-testid="upload-modal-cancel" className="btn btn--ghost btn--sm" onClick={handleClose}>Cancel</button>
            {allFinished ? (
              <button data-testid="upload-modal-done" className="btn btn--sm btn--primary" onClick={finish}>Done</button>
            ) : (
              <button
                data-testid="upload-modal-submit"
                className="btn btn--sm btn--primary"
                disabled={items.length === 0 || items.every(i => i.status !== "pending")}
                onClick={startAll}
              >
                <Icon name="upload" size={12} /> Start upload
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/**
 * Concept names off a stream `result` ({ concepts: { concepts: [{ name }] } }).
 * One shape since #759: the backend normalises an idempotent replay to the
 * fresh DocumentProcessingResult keys instead of sending the DB row.
 */
function extractConceptNames(resp: UploadResultData): string[] {
  const concepts = resp.concepts?.concepts;
  if (!Array.isArray(concepts)) return [];
  return concepts
    .map(c => c?.name)
    .filter((n): n is string => typeof n === "string" && n.length > 0);
}

function StatusBadge({ status }: { status: UploadStatus }) {
  const meta = statusMeta(status);
  return (
    <span className={`chip ${meta.cls}`} style={{ fontSize: 10 }}>
      {meta.label}
    </span>
  );
}

function statusMeta(s: UploadStatus): { label: string; cls: string } {
  switch (s) {
    case "pending": return { label: "queued", cls: "" };
    case "uploading": return { label: "processing…", cls: "chip--info" };
    case "processed": return { label: "done", cls: "chip--accent" };
    case "aborted": return { label: "aborted", cls: "chip--warn" };
    case "error": return { label: "error", cls: "chip--err" };
  }
}
