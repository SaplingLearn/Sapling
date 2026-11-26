"use client";
/**
 * Loading, autosaving and regenerating one document's notes.
 *
 * The prototype keeps the body in `localStorage` under
 * `sapling:notes:v2:<docId>`; this is the same shape against the API. Two
 * things matter and are easy to get wrong:
 *
 *  - The editor is UNCONTROLLED. React writes its HTML exactly once, when the
 *    notes first arrive; after that the DOM is the source of truth and a
 *    re-render must never replace it, or the caret jumps on every keystroke.
 *  - The autosave debounces, so the last edit before a navigation would be
 *    lost — it is flushed on unmount and on `pagehide`.
 */
import React from "react";

import {
  getDocumentNotes, regenerateDocumentNotes, saveDocumentNotes,
} from "@/lib/notesApi";
import type { DocumentNotes } from "@/lib/types";
import { humanizeError } from "@/lib/errorMessage";

/** The design's save debounce. */
const SAVE_MS = 600;

export type SaveState = "Saved" | "Saving…" | "Not saved";

export interface DocumentNotesState {
  /** Null until the notes have loaded. */
  notes: DocumentNotes | null;
  loading: boolean;
  /** The load failed; the page says so rather than showing an empty editor. */
  error: string | null;
  retry: () => void;
  /**
   * The notes loaded, but with no opening draft — the model was unavailable,
   * so the editor opened empty rather than the page failing. The page says so
   * once: an empty editor otherwise reads as notes that went missing.
   */
  draftFailed: boolean;

  title: string;
  setTitle: (t: string) => void;
  /** Read-only until the student presses Edit. */
  final: boolean;
  setFinal: (f: boolean) => void;
  saveState: SaveState;
  /** When the notes were last edited, for the "Edited …" line. */
  editedAt: number | null;

  /** Called by the editor on every change; debounces a save of `read()`. */
  touch: () => void;
  /** Save now, without waiting for the debounce. */
  flush: () => Promise<void>;
  regenerate: () => Promise<boolean>;
  regenerating: boolean;
}

export interface DocumentNotesInput {
  documentId: string;
  userId: string;
  ready: boolean;
  /** Reads the editor's current HTML. */
  read: () => string;
  /** Writes the loaded HTML into the editor, once. */
  write: (html: string) => void;
}

export function useDocumentNotes(input: DocumentNotesInput): DocumentNotesState {
  const { documentId, userId, ready, read, write } = input;

  const [notes, setNotes] = React.useState<DocumentNotes | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [draftFailed, setDraftFailed] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  const [title, setTitleState] = React.useState("");
  const [final, setFinalState] = React.useState(false);
  const [saveState, setSaveState] = React.useState<SaveState>("Saved");
  const [editedAt, setEditedAt] = React.useState<number | null>(null);
  const [regenerating, setRegenerating] = React.useState(false);

  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const readRef = React.useRef(read);
  readRef.current = read;
  const writeRef = React.useRef(write);
  writeRef.current = write;
  /** What the next save should carry beyond the body. */
  const pending = React.useRef<{ title?: string; final?: boolean }>({});

  const save = React.useCallback(async () => {
    if (!userId || !documentId) return;
    const extra = pending.current;
    pending.current = {};
    try {
      await saveDocumentNotes(documentId, userId, {
        content: readRef.current(),
        ...extra,
      });
      setSaveState("Saved");
    } catch (err) {
      console.error("notes save failed", err);
      // Say so rather than claiming "Saved": the student decides whether to
      // copy their work out.
      setSaveState("Not saved");
    }
  }, [documentId, userId]);

  const touch = React.useCallback(() => {
    setSaveState("Saving…");
    setEditedAt(Date.now());
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void save(); }, SAVE_MS);
  }, [save]);

  const flush = React.useCallback(async () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    await save();
  }, [save]);

  // Load once per document. The editor's HTML is written here and never again.
  React.useEffect(() => {
    if (!ready || !userId || !documentId) return;
    let live = true;
    setLoading(true);
    setError(null);
    getDocumentNotes(documentId, userId)
      .then(n => {
        if (!live) return;
        setNotes(n);
        setTitleState(n.title || "");
        setFinalState(!!n.final);
        setEditedAt(Date.parse(n.updated_at) || null);
        writeRef.current(n.content || "");
        setDraftFailed(!!n.draft_failed);
        setLoading(false);
      })
      .catch(err => {
        if (!live) return;
        console.error("notes load failed", err);
        setError(humanizeError(err, "Couldn't load these notes."));
        setLoading(false);
      });
    return () => { live = false; };
  }, [documentId, userId, ready, attempt]);

  // A debounced save must not be lost to a navigation.
  React.useEffect(() => {
    const onHide = () => { if (timer.current) void flush(); };
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      if (timer.current) { clearTimeout(timer.current); void save(); }
    };
  }, [flush, save]);

  const setTitle = React.useCallback((t: string) => {
    setTitleState(t);
    pending.current.title = t;
    touch();
  }, [touch]);

  const setFinal = React.useCallback((f: boolean) => {
    setFinalState(f);
    pending.current.final = f;
    touch();
  }, [touch]);

  const regenerate = React.useCallback(async () => {
    if (!userId || !documentId) return false;
    setRegenerating(true);
    try {
      const n = await regenerateDocumentNotes(documentId, userId);
      setNotes(n);
      setTitleState(n.title || "");
      setFinalState(false);
      setEditedAt(Date.parse(n.updated_at) || Date.now());
      writeRef.current(n.content || "");
      setSaveState("Saved");
      return true;
    } catch (err) {
      console.error("notes regenerate failed", err);
      return false;
    } finally {
      setRegenerating(false);
    }
  }, [documentId, userId]);

  const retry = React.useCallback(() => setAttempt(n => n + 1), []);

  return {
    notes, loading, error, retry, draftFailed,
    title, setTitle, final, setFinal, saveState, editedAt,
    touch, flush, regenerate, regenerating,
  };
}

/** "Edited just now" / "Edited 5 min ago" / "Edited today at 3:04 PM". */
export function editedLabel(editedAt: number | null, fallback: string): string {
  if (!editedAt) return `Last edited ${fallback}`;
  const secs = (Date.now() - editedAt) / 1000;
  if (secs < 60) return "Edited just now";
  if (secs < 3600) return `Edited ${Math.floor(secs / 60)} min ago`;
  const when = new Date(editedAt);
  const time = when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (when.toDateString() === new Date().toDateString()) return `Edited today at ${time}`;
  return `Edited ${when.toLocaleDateString([], { month: "short", day: "numeric" })} at ${time}`;
}
