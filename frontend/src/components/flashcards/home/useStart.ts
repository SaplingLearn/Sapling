"use client";
/**
 * Start: turn a selection into a review deck.
 *
 * Every ticked concept that has no cards gets them generated first, ONE
 * concept at a time, so each new card's topic is exactly that concept's name
 * (which is how cards and concepts are matched). A failed generation toasts
 * and the run moves on; a rate limit ends the generating early, since every
 * later call would fail the same way. "Only what's due" never generates: a
 * card made a moment ago is not what the student asked for.
 *
 * One run at a time, and the latest wins: a course switch (`cancel`) or an
 * unmount drops whatever the run still has in flight.
 */
import React from "react";
import { generateFlashcards } from "@/lib/api";
import { humanizeError, statusOf } from "@/lib/errorMessage";
import { useLatestRequest, type RequestToken } from "@/lib/useLatestRequest";
import { useToast } from "../../ToastProvider";
import {
  buildDeck,
  cardsInCourse,
  countsFor,
  emptyDeckReason,
  hasDueData,
  indexCards,
  type Card,
} from "./flashcardsModel";
import type { CardsState } from "./useFlashcardsData";

export interface StartPlan {
  /** The selection, in the order an unshuffled deck should run. */
  names: string[];
  /** The names cards may be generated for when they have none. Default: all
   *  of `names`. (The home's "everything" deck generates for none.) */
  generate?: string[];
  onlyDue: boolean;
  shuffle: boolean;
  perConcept: number;
  /** What the review's header calls the deck. */
  title: string;
}

export interface StartProgress {
  /** The concept cards are being made for. */
  name: string;
  at: number;
  of: number;
}

interface StartInput {
  userId: string;
  courseId: string;
  courseName?: string | null;
  semester: string;
  cards: CardsState;
  conceptNames: string[];
  random: () => number;
  onDeck: (deck: Card[], title: string) => void;
}

/** Said once per Start, for the concepts no card could be made for. */
export function noCardsMessage(names: string[]): string {
  const which = names.length === 1 ? names[0] : `${names[0]} and ${names.length - 1} more`;
  return `No cards could be made for ${which}. Your course material may not cover it yet.`;
}

/** The line that says a review is being started: which concept is being
 *  made, or (when nothing started) why. */
export function startStatus(progress: StartProgress | null, running: boolean, notice: string | null): string {
  if (progress) return `Making cards for ${progress.name}… ${progress.at} of ${progress.of}`;
  if (running) return "Getting your cards ready…";
  return notice ?? "";
}

export function useStart(input: StartInput) {
  const toast = useToast();
  const [progress, setProgress] = React.useState<StartProgress | null>(null);
  const [running, setRunning] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const req = useLatestRequest();
  /** Closes the gap before `running` re-renders: a second press of Start in
   *  the same tick would otherwise generate everything twice. */
  const busy = React.useRef(false);
  // The run outlives the render that started it; it reads the page's current
  // state through this.
  const live = React.useRef(input);
  React.useEffect(() => { live.current = input; });

  /** Generates for each name in turn; resolves with the cards that were made. */
  const generate = React.useCallback(async (names: string[], perConcept: number, run: RequestToken) => {
    const { userId, courseId, semester } = live.current;
    const made: Card[] = [];
    /** Asked for and answered with no cards: the generator writes from the
     *  course's material, and makes nothing for a concept it does not cover. */
    const none: string[] = [];
    for (let i = 0; i < names.length && run.isCurrent(); i++) {
      setProgress({ name: names[i], at: i + 1, of: names.length });
      try {
        const r = await generateFlashcards(userId, names[i], perConcept, semester || undefined, courseId || undefined);
        const cards = r.flashcards || [];
        if (!cards.length) none.push(names[i]);
        made.push(...cards);
      } catch (err) {
        if (!run.isCurrent()) break;
        console.error("flashcard generate failed", err);
        toast.error(humanizeError(err, `Couldn't make cards for ${names[i]}.`));
        if (statusOf(err) === 429) break;
      }
    }
    if (none.length && run.isCurrent()) toast.warn(noCardsMessage(none));
    return made;
  }, [toast]);

  /** Resolves true when a review was started. */
  const start = React.useCallback(async (plan: StartPlan): Promise<boolean> => {
    if (busy.current) return false;
    busy.current = true;
    const { courseId, courseName, cards, conceptNames, random, onDeck } = live.current;
    const run = req.begin();
    // What was asked for counts as this course's concepts even before the map
    // has loaded (the hub's deep link starts as soon as the cards are in).
    const known = [...conceptNames, ...plan.names];
    const indexOf = (list: Card[]) =>
      indexCards(cardsInCourse(list, courseId, { name: courseName, conceptNames: known }), conceptNames, { now: cards.now, showDue: hasDueData(list) });
    setRunning(true);
    setNotice(null);
    try {
      let all = cards.cards;
      const have = indexOf(all);
      const missing = plan.onlyDue ? [] : (plan.generate ?? plan.names).filter(name => !countsFor(have, name).cards);
      if (missing.length) {
        const made = await generate(missing, plan.perConcept, run);
        if (!run.isCurrent()) return false;
        if (made.length) {
          // The re-read list is the truth; what the generate calls returned
          // stands in for anything it does not (yet) hold, or for a re-read
          // that failed.
          const fresh = (await cards.reload()) ?? all;
          if (!run.isCurrent()) return false;
          const held = new Set(fresh.map(c => c.id));
          all = [...fresh, ...made.filter(c => !held.has(c.id))];
        }
      }
      const deck = buildDeck({ names: plan.names, index: indexOf(all), onlyDue: plan.onlyDue, shuffle: plan.shuffle, random });
      if (!deck.length) {
        setNotice(emptyDeckReason(plan.onlyDue, missing.length > 0));
        return false;
      }
      onDeck(deck, plan.title);
      return true;
    } finally {
      // A run that was cancelled has already been cleared (and may have been
      // followed by another, which these now belong to).
      if (run.isCurrent()) {
        busy.current = false;
        setProgress(null);
        setRunning(false);
      }
    }
  }, [req, generate]);

  /** Drops the run in flight and anything it said. */
  const cancel = React.useCallback(() => {
    req.cancel();
    busy.current = false;
    setProgress(null);
    setRunning(false);
    setNotice(null);
  }, [req]);

  const clearNotice = React.useCallback(() => setNotice(null), []);

  return { start, cancel, clearNotice, progress, running, notice };
}
