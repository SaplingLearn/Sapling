/**
 * W8.4 — honest microcopy for generate / review.
 *
 * Flashcards are retrieval practice (self-rated; card FSRS only). Concept
 * mastery / learner_state / Study-next live on the learner model when
 * `learning_loop` is on — never implied from cards alone. Tier words on the
 * deck bar (`mastered` / `learning` / `struggling`) stay Study's language;
 * the label says they are map status, not a score from this deck.
 */

/** Aria for the deck bar that mirrors concept tiers on the map. */
export const mapStatusAria = (said: string) => `On your map: ${said}`;

/** Quiet legend caption under the bar. */
export const MAP_STATUS_HINT = "On your map — not from cards alone";

/** End-of-review summary: ratings ≠ concept mastery. */
export const REVIEW_DONE_NOTE =
  "Ratings schedule these cards. Concept mastery lives on Study, not from this deck alone.";

/** Hero line under the prompt — generate / start path. */
export const HERO_PRACTICE_NOTE =
  "Retrieval practice. Mastery and due reviews live on Study when the learning loop is on.";

/** Import / AI generate dialog subtitle. */
export const IMPORT_PRACTICE_NOTE =
  "Cards are retrieval practice — they don't set concept mastery on their own.";
