"use client";
/**
 * The Library's upload engine: one streaming upload per file, with the
 * progress, cancel and retry semantics the old modal established (#759).
 *
 * It deliberately mirrors `DocumentUploadModal`'s engine rather than importing
 * it: that component owns its own picker UI and lifecycle, and the redesign
 * needs the same machinery under a different surface. The two rules worth
 * repeating are the ones that are easy to get wrong:
 *
 *  - A RETRY reuses the attempt's `X-Request-ID` while the course is
 *    unchanged, so a document the server saved after the client gave up is
 *    replayed instead of processed twice.
 *  - A terminal outcome is read off the resolved `UploadOutcome`, never off
 *    the event stream, so a failure that arrives after a `result` event is
 *    still a failure (nothing was saved).
 */
import React from "react";

import { uploadDocumentStream, type UploadEvent } from "@/lib/api";

/** Processing is given four minutes before the client stops waiting. */
const UPLOAD_TIMEOUT_MS = 4 * 60 * 1000;
const TIMEOUT_MESSAGE = "Processing took longer than 4 minutes — try a smaller file.";
const CANCELLED_MESSAGE = "Upload cancelled.";

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

export type UploadStatus = "pending" | "uploading" | "done" | "error";

export interface UploadRow {
  id: string;
  file: File;
  /** "PDF" / "PPTX" / "DOCX" — the tag colour keys on it. */
  fmt: string;
  /** The name without its extension, as the Library shows it. */
  name: string;
  /** "1.2 MB" / "640 KB". */
  size: string;
  status: UploadStatus;
  /** The live message from the stream while uploading. */
  progress?: string;
  error?: string;
  documentId?: string;
  /** The saved category, so the caller can re-poll after a syllabus. */
  category?: string;
  requestId?: string;
  requestCourseId?: string | null;
  abort?: AbortController;
}

export function describeSize(bytes: number): string {
  return bytes > 1e6
    ? `${(bytes / 1e6).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function rowsFor(files: File[]): UploadRow[] {
  return files.map((file, i) => {
    const ext = (file.name.split(".").pop() || "").toUpperCase();
    return {
      id: `${Date.now()}-${i}-${file.name}`,
      file,
      fmt: ["PDF", "PPTX", "DOCX"].includes(ext) ? ext : "PDF",
      name: file.name.replace(/\.[^.]+$/, ""),
      size: describeSize(file.size),
      status: "pending" as const,
    };
  });
}

export interface UploadQueue {
  rows: UploadRow[];
  setRows: React.Dispatch<React.SetStateAction<UploadRow[]>>;
  /** True while any row is still in flight. */
  busy: boolean;
  /** Every row has reached a terminal state, and there is at least one. */
  finished: boolean;
  start: (courseId: string | null) => void;
  retry: (id: string, courseId: string | null) => void;
  cancel: (id: string) => void;
  cancelAll: () => void;
  reset: () => void;
}

export function useUploadQueue(userId: string): UploadQueue {
  const [rows, setRows] = React.useState<UploadRow[]>([]);
  const controllers = React.useRef(new Set<AbortController>());

  const cancelAll = React.useCallback(() => {
    controllers.current.forEach(ac => abortWith(ac, "cancelled"));
    controllers.current.clear();
  }, []);

  React.useEffect(() => cancelAll, [cancelAll]);

  const run = React.useCallback(async (
    row: UploadRow, courseId: string | null, reuseRequestId: boolean,
  ) => {
    if (!courseId) {
      setRows(prev => prev.map(r => (r.id === row.id
        ? { ...r, status: "error", error: "Pick a course first." } : r)));
      return;
    }
    const ac = new AbortController();
    controllers.current.add(ac);
    const timer = setTimeout(() => abortWith(ac, "timeout"), UPLOAD_TIMEOUT_MS);
    const requestId = reuseRequestId && row.requestId && row.requestCourseId === courseId
      ? row.requestId
      : mintRequestId();

    // Every attempt starts from a clean row (#759): a retry must not keep the
    // previous attempt's error or document id on screen.
    setRows(prev => prev.map(r => (r.id === row.id ? {
      ...r,
      status: "uploading" as const,
      abort: ac,
      progress: "Starting upload…",
      requestId,
      requestCourseId: courseId,
      error: undefined,
      documentId: undefined,
    } : r)));

    const settle = (patch: Partial<UploadRow>) =>
      setRows(prev => prev.map(r => (r.id === row.id
        ? { ...r, progress: undefined, abort: undefined, ...patch } : r)));

    try {
      const fd = new FormData();
      fd.append("file", row.file);
      fd.append("course_id", courseId);
      fd.append("user_id", userId);
      const outcome = await uploadDocumentStream(fd, (ev: UploadEvent) => {
        if (ev.type === "status" && ev.step === "done") return;
        const evRid = (ev.data as { request_id?: unknown } | undefined)?.request_id;
        setRows(prev => prev.map(r => (r.id === row.id ? {
          ...r,
          progress: ev.message,
          ...(typeof evRid === "string" && evRid ? { requestId: evRid } : {}),
        } : r)));
      }, ac.signal, requestId);

      if (outcome.kind === "processed") {
        settle({
          status: "done",
          documentId: outcome.documentId,
          category: outcome.result.classification?.category || "other",
        });
      } else {
        settle({
          status: "error",
          error: outcome.message,
          ...(outcome.requestId ? { requestId: outcome.requestId } : {}),
        });
      }
    } catch (err) {
      const reason = abortReasons.get(ac);
      settle({
        status: "error",
        error: reason
          ? (reason === "timeout" ? TIMEOUT_MESSAGE : CANCELLED_MESSAGE)
          : String((err as Error)?.message || err),
      });
    } finally {
      clearTimeout(timer);
      controllers.current.delete(ac);
    }
  }, [userId]);

  const start = React.useCallback((courseId: string | null) => {
    setRows(prev => {
      prev.filter(r => r.status === "pending").forEach(r => { void run(r, courseId, false); });
      return prev;
    });
  }, [run]);

  const retry = React.useCallback((id: string, courseId: string | null) => {
    setRows(prev => {
      const row = prev.find(r => r.id === id);
      if (row) void run(row, courseId, true);
      return prev;
    });
  }, [run]);

  const cancel = React.useCallback((id: string) => {
    setRows(prev => {
      const row = prev.find(r => r.id === id);
      if (row?.abort) abortWith(row.abort, "cancelled");
      return prev;
    });
  }, []);

  const reset = React.useCallback(() => {
    cancelAll();
    setRows([]);
  }, [cancelAll]);

  const busy = rows.some(r => r.status === "uploading");
  const finished = rows.length > 0 && rows.every(r => r.status === "done" || r.status === "error");

  return { rows, setRows, busy, finished, start, retry, cancel, cancelAll, reset };
}
