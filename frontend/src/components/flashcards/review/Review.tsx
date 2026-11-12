"use client";
/**
 * The review: a deck of flip cards, rated forgot / hard / easy.
 *
 * What a session looks like is driven by how each card was rated in it: the
 * strip above the card has one segment per card in that rating's colour, a
 * tally counts the three beside "Card N of M", and the end of the deck is a
 * summary with a way to go again through just the cards that were missed.
 * The rules for those are pure functions in reviewModel.ts.
 *
 * Behaviour pinned since #769: one rating per card however many times the key
 * or button fires while it saves; a failed rating does not advance; the end of
 * the deck is an explicit state. Keyboard: Space flips, the left and right
 * arrows move to the previous / next card without rating, and 1 / 2 / 3 rate
 * once the answer is showing.
 */
import React from "react";
import dynamic from "next/dynamic";
import { useUser } from "@/context/UserContext";
import { deleteFlashcard, rateFlashcard } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { Icon } from "../../Icon";
import { useToast } from "../../ToastProvider";
import type { Card } from "../home/flashcardsModel";
import rv from "./review.module.css";
import {
  RATING_OPTIONS,
  TALLY_ORDER,
  missed,
  ratedAs,
  roundDeck,
  segments,
  tally,
  tallyLabel,
  type Ratings,
  type Tally,
} from "./reviewModel";
import type { ReviewProgress } from "./reviewSession";

