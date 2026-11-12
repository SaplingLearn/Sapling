/**
 * Pure derivations behind the review's colour: what each card was rated this
 * session, and what the progress strip, the running tally and the end-of-deck
 * summary make of it.
 *
 * Ratings are kept per card id for ONE pass through the deck. Everything here
 * reads them through the deck it is given, so a card deleted mid-review simply
 * stops counting.
 */
import type { Card } from "../home/flashcardsModel";

export type Rated = "easy" | "hard" | "forgot";

/** The three rating buttons, in key order. `n` is what the API stores. */
export const RATING_OPTIONS: { n: 1 | 2 | 3; kind: Rated; hint: string }[] = [
  { n: 1, kind: "forgot", hint: "1" },
  { n: 2, kind: "hard", hint: "2" },
  { n: 3, kind: "easy", hint: "3" },
];

export const ratedAs = (n: number): Rated => RATING_OPTIONS.find(o => o.n === n)?.kind ?? "forgot";

/** Card id -> how it was rated this session. */
export type Ratings = Readonly<Record<string, Rated>>;

export interface Tally {
  easy: number;
  hard: number;
  forgot: number;
}

/** The order the tally and the summary list the three in. */
export const TALLY_ORDER: Rated[] = ["easy", "hard", "forgot"];

export function tally(deck: Card[], ratings: Ratings): Tally {
  const out: Tally = { easy: 0, hard: 0, forgot: 0 };
  for (const card of deck) {
    const rated = ratings[card.id];
    if (rated) out[rated] += 1;
  }
  return out;
}

/** "2 easy, 1 hard, 0 forgot" */
export const tallyLabel = (t: Tally) => TALLY_ORDER.map(kind => `${t[kind]} ${kind}`).join(", ");

/** Past this many cards the strip is one continuous bar again. */
export const SEGMENT_CAP = 40;

export interface Segment {
  id: string;
  rated: Rated | null;
  current: boolean;
}

/** One segment per card, or null for a deck too long to show card by card. */
export function segments(deck: Card[], ratings: Ratings, current: number): Segment[] | null {
  if (deck.length > SEGMENT_CAP) return null;
  return deck.map((card, i) => ({ id: card.id, rated: ratings[card.id] ?? null, current: i === current }));
}

/** The cards rated hard or forgot, in deck order: what "the N you missed" reviews. */
export const missed = (deck: Card[], ratings: Ratings): string[] =>
  deck.filter(card => ratings[card.id] === "hard" || ratings[card.id] === "forgot").map(card => card.id);

/** The cards a round reviews: the whole deck, or the missed ones still in it. */
export function roundDeck(deck: Card[], round: string[] | null): Card[] {
  if (!round) return deck;
  const only = new Set(round);
  const subset = deck.filter(card => only.has(card.id));
  // Every card of the round was deleted: back to the whole deck.
  return subset.length ? subset : deck;
}

// ── the keyboard ─────────────────────────────────────────────────────────────

/** What a key asks of the review. */
export type KeyIntent =
  | { kind: "flip" }
  | { kind: "step"; by: -1 | 1 }
  | { kind: "rate"; n: 1 | 2 | 3 };

const STEP_KEYS = new Map<string, -1 | 1>([["ArrowLeft", -1], ["ArrowRight", 1]]);
const RATE_KEYS = new Map<string, 1 | 2 | 3>(RATING_OPTIONS.map(o => [o.hint, o.n]));

/** Space or up/down flips; left/right move between cards; 1/2/3 rate. */
export function keyIntent(e: Pick<KeyboardEvent, "key" | "code">): KeyIntent | null {
  if (e.code === "Space" || e.key === "ArrowUp" || e.key === "ArrowDown") return { kind: "flip" };
  const by = STEP_KEYS.get(e.key);
  if (by) return { kind: "step", by };
  const n = RATE_KEYS.get(e.key);
  return n ? { kind: "rate", n } : null;
}
