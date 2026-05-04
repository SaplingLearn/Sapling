"use client";

import React from "react";
import { createPortal } from "react-dom";
import { Icon } from "./Icon";
import { CustomSelect } from "./CustomSelect";
import { useToast } from "./ToastProvider";
import {
  uploadDocumentStream,
  updateDocumentCategory,
  addCourse,
  onboardingCoursesSearch,
  type EnrolledCourse,
  type OnboardingCourse,
  type UploadEvent,
} from "@/lib/api";

const MAX_FILES = 5;
const MAX_SIZE = 15 * 1024 * 1024;
const ALLOWED = /\.(pdf|docx|pptx)$/i;
const UPLOAD_TIMEOUT_MS = 4 * 60 * 1000;

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

  React.useEffect(() => setMounted(true), []);

  React.useEffect(() => {
    if (!open) {
      setItems([]);
      setCourseQuery("");
      setCourseResults([]);
      return;
    }
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  React.useEffect(() => {
    if (!courseQuery.trim()) { setCourseResults([]); return; }
    const t = setTimeout(() => {
      onboardingCoursesSearch(courseQuery).then(r => setCourseResults(r.courses ?? [])).catch(() => setCourseResults([]));
    }, 200);
    return () => clearTimeout(t);
  }, [courseQuery]);

  const activeUploads = items.filter(it => it.status === "uploading").length;

  const handleClose = () => {
    if (activeUploads > 0) {
      if (!window.confirm(`${activeUploads} upload${activeUploads === 1 ? "" : "s"} still running. Abort and close?`)) return;
      items.forEach(it => it.abort?.abort());
    }
    onClose();
  };

  const addFiles = (fileList: File[]) => {
    const defaultCourseId = courses[0]?.course_id || "";
    const candidates = fileList
      .slice(0, MAX_FILES - items.length)
      .filter(f => {
        if (!ALLOWED.test(f.name)) {
          toast.error(`${f.name}: only PDF / DOCX / PPTX are accepted.`);
          return false;
        }
        if (f.size > MAX_SIZE) {
          toast.error(`${f.name}: exceeds the 15 MB limit.`);
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
      ...i, status: "uploading", abort: ac, progress: "Starting upload…", requestId,
    } : i));
    try {
      const fd = new FormData();
      fd.append("file", item.file);
      fd.append("course_id", item.courseId);
      fd.append("user_id", userId);
      const resp = await uploadDocumentStream(fd, (ev: UploadEvent) => {
        // Mirror backend SaplingEvent.message into the row's live label.
        if (ev.type === "status" && ev.step === "done") return; // final state covered below

        // Capture any backend-supplied request_id (matches what we sent, but
        // some events may carry the canonical one if the backend re-issues).
        const evRid = (ev.data as { request_id?: unknown } | undefined)?.request_id;
        if (typeof evRid === "string" && evRid.length > 0) {
          setItems(prev => prev.map(i => i.id === item.id ? { ...i, requestId: evRid } : i));
        }

        if (ev.type === "error") {
          // Two flavors of error event from the streaming route:
          //   step === "fallback" — orchestrator tripped, legacy path will run.
          //                         Degraded mode, NOT a terminal failure.
          //   step === "failed"   — terminal failure from _stream_legacy_fallback.
          // Anything else we treat as informational and skip toasting to avoid
          // double-firing alongside the catch-block toast.
          if (ev.step === "fallback") {
            toast.warn(`Switching to fallback: ${ev.message}`);
          } else if (ev.step === "failed") {
            toast.error(`Upload failed: ${ev.message}`);
          }
          setItems(prev => prev.map(i => i.id === item.id ? { ...i, progress: ev.message } : i));
          return;
        }

        setItems(prev => prev.map(i => i.id === item.id ? { ...i, progress: ev.message } : i));
      }, ac.signal, requestId);
      clearTimeout(timeout);
      setItems(prev => prev.map(i => i.id === item.id ? {
        ...i,
        status: "processed",
        progress: undefined,
        docId: resp?.id,
        category: resp?.classification?.category || resp?.category || "other",
        summary: resp?.summary?.abstract ?? resp?.summary,
        conceptNames: extractConceptNames(resp),
      } : i));
    } catch (err: any) {
      clearTimeout(timeout);
      const aborted = ac.signal.aborted;
      const errorMsg = aborted
        ? "Processing took longer than 4 minutes — try a smaller file."
        : String(err?.message || err);
      setItems(prev => prev.map(i => i.id === item.id ? {
        ...i,
        status: aborted ? "aborted" : "error",
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
      await addCourse(userId, course.id);
      toast.success(`Added ${course.course_code}`);
      setCourseQuery("");
      setCourseResults([]);
      // Parent refreshes courses via onComplete.
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
    <div
      onClick={handleClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(19,38,16,0.45)",
        zIndex: 200, display: "grid", placeItems: "center", padding: 20,
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        className="card slide-up"
        style={{ width: "min(720px, 100%)", maxHeight: "88vh", overflow: "hidden", padding: 0, display: "flex", flexDirection: "column" }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 20px", borderBottom: "1px solid var(--border)" }}>
          <div>
            <div className="label-micro">Upload</div>
            <div className="h-serif" style={{ fontSize: 20 }}>Add course materials</div>
          </div>
          <button className="btn btn--ghost btn--sm" onClick={handleClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div style={{ padding: 20, overflowY: "auto" }}>
          <div
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
              PDF, DOCX, PPTX · max 15 MB each
            </div>
            <label className="btn btn--primary btn--sm">
              <Icon name="up" size={12} /> Browse
              <input
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

          {courses.length < 10 && (
            <div style={{ marginTop: 16 }}>
              <div className="label-micro" style={{ marginBottom: 6 }}>+ Add a course</div>
              <input
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
            {items.map(item => (
              <div
                key={item.id}
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
                    options={courses.map(c => ({ value: c.course_id, label: c.course_code || c.course_name }))}
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
                      <button className="btn btn--ghost btn--sm" onClick={() => reanalyze(item)}>
                        <Icon name="sparkle" size={12} /> Re-analyze
                      </button>
                    </>
                  )}
                  {(item.status === "error" || item.status === "aborted") && (
                    <button className="btn btn--ghost btn--sm" onClick={() => retry(item)}>
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
            <button className="btn btn--ghost btn--sm" onClick={handleClose}>Cancel</button>
            {allFinished ? (
              <button className="btn btn--sm btn--primary" onClick={done}>Done</button>
            ) : (
              <button
                className="btn btn--sm btn--primary"
                disabled={items.length === 0 || items.every(i => i.status !== "pending")}
                onClick={startAll}
              >
                <Icon name="up" size={12} /> Start upload
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
 * Pull concept names out of either the orchestrator result shape
 * ({ concepts: { concepts: [{ name, ... }] } }) or the legacy fallback
 * shape ({ concept_notes: [{ name }] }). Returns at most a flat string[].
 */
function extractConceptNames(resp: any): string[] {
  const fromOrchestrator = resp?.concepts?.concepts;
  if (Array.isArray(fromOrchestrator)) {
    return fromOrchestrator
      .map((c: { name?: unknown }) => c?.name)
      .filter((n: unknown): n is string => typeof n === "string" && n.length > 0);
  }
  const fromLegacy = resp?.concept_notes;
  if (Array.isArray(fromLegacy)) {
    return fromLegacy
      .map((n: { name?: unknown }) => n?.name)
      .filter((n: unknown): n is string => typeof n === "string" && n.length > 0);
  }
  return [];
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