// Lazy-load to keep mermaid/katex/highlight.js out of the OpenNext server
// bundle. See ChatPanel.tsx for the rationale.
const MarkdownChat = dynamic(
  () => import("../../chat/MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

export interface ReviewProps {
  /** The cards chosen at Start, in review order. */
  deck: Card[];
  /** The course's colour (any CSS colour): the card's accent. */
  accent: string;
  /** The review was started from the home, so the summary offers the way back. */
  fromHome: boolean;
  onRated: () => void;
  onDeleted: (cardId: string) => void;
  onAllSets: () => void;
  /** Where to open: a review read back after a reload (reviewSession.ts). */
  initial?: ReviewProgress;
  /** Told where the review is whenever that changes. Must be stable. */
  onProgress?: (progress: ReviewProgress) => void;
}

const FROM_THE_TOP: ReviewProgress = { idx: 0, ratings: {}, round: null, done: false };

export function Review({ deck, accent, fromHome, onRated, onDeleted, onAllSets, initial = FROM_THE_TOP, onProgress }: ReviewProps) {
  const toast = useToast();
  const { userId } = useUser();
  /** The cards of a "review the ones you missed" round; null: the whole deck. */
  const [round, setRound] = React.useState<string[] | null>(initial.round);
  const active = React.useMemo(() => roundDeck(deck, round), [deck, round]);
  const [idx, setIdx] = React.useState(initial.idx);
  const [flipped, setFlipped] = React.useState(false);
  // Review-session state (#769). `rating` is the in-flight guard: one rating
  // per card, however many times the button/key fires while it's saving
  // (the ref closes the same-tick gap before the state re-renders). `done`
  // is the explicit end-of-deck state — rating the last card used to wrap
  // silently back to card 1.
  const [rating, setRating] = React.useState(false);
  const ratingRef = React.useRef(false);
  const [done, setDone] = React.useState(initial.done);
  /** How each card was rated in this pass. */
  const [ratings, setRatings] = React.useState<Ratings>(initial.ratings);
  React.useEffect(() => { onProgress?.({ idx, ratings, round, done }); }, [idx, ratings, round, done, onProgress]);

  React.useEffect(() => {
    if (idx >= active.length) setIdx(0);
    setFlipped(false);
  }, [active.length, idx]);

  const card = active[idx];

  const rate = React.useCallback(async (r: number) => {
    if (!card || ratingRef.current) return;
    ratingRef.current = true;
    setRating(true);
    try {
      await rateFlashcard(userId, card.id, r);
    } catch (err) {
      // On failure the card does NOT advance (#769): it stays up and
      // flipped, so pressing the rating again retries it. Advancing would
      // silently drop the review from the student's schedule.
      console.error("rate failed", err);
      toast.error(humanizeError(err, "Couldn't save that rating. Try again."));
      return;
    } finally {
      ratingRef.current = false;
      setRating(false);
    }
    onRated();
    setRatings(prev => ({ ...prev, [card.id]: ratedAs(r) }));
    setFlipped(false);
    if (idx >= active.length - 1) setDone(true);
    else setIdx(idx + 1);
  }, [card, userId, idx, active.length, toast, onRated]);

  /** A new pass: the whole deck, or only the given cards. */
  const begin = (only: string[] | null) => {
    setRound(only);
    setRatings({});
    setDone(false);
    setIdx(0);
    setFlipped(false);
  };

  const remove = React.useCallback(async () => {
    if (!card) return;
    try {
      await deleteFlashcard(userId, card.id);
      toast.success("Card deleted");
      // As before, a deck that lost a card starts over at its first. What was
      // rated stays rated; the deleted card just stops counting.
      onDeleted(card.id);
      setDone(false);
      setIdx(0);
      setFlipped(false);
    } catch (err) {
      console.error("flashcard delete failed", err);
      toast.error(humanizeError(err, "Couldn't delete that card."));
    }
  }, [card, userId, toast, onDeleted]);

  /** Step to the previous (-1) or next (+1) card without rating this one. It
   *  stops at either end of the deck (no wrap), and waits out a rating that
   *  is still saving so the save cannot land on a different card. */
  const step = React.useCallback((by: -1 | 1) => {
    if (done || ratingRef.current) return;
    const next = idx + by;
    if (next < 0 || next >= active.length) return;
    setIdx(next);
    setFlipped(false);
  }, [done, idx, active.length]);

  // Keyboard: Space or up/down flips; left/right move between cards; 1/2/3 rate when flipped.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
      // A held key auto-repeats: one physical press = one action.
      if (e.repeat) return;
      if (e.code === "Space" || e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault(); setFlipped(f => !f); return;
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        step(e.key === "ArrowLeft" ? -1 : 1);
        return;
      }
      if (!flipped || !card || done) return;
      if (e.key === "1") rate(1);
      else if (e.key === "2") rate(2);
      else if (e.key === "3") rate(3);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flipped, rate, step, card, done]);

  const stage = { "--fc-accent": accent } as React.CSSProperties;

  if (!deck.length) {
    return (
      <div className={rv.stage}>
        <div className={rv.message}>
          <div className="h-serif" style={{ fontSize: "var(--fs-2xl)", color: "var(--text)" }}>No cards left here</div>
          <div style={{ marginTop: 6 }}>Every card in this deck was deleted.</div>
          <button type="button" className="btn btn--primary" style={{ marginTop: 16 }} onClick={onAllSets}>Back to all sets</button>
        </div>
      </div>
    );
  }

  // Between a deck shrinking and the index following it: nothing to show yet.
  if (!done && !card) return <div className={rv.stage} />;

  if (done) {
    return (
      <div className={rv.stage} style={stage}>
        <Summary
          counts={tally(active, ratings)}
          missedIds={missed(active, ratings)}
          onAgain={() => begin(null)}
          onMissed={ids => begin(ids)}
          onAllSets={fromHome ? onAllSets : undefined}
        />
      </div>
    );
  }

  return (
    <div className={rv.stage} style={stage}>
      <Progress deck={active} ratings={ratings} idx={idx} />
      <FlipCard flipped={flipped} onFlip={() => setFlipped(f => !f)} card={card} />
      <div className={rv.rates}>
        {RATING_OPTIONS.map(r => (
          <button key={r.n} type="button" className={rv.rate} data-kind={r.kind} onClick={() => rate(r.n)}
            disabled={!flipped || rating} title={`${r.kind} (press ${r.hint})`}>
            {r.kind}
            <span className={`mono ${rv.key}`}>{r.hint}</span>
          </button>
        ))}
      </div>
      <div className={rv.foot}>
        <span>Space or ↑ ↓ to flip · ← → to go back and forth · 1 / 2 / 3 to rate</span>
        <button type="button" onClick={remove} className={`btn btn--sm btn--ghost ${rv.delete}`} title="Delete this card">
          <Icon name="x" size={11} /> Delete card
        </button>
      </div>
    </div>
  );
}

// ── progress ─────────────────────────────────────────────────────────────────

