"use client";
// The Tutor's Saved tab (Tutor redesign, behind `saved_items`; backend
// routes/saved_items.py over services/saved_items.py, table
// tutor_saved_items): what a student saved from a session, one store per
// session shared by the Save action under each tutor reply, the session
// panel's Saved tab and the milestone page, so they never disagree.
import React, { useCallback, useEffect, useSyncExternalStore } from "react";
import { fetchJSON } from "@/lib/api";
import { useFlag } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import type { ChatMsg } from "../../chat/ChatPanel";
import styles from "./saved.module.css";

export type SavedItem = { id: string; session_id: string; course_id: string | null; title: string; content: string; created_at: string };

export const SAVED_COPY = {
  save: "Save",
  saved: "Saved",
  failed: "Couldn't save",
  tab: (n: number) => (n > 0 ? `Saved (${n})` : "Saved"),
  empty: "Nothing saved yet. Save a reply to keep it here.",
  remove: "Remove",
} as const;

// ── API ───────────────────────────────────────────────────────────────────────
const base = "/api/learn/saved";
export const listSaved = (userId: string, q: { sessionId?: string; courseId?: string }) => {
  const p = new URLSearchParams();
  if (q.sessionId) p.set("session_id", q.sessionId);
  if (q.courseId) p.set("course_id", q.courseId);
  return fetchJSON<{ items: SavedItem[] }>(`${base}/${encodeURIComponent(userId)}${p.size ? `?${p}` : ""}`);
};
export const saveItem = (userId: string, sessionId: string, title: string, content: string) =>
  fetchJSON<{ item: SavedItem }>(base, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, session_id: sessionId, title, content }) });
export const deleteSaved = (userId: string, id: string) =>
  fetchJSON<{ deleted: boolean }>(`${base}/${encodeURIComponent(id)}?${new URLSearchParams({ user_id: userId })}`, { method: "DELETE" });

/** A reply's title: its first line, without markdown marks, cut at 80. */
export function savedTitle(content: string): string {
  const line = (content.split("\n").find((l) => l.trim()) ?? "").replace(/[#*_`>]/g, "").trim();
  return line.length > 80 ? `${line.slice(0, 79).trimEnd()}…` : line;
}

// ── one store per session ─────────────────────────────────────────────────────
type Entry = { items: SavedItem[] | null; failed: boolean };
const EMPTY: Entry = { items: null, failed: false };
const store = new Map<string, Entry>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const set = (sessionId: string, entry: Entry) => { store.set(sessionId, entry); emit(); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
/** Test seam. */
export function __resetSavedForTests() { store.clear(); }

/** One session's saved items (null while loading), and save/remove. */
export function useSessionSaved(sessionId: string | null, enabled: boolean) {
  const { userId } = useUser();
  const entry = useSyncExternalStore(subscribe, () => (sessionId ? store.get(sessionId) ?? EMPTY : EMPTY), () => EMPTY);
  useEffect(() => {
    if (!enabled || !userId || !sessionId || store.has(sessionId)) return;
    store.set(sessionId, EMPTY); // one read per session
    listSaved(userId, { sessionId })
      .then((r) => set(sessionId, { items: r.items ?? [], failed: false }))
      .catch(() => set(sessionId, { items: null, failed: true }));
  }, [enabled, userId, sessionId]);
  const save = useCallback(async (content: string) => {
    if (!sessionId || !userId) return;
    const r = await saveItem(userId, sessionId, savedTitle(content), content);
    const now = store.get(sessionId)?.items ?? [];
    set(sessionId, { items: [r.item, ...now.filter((i) => i.id !== r.item.id)], failed: false });
  }, [sessionId, userId]);
  const remove = useCallback(async (id: string) => {
    if (!sessionId || !userId) return;
    await deleteSaved(userId, id);
    set(sessionId, { items: (store.get(sessionId)?.items ?? []).filter((i) => i.id !== id), failed: false });
  }, [sessionId, userId]);
  return { ...entry, save, remove };
}

/** The Save action under one tutor reply: "Save", then "Saved". */
function SaveReply({ m, sessionId }: { m: ChatMsg; sessionId: string }) {
  const { items, save } = useSessionSaved(sessionId, true);
  const [state, setState] = React.useState<"idle" | "busy" | "failed">("idle");
  const saved = (items ?? []).some((i) => i.content === m.content.trim());
  return (
    <div className={styles.action}>
      <button type="button" className={styles.save} data-testid="tutor-save-reply" disabled={saved || state === "busy"}
        aria-label={saved ? `${SAVED_COPY.saved}: ${savedTitle(m.content)}` : `${SAVED_COPY.save}: ${savedTitle(m.content)}`}
        onClick={() => { setState("busy"); save(m.content).then(() => setState("idle"), () => setState("failed")); }}>
        {saved ? SAVED_COPY.saved : SAVED_COPY.save}
      </button>
      {state === "failed" && <span role="status" className={styles.note}>{SAVED_COPY.failed}</span>}
    </div>
  );
}

/** ChatPanel's `messageAction` for a session: Save under each settled tutor
 *  reply, while `saved_items` is on; null otherwise. Stable per session. */
export function useSaveAction(sessionId: string | null): ((m: ChatMsg) => React.ReactNode) | undefined {
  const on = useFlag("saved_items") === "on";
  const action = useCallback((m: ChatMsg) => (
    sessionId && m.role === "assistant" && !m.loading && !m.interrupted && !m.crisisSupport && m.content.trim()
      ? <SaveReply m={m} sessionId={sessionId} /> : null
  ), [sessionId]);
  return on && sessionId ? action : undefined;
}

/** The session panel's Saved tab: each item's title opens its text. */
export function SavedList({ sessionId }: { sessionId: string }) {
  const { items, failed, remove } = useSessionSaved(sessionId, true);
  if (failed) return <p className={styles.note}>Couldn&apos;t load what you saved.</p>;
  if (items === null) return null;
  if (items.length === 0) return <p className={styles.note} data-testid="tutor-saved-empty">{SAVED_COPY.empty}</p>;
  return (
    <ul className={styles.list} data-testid="tutor-saved-list">
      {items.map((i) => (
        <li key={i.id} className={styles.item} data-testid={`tutor-saved-${i.id}`}>
          <details>
            <summary className={styles.title}>{i.title}</summary>
            <p className={styles.content}>{i.content}</p>
          </details>
          <button type="button" className={styles.remove} aria-label={`${SAVED_COPY.remove}: ${i.title}`}
            onClick={() => void remove(i.id)}>{SAVED_COPY.remove}</button>
        </li>
      ))}
    </ul>
  );
}
