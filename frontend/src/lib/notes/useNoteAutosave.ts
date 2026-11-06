"use client";
/**
 * Debounced, per-note autosave for the notetaker (#768).
 *
 * Each note id owns an explicit save entry: a `pending` patch (dirty), at most
 * one PATCH `inFlight` (saving), and an `error` flag + attempt count (a failed
 * save). The footer status is an aggregate over every entry, so it can never
 * say "Saved" while any note still has a write queued, in flight or failed:
 *
 *   any entry failed (and not currently retrying) → "error"
 *   else any entry in flight                      → "saving"
 *   else any entry with a queued edit             → "unsaved"
 *   else                                          → "saved"
 *
 * Invariants:
 *   - A failed save never drops the edit: its patch is merged back UNDER any
 *     newer queued edit and retried — on the next edit's debounce, on a
 *     capped exponential backoff, or immediately via `retry()` / `flush()`.
 *   - One PATCH per note in flight at a time, so writes land in order.
 *   - `cancel(id)` (the note was deleted) drops the queued patch, its timers,
 *     and ignores the outcome of a PATCH already in flight — a deleted note is
 *     never PATCHed again and its 404 never shows as a save error.
 *   - `flush(id)` resolves `true` only once everything queued for that note
 *     has landed, so callers that hand the note to an agent can await it.
 *   - Pending edits are flushed on unmount and (keepalive) on `pagehide`.
 */
import React from "react";
import { patchNote } from "@/lib/api";
import type { Note as ApiNote } from "@/lib/types";

export type NotePatch = Partial<Pick<ApiNote, "title" | "body" | "tags">>;
export type AutosaveStatus = "saved" | "unsaved" | "saving" | "error";

export const AUTOSAVE_DEBOUNCE_MS = 800;
const RETRY_BASE_MS = 2_000;
const RETRY_MAX_MS = 30_000;

/** Backoff before automatic retry number `attempt` (1-based), capped. */
export function retryDelayMs(attempt: number): number {
  return Math.min(RETRY_MAX_MS, RETRY_BASE_MS * 2 ** Math.max(0, attempt - 1));
}

type Entry = {
  pending: NotePatch | null;
  timer: number | null;
  inFlight: Promise<boolean> | null;
  error: boolean;
  attempts: number;
  cancelled: boolean;
};

function clearTimer(e: Entry) {
  if (e.timer !== null) {
    window.clearTimeout(e.timer);
    e.timer = null;
  }
}

function aggregate(entries: Iterable<Entry>): AutosaveStatus {
  let status: AutosaveStatus = "saved";
  for (const e of entries) {
    if (e.error && !e.inFlight) return "error";
    if (e.inFlight) status = "saving";
    else if (e.pending && status === "saved") status = "unsaved";
  }
  return status;
}

/**
 * The framework-free save machine. `onStatus` receives every aggregate change;
 * the user id is read at send time (`setUserId`).
 */
