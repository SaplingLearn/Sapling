"use client";
/**
 * The set builder survives a reload, the same way a review does
 * (review/reviewSession.ts): the URL is marked (`build=1`) while the builder
 * is open and the selection being built (what is ticked, the name, the
 * options, which saved set it came from, what "Sort it" said) is kept in
 * sessionStorage. A reload reads it back; leaving the builder clears both.
 */
import React from "react";
import { markParam, parseStored, strings, text, useLeaveOnBack } from "../review/reviewSession";
import { PER_CONCEPT, type Draft, type DraftAction, type PerConcept } from "./flashcardsModel";

export const BUILD_PARAM = "build";
const KEY = "sapling:flashcards:build";

export interface BuildSession {
  userId: string;
  courseId: string;
  /** What a sort said on the way in. */
  note: string;
  draft: Draft;
}

/** A stored draft back into one, or null when it is not one. */
export function parseDraft(value: unknown): Draft | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const selected = strings(v.selected);
  const custom = strings(v.custom);
  if (!selected || !custom) return null;
  return {
    selected,
    custom,
    onlyDue: v.onlyDue === true,
    shuffle: v.shuffle !== false,
    perConcept: PER_CONCEPT.includes(v.perConcept as PerConcept) ? (v.perConcept as PerConcept) : 5,
    name: text(v.name) ?? "",
    setId: text(v.setId),
    examId: text(v.examId),
    givenName: text(v.givenName),
  };
}

export function parseBuild(raw: string | null): BuildSession | null {
  const v = parseStored(raw);
  if (!v) return null;
  const draft = parseDraft(v.draft);
  const userId = text(v.userId);
  const courseId = text(v.courseId);
  if (!draft || !userId || courseId === null) return null;
  return { userId, courseId, note: text(v.note) ?? "", draft };
}

// Storage can be unavailable: the builder then simply does not survive a reload.
export function saveBuild(session: BuildSession): void {
  try { window.sessionStorage.setItem(KEY, JSON.stringify(session)); } catch { /* not kept */ }
}

export function loadBuild(userId: string, courseId: string): BuildSession | null {
  let raw: string | null = null;
  try { raw = window.sessionStorage.getItem(KEY); } catch { return null; }
  const session = parseBuild(raw);
  return session && session.userId === userId && session.courseId === courseId ? session : null;
}

export function clearBuild(): void {
  try { window.sessionStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}

/**
 * The page's side of it. `requested`: the URL carried the marker on arrival.
 * Once the student and the course are known the kept builder is put back
 * (`dispatch` a restore, then `onRestore`); from then on an open builder is
 * kept on every change and a closed one forgotten.
 */
export function useBuildSession(input: {
  userId: string;
  courseId: string;
  requested: boolean;
  build: { note: string } | null;
  draft: Draft;
  dispatch: React.Dispatch<DraftAction>;
  onRestore: (note: string) => void;
  /** The browser's Back, pressed in the builder. */
  onLeave: () => void;
}) {
  const { userId, courseId, build, draft, dispatch } = input;
  /** The marker has been answered (or there was none to answer). */
  const [checked, setChecked] = React.useState(!input.requested);
  const restore = React.useRef(input.onRestore);
  React.useEffect(() => { restore.current = input.onRestore; });

  React.useEffect(() => {
    if (checked || !userId || !courseId) return;
    const session = loadBuild(userId, courseId);
    if (session) {
      dispatch({ type: "restore", draft: session.draft });
      restore.current(session.note);
    }
    setChecked(true);
  }, [checked, userId, courseId, dispatch]);

  const note = build ? build.note : null;
  useLeaveOnBack(BUILD_PARAM, note !== null, input.onLeave);
  React.useEffect(() => {
    if (!checked) return;
    markParam(BUILD_PARAM, note !== null);
    if (note === null) clearBuild();
    else if (userId) saveBuild({ userId, courseId, note, draft });
  }, [checked, note, draft, userId, courseId]);
}
