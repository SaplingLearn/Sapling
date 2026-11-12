// @vitest-environment jsdom
/**
 * A review kept across a reload: what is stored, what is read back, and what
 * is refused. (The page's side of it is in home/FlashcardsHome.test.tsx.)
 */
import { describe, it, expect, beforeEach } from "vitest";
import type { Card } from "../home/flashcardsModel";
import {
  clearSession,
  loadSession,
  markReview,
  parseSession,
  restoreDeck,
  saveSession,
  type ReviewSession,
} from "./reviewSession";

const card = (id: string): Card => ({ id, topic: "Recursion", front: `Q-${id}`, back: `A-${id}`, course_id: "c1" });
const SESSION: ReviewSession = {
  userId: "u1", courseId: "c1", title: "Midterm crunch", ids: ["b", "a", "c"],
  idx: 1, ratings: { b: "easy" }, round: null, done: false,
};

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/flashcards?course=c1");
});

describe("a kept review", () => {
  it("comes back as it was saved, for the same student and course only", () => {
    saveSession(SESSION);
    expect(loadSession("u1", "c1")).toEqual(SESSION);
    expect(loadSession("u2", "c1")).toBeNull();
    expect(loadSession("u1", "c2")).toBeNull();
    clearSession();
    expect(loadSession("u1", "c1")).toBeNull();
  });

  it("refuses what is not a session, and repairs what it can", () => {
    expect(parseSession(null)).toBeNull();
    expect(parseSession("not json")).toBeNull();
    expect(parseSession("null")).toBeNull();
    expect(parseSession(JSON.stringify({ ...SESSION, ids: [] }))).toBeNull();
    expect(parseSession(JSON.stringify({ ...SESSION, ids: [1, 2] }))).toBeNull();
    expect(parseSession(JSON.stringify({ ...SESSION, userId: 7 }))).toBeNull();
    // A bad position starts at the first card; an unknown rating is dropped.
    expect(parseSession(JSON.stringify({ ...SESSION, idx: -3, ratings: { a: "easy", b: "great" }, round: "x", done: "yes" })))
      .toEqual({ ...SESSION, idx: 0, ratings: { a: "easy" }, round: null, done: false });
  });

  it("rebuilds the deck in its saved order from the cards there are now", () => {
    expect(restoreDeck(SESSION, [card("a"), card("b"), card("c"), card("d")]).map(c => c.id)).toEqual(["b", "a", "c"]);
    // A card deleted since is left out.
    expect(restoreDeck(SESSION, [card("c"), card("b")]).map(c => c.id)).toEqual(["b", "c"]);
    expect(restoreDeck(SESSION, [])).toEqual([]);
  });

  it("marks the URL without touching its other params, and unmarks it", () => {
    markReview(true);
    expect(window.location.search).toBe("?course=c1&review=1");
    markReview(true);
    expect(window.location.search).toBe("?course=c1&review=1");
    markReview(false);
    expect(window.location.search).toBe("?course=c1");
  });
});
