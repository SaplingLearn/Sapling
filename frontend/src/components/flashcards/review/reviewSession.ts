"use client";
/**
 * A review survives a reload.
 *
 * The page marks the URL (`review=1`) while a review is open and keeps what
 * the review is in sessionStorage: which cards in which order (a shuffled deck
 * is not rebuilt, it is read back), where the student is in it and what they
 * have rated. On a reload the page reads it back and opens the same review on
 * the same card. Nothing is generated and nothing is fetched for it beyond the
 * card list the page loads anyway; a card deleted in the meantime is dropped.
 *
 * sessionStorage, not the URL: a deck is a list of card ids far too long for
 * one, and it belongs to this tab's visit (a link someone shares should open
 * the home, not a review of cards the reader does not have). Leaving the
 * review clears both.
 */
import React from "react";
import type { Card } from "../home/flashcardsModel";
import { TALLY_ORDER, type Rated, type Ratings } from "./reviewModel";

export const REVIEW_PARAM = "review";
const KEY = "sapling:flashcards:review";

/** Where a review is: what `Review` reports and can be started from. */
export interface ReviewProgress {
  idx: number;
  ratings: Ratings;
  /** The ids of a "review the ones you missed" round; null: the whole deck. */
  round: string[] | null;
  done: boolean;
}

export interface ReviewSession extends ReviewProgress {
  userId: string;
  courseId: string;
  title: string;
  /** The deck's cards, in review order. */
  ids: string[];
}

const strings = (value: unknown): string[] | null =>
  Array.isArray(value) && value.every(x => typeof x === "string") ? (value as string[]) : null;

/** A stored value back into a session, or null when it is not one. */
export function parseSession(raw: string | null): ReviewSession | null {
  if (!raw) return null;
  let v: Record<string, unknown>;
  try { v = JSON.parse(raw) as Record<string, unknown>; } catch { return null; }
  if (!v || typeof v !== "object") return null;
  const ids = strings(v.ids);
  if (!ids || !ids.length || typeof v.userId !== "string" || typeof v.courseId !== "string") return null;
  const ratings: Record<string, Rated> = {};
  for (const [id, kind] of Object.entries((v.ratings as Record<string, unknown>) ?? {})) {
    if (TALLY_ORDER.includes(kind as Rated)) ratings[id] = kind as Rated;
  }
  return {
    userId: v.userId,
    courseId: v.courseId,
    title: typeof v.title === "string" ? v.title : "",
    ids,
    idx: Number.isInteger(v.idx) && (v.idx as number) >= 0 ? (v.idx as number) : 0,
    ratings,
    round: strings(v.round),
    done: v.done === true,
  };
}

/** The session's deck out of the cards the student has now, in its order.
 *  A card that is gone is left out. */
export function restoreDeck(session: ReviewSession, cards: Card[]): Card[] {
  const byId = new Map(cards.map(c => [c.id, c]));
  return session.ids.flatMap(id => byId.get(id) ?? []);
}

// Storage can be unavailable (private mode, blocked site data): a review then
// simply does not survive a reload.
export function saveSession(session: ReviewSession): void {
  try { window.sessionStorage.setItem(KEY, JSON.stringify(session)); } catch { /* not kept */ }
}

export function loadSession(userId: string, courseId: string): ReviewSession | null {
  let raw: string | null = null;
  try { raw = window.sessionStorage.getItem(KEY); } catch { return null; }
  const session = parseSession(raw);
  return session && session.userId === userId && session.courseId === courseId ? session : null;
}

export function clearSession(): void {
  try { window.sessionStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}

/** The live URL carries the `name` marker. */
export function hasParam(name: string): boolean {
  return typeof window !== "undefined" && new URL(window.location.href).searchParams.has(name);
}

/**
 * Put a `name=1` marker on (or take it off) the current URL without a
 * navigation. (The builder keeps itself the same way: home/buildSession.ts.)
 * Putting it on is a NEW history entry, so the browser's Back leaves the
 * review (or the builder) for the screen under it; taking it off rewrites the
 * entry it is on.
 */
export function markParam(name: string, on: boolean): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (url.searchParams.has(name) === on) return;
  if (on) {
    url.searchParams.set(name, "1");
    window.history.pushState(window.history.state, "", url.toString());
  } else {
    url.searchParams.delete(name);
    window.history.replaceState(window.history.state, "", url.toString());
  }
}

export const markReview = (on: boolean) => markParam(REVIEW_PARAM, on);

/** While `open`, the browser's Back (the marker leaving the URL) calls `onLeave`. */
export function useLeaveOnBack(name: string, open: boolean, onLeave: () => void): void {
  const leave = React.useRef(onLeave);
  React.useEffect(() => { leave.current = onLeave; });
  React.useEffect(() => {
    if (!open) return;
    const onPop = () => { if (!hasParam(name)) leave.current(); };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [name, open]);
}

/**
 * The page's side of it. While `review` is open it is kept (deck, title and
 * the progress `Review` reports through `onProgress`) and the URL is marked.
 * On a reload with the marker, once the cards are in (`ready`), the kept
 * review is handed to `onRestore`; until then `pending` is true and the page
 * shows neither the home nor the review.
 */
export function useReviewSession(input: {
  userId: string;
  courseId: string;
  /** The URL carried the marker on arrival (read from the router's params,
   *  which the server render shares, not from `window`), and did not ask for
   *  something else (`start=1`). */
  requested: boolean;
  /** The card list has answered and the course is known. */
  ready: boolean;
  cards: Card[];
  review: { deck: Card[]; title: string } | null;
  onRestore: (deck: Card[], title: string) => void;
  /** The browser's Back, pressed in the review. */
  onLeave: () => void;
}) {
  const { userId, courseId, ready, cards, review, onRestore } = input;
  const [pending, setPending] = React.useState(input.requested);
  const [initial, setInitial] = React.useState<ReviewProgress | undefined>(undefined);
  const [progress, setProgress] = React.useState<ReviewProgress | null>(null);
  const restore = React.useRef(onRestore);
  React.useEffect(() => { restore.current = onRestore; });

  React.useEffect(() => {
    if (!pending || !ready) return;
    const session = userId ? loadSession(userId, courseId) : null;
    const deck = session ? restoreDeck(session, cards) : [];
    if (session && deck.length) {
      const { idx, ratings, round, done } = session;
      setInitial({ idx, ratings, round, done });
      restore.current(deck, session.title);
    } else {
      clearSession();
      markReview(false);
    }
    setPending(false);
  }, [pending, ready, userId, courseId, cards]);

  // Open: mark the URL. Closed: forget it (but not before a reload's review
  // has been read back).
  const open = !!review;
  React.useEffect(() => {
    if (pending) return;
    markReview(open);
    if (!open) { clearSession(); setInitial(undefined); setProgress(null); }
  }, [open, pending]);

  useLeaveOnBack(REVIEW_PARAM, open, input.onLeave);

  React.useEffect(() => {
    if (!review || !progress || !userId) return;
    saveSession({ userId, courseId, title: review.title, ids: review.deck.map(c => c.id), ...progress });
  }, [review, progress, userId, courseId]);

  return { pending, initial, onProgress: setProgress };
}
