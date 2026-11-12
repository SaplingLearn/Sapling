/**
 * The review's session rules, without rendering: what the strip, the tally and
 * the end-of-deck summary make of the ratings.
 */
import { describe, it, expect } from "vitest";
import type { Card } from "../home/flashcardsModel";
import { SEGMENT_CAP, missed, ratedAs, roundDeck, segments, tally, tallyLabel, type Ratings } from "./reviewModel";

const card = (id: string): Card => ({ id, topic: "T", front: `Q-${id}`, back: `A-${id}` });
const DECK = ["a", "b", "c", "d"].map(card);
const RATINGS: Ratings = { a: "easy", b: "forgot", c: "hard", gone: "easy" };

describe("ratings", () => {
  it("names the three the API stores as 1, 2, 3", () => {
    expect([1, 2, 3].map(ratedAs)).toEqual(["forgot", "hard", "easy"]);
  });

  it("counts each kind over the cards still in the deck", () => {
    expect(tally(DECK, RATINGS)).toEqual({ easy: 1, hard: 1, forgot: 1 });
    // A deleted card (no longer in the deck) stops counting.
    expect(tally(DECK.filter(c => c.id !== "b"), RATINGS)).toEqual({ easy: 1, hard: 1, forgot: 0 });
    expect(tally(DECK, {})).toEqual({ easy: 0, hard: 0, forgot: 0 });
    expect(tallyLabel({ easy: 2, hard: 1, forgot: 0 })).toBe("2 easy, 1 hard, 0 forgot");
  });
});

describe("the progress strip", () => {
  it("has one segment per card, coloured by its rating, with the current one marked", () => {
    expect(segments(DECK, RATINGS, 3)).toEqual([
      { id: "a", rated: "easy", current: false },
      { id: "b", rated: "forgot", current: false },
      { id: "c", rated: "hard", current: false },
      { id: "d", rated: null, current: true },
    ]);
  });

  it("gives way to a continuous bar past the cap", () => {
    const long = Array.from({ length: SEGMENT_CAP + 1 }, (_, i) => card(`k${i}`));
    expect(segments(long, {}, 0)).toBeNull();
    expect(segments(long.slice(0, SEGMENT_CAP), {}, 0)).toHaveLength(40);
  });
});

describe("the ones you missed", () => {
  it("are the cards rated hard or forgot, in deck order", () => {
    expect(missed(DECK, RATINGS)).toEqual(["b", "c"]);
    expect(missed(DECK, { a: "easy" })).toEqual([]);
  });

  it("make a round of their own; with none left the round is the whole deck", () => {
    expect(roundDeck(DECK, null)).toBe(DECK);
    expect(roundDeck(DECK, ["c", "b"]).map(c => c.id)).toEqual(["b", "c"]);
    expect(roundDeck(DECK, ["gone"])).toBe(DECK);
  });
});