/** The three counts with their colours: beside the card count, and in the summary. */
function TallyDots({ counts, withWords = false, className }: { counts: Tally; withWords?: boolean; className: string }) {
  return (
    <span className={className} role="group" data-testid="flashcards-tally" aria-label={`This session: ${tallyLabel(counts)}`}>
      {TALLY_ORDER.map(kind => (
        <span key={kind} className={rv.tallyItem} data-testid={`flashcards-tally-${kind}`} title={kind}>
          <span aria-hidden="true" className={rv.dot} data-kind={kind} />
          {withWords ? <span><b>{counts[kind]}</b> {kind}</span> : counts[kind]}
        </span>
      ))}
    </span>
  );
}

/** "Card N of M", the running tally, and one segment per card (a plain bar for
 *  a deck too long to show card by card). */
function Progress({ deck, ratings, idx }: { deck: Card[]; ratings: Ratings; idx: number }) {
  const parts = segments(deck, ratings, idx);
  const strip = {
    role: "progressbar",
    "aria-label": "Cards reviewed",
    "aria-valuemin": 1,
    "aria-valuemax": deck.length,
    "aria-valuenow": idx + 1,
  } as const;
  return (
    <div className={rv.column}>
      <div className={rv.meta}>
        <span>Card {idx + 1} of {deck.length}</span>
        <TallyDots counts={tally(deck, ratings)} className={rv.tally} />
      </div>
      {parts ? (
        <div {...strip} className={rv.segments} data-testid="flashcards-segments">
          {parts.map(p => (
            <span key={p.id} className={rv.segment} data-testid="flashcards-segment" data-rated={p.rated ?? "unseen"} data-current={p.current} />
          ))}
        </div>
      ) : (
        <div {...strip} className={rv.progress} data-testid="flashcards-progress-bar">
          <div className={rv.progressFill} style={{ transform: `scaleX(${(idx + 1) / deck.length})` }} />
        </div>
      )}
    </div>
  );
}

// ── the card ─────────────────────────────────────────────────────────────────

function FlipCard({ flipped, onFlip, card }: { flipped: boolean; onFlip: () => void; card: Card }) {
  const topic = (card.topic ?? "").trim();
  return (
    <div className={rv.card} onClick={onFlip}>
      <div className={rv.cardInner} data-flipped={flipped} data-testid="flashcards-card">
        <div className={rv.face}>
          {topic && (
            <div className={rv.faceHead}>
              <span className={rv.topic} data-testid="flashcards-topic">{topic}</span>
            </div>
          )}
          <div className={`h-serif ${rv.faceText}`}>
            <MarkdownChat>{card.front}</MarkdownChat>
          </div>
          <div className={rv.faceHint}>Click or press Space to reveal</div>
        </div>
        <div className={`${rv.face} ${rv.faceBack}`}>
          <div className={`h-serif ${rv.faceText}`}>
            <MarkdownChat>{card.back}</MarkdownChat>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── deck complete ────────────────────────────────────────────────────────────

/** How the session went, and what next. */
function Summary({
  counts, missedIds, onAgain, onMissed, onAllSets,
}: {
  counts: Tally;
  missedIds: string[];
  onAgain: () => void;
  onMissed: (ids: string[]) => void;
  /** Absent when the review was not started from the home. */
  onAllSets?: () => void;
}) {
  const shown = TALLY_ORDER.filter(kind => counts[kind] > 0);
  return (
    <div className={rv.summary} data-testid="flashcards-summary">
      <div className={`h-serif ${rv.summaryTitle}`}>Deck complete</div>
      <div className={rv.stack} role="img" aria-label={`This session: ${tallyLabel(counts)}`}>
        {shown.map(kind => (
          <span key={kind} className={rv.stackPart} data-kind={kind} data-testid={`flashcards-stack-${kind}`} style={{ flexGrow: counts[kind] }} />
        ))}
      </div>
      <TallyDots counts={counts} withWords className={rv.counts} />
      <div className={rv.summaryActions}>
        <button type="button" className="btn btn--primary" onClick={onAgain}>Review again</button>
        {missedIds.length > 0 && (
          <button type="button" className="btn" onClick={() => onMissed(missedIds)}>
            Review the {missedIds.length} you missed
          </button>
        )}
        {onAllSets && (
          <button type="button" className="btn btn--ghost" onClick={onAllSets}>
            <Icon name="chevron-left" size={12} /> All sets
          </button>
        )}
      </div>
    </div>
  );
}