export function createNoteAutosave(opts: {
  onStatus: (status: AutosaveStatus) => void;
}) {
  const entries = new Map<string, Entry>();
  let disposed = false;
  let userId: string | null | undefined = null;

  const recompute = () => opts.onStatus(aggregate(entries.values()));

  function send(noteId: string, keepalive: boolean): Promise<boolean> {
    const e = entries.get(noteId);
    if (!e || e.cancelled) return Promise.resolve(true);
    clearTimer(e);
    // Serialize per note: queue behind the write already on the wire.
    if (e.inFlight) return e.inFlight.then(() => send(noteId, keepalive));
    if (!e.pending) return Promise.resolve(!e.error);
    const uid = userId;
    if (!uid) return Promise.resolve(false);

    const patch = e.pending;
    e.pending = null;
    const request = patchNote(noteId, uid, patch, { keepalive }).then(
      () => {
        if (!e.cancelled) {
          e.error = false;
          e.attempts = 0;
        }
        return true;
      },
      (err: unknown) => {
        // A cancelled (deleted) note's failure — typically the 404 — is moot.
        if (e.cancelled) return true;
        console.error("Autosave failed", err);
        // Keep the edit: the failed patch goes back UNDER anything newer.
        e.pending = { ...patch, ...(e.pending ?? {}) };
        e.error = true;
        e.attempts += 1;
        // A newer edit's debounce timer already retries sooner; otherwise
        // back off. Never retry in the background after unmount.
        if (e.timer === null && !disposed) {
          e.timer = window.setTimeout(() => {
            e.timer = null;
            void send(noteId, false);
          }, retryDelayMs(e.attempts));
        }
        return false;
      },
    );
    const tracked = request.then((ok) => {
      e.inFlight = null;
      if (!e.cancelled && !e.pending && !e.error && e.timer === null) {
        entries.delete(noteId);
      }
      recompute();
      return ok;
    });
    e.inFlight = tracked;
    recompute();
    return tracked;
  }

  /** Merge `patch` into the note's queued edit and (re)start the debounce. */
  function queue(noteId: string, patch: NotePatch) {
    let entry = entries.get(noteId);
    if (!entry) {
      entry = {
        pending: null,
        timer: null,
        inFlight: null,
        error: false,
        attempts: 0,
        cancelled: false,
      };
      entries.set(noteId, entry);
    }
    const e = entry;
    e.pending = { ...(e.pending ?? {}), ...patch };
    clearTimer(e);
    e.timer = window.setTimeout(() => {
      e.timer = null;
      void send(noteId, false);
    }, AUTOSAVE_DEBOUNCE_MS);
    recompute();
  }

  /** Save `noteId` now; resolves true once everything queued for it landed. */
  function flush(noteId: string, keepalive = false): Promise<boolean> {
    return send(noteId, keepalive);
  }

  /** Save every note with a queued (or failed) edit now. */
  function flushAll(keepalive = false): Promise<boolean> {
    const ids = Array.from(entries.entries())
      .filter(([, e]) => e.pending !== null)
      .map(([id]) => id);
    return Promise.all(ids.map((id) => send(id, keepalive))).then((r) =>
      r.every(Boolean),
    );
  }

  /** Manual "Retry": re-send every failed note immediately. */
  function retry() {
    for (const [id, e] of entries) {
      if (e.error) void send(id, false);
    }
  }

  /**
   * The note is (being) deleted: drop its queued save and ignore any in-flight
   * outcome. Returns the dropped patch so a caller whose delete then FAILS can
   * `queue` it back instead of losing the edit.
   */
  function cancel(noteId: string): NotePatch | null {
    const e = entries.get(noteId);
    if (!e) return null;
    const dropped = e.pending;
    e.cancelled = true;
    clearTimer(e);
    e.pending = null;
    entries.delete(noteId);
    recompute();
    return dropped;
  }

  /** Mount/unmount: a disposed engine never schedules background retries. */
  function setDisposed(value: boolean) {
    disposed = value;
    if (value) for (const e of entries.values()) clearTimer(e);
  }

  function setUserId(value: string | null | undefined) {
    userId = value;
  }

  return { queue, flush, flushAll, retry, cancel, setDisposed, setUserId };
}

export function useNoteAutosave(userId: string | null | undefined) {
  const [status, setStatus] = React.useState<AutosaveStatus>("saved");
  const [engine] = React.useState(() => createNoteAutosave({ onStatus: setStatus }));
  React.useEffect(() => {
    engine.setUserId(userId);
  }, [engine, userId]);

  // Flush on tab close / hard navigation (keepalive so the request survives
  // the unload) and on unmount (a normal request against the live page).
  React.useEffect(() => {
    engine.setDisposed(false);
    const onPageHide = () => void engine.flushAll(true);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      void engine.flushAll();
      engine.setDisposed(true);
    };
  }, [engine]);

  return {
    status,
    queue: engine.queue,
    flush: engine.flush,
    flushAll: engine.flushAll,
    retry: engine.retry,
    cancel: engine.cancel,
  };
}
