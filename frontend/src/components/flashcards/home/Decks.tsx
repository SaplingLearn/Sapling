"use client";
/**
 * The deck grid of the home, and the mix bar that appears over it.
 *
 * A deck is a stack you can press play on: a band in its own colour that
 * carries its name, over a paper body with what is in it (a peek at its
 * concepts, how they are going, one fact) and the play button. Behind it two
 * layers in the same colour make it a stack. A saved set's deck also opens the
 * builder with the set loaded (the deck's body, or "Edit" in its "..." menu),
 * can be renamed or deleted from that menu, and can be ticked. The automatic
 * decks ("All of <course>", "Due today") are not stored: play only, and the
 * first can be ticked too. The last cell builds a set by hand.
 *
 * Ticking decks is how sets are mixed: the bar offers to study the union of
 * their concepts, or to merge them into a new set in the builder.
 */
import React from "react";
import { SET_NAME_MAX, type FlashcardSet } from "@/lib/flashcardSetsApi";
import { useConfirm } from "@/lib/useConfirm";
import { mixable, type Deck } from "./decksModel";
import { masteryLegend, plural, type MasteryCounts } from "./flashcardsModel";
import h from "./home.module.css";

export interface DeckGridProps {
  decks: Deck[];
  /** Ids of the ticked decks. */
  ticked: string[];
  /** The deck a review is being started from (its cards may be being made). */
  playing: string | null;
  /** A review is being started: nothing here starts another. */
  busy: boolean;
  /** The "build one by hand" tile is offered. */
  canBuild: boolean;
  onPlay: (deck: Deck) => void;
  onOpen: (set: FlashcardSet) => void;
  onTick: (deck: Deck) => void;
  onRename: (set: FlashcardSet, name: string) => Promise<boolean>;
  onDelete: (set: FlashcardSet) => void;
  onBuild: () => void;
}

export function DeckGrid(props: DeckGridProps) {
  return (
    <ul className={h.decks} aria-label="Your sets">
      {props.decks.map(deck => (
        <DeckCard
          key={deck.id}
          deck={deck}
          ticked={props.ticked.includes(deck.id)}
          playing={props.playing === deck.id}
          busy={props.busy}
          onPlay={props.onPlay}
          onOpen={props.onOpen}
          onTick={props.onTick}
          onRename={props.onRename}
          onDelete={props.onDelete}
        />
      ))}
      {props.canBuild && (
        <li className={h.deck}>
          <button type="button" className={h.deckNew} onClick={props.onBuild}>
            <span>+ Build one by hand</span>
            <small>pick concepts yourself</small>
          </button>
        </li>
      )}
    </ul>
  );
}

function DeckCard({
  deck, ticked, playing, busy, onPlay, onOpen, onTick, onRename, onDelete,
}: {
  deck: Deck;
  ticked: boolean;
  playing: boolean;
  busy: boolean;
  onPlay: (deck: Deck) => void;
  onOpen: (set: FlashcardSet) => void;
  onTick: (deck: Deck) => void;
  onRename: (set: FlashcardSet, name: string) => Promise<boolean>;
  onDelete: (set: FlashcardSet) => void;
}) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [renaming, setRenaming] = React.useState(false);
  const set = deck.set;
  const classes = [h.deck, ticked ? h.deckSel : "", menuOpen ? h.deckMenuOpen : ""].filter(Boolean).join(" ");
  return (
    <li className={classes} data-palette={deck.palette} data-kind={deck.kind} data-busy={playing || undefined} data-testid={`flashcards-deck-${deck.id}`}>
      <span aria-hidden="true" className={h.layer} />
      <span aria-hidden="true" className={`${h.layer} ${h.layerTwo}`} />
      <div className={h.face}>
        {/* The deck's body: one control stretched over the face, under the
            others, so the whole surface opens the set. */}
        {set && !renaming && (
          <button type="button" className={h.deckOpen} aria-label={`Open ${deck.name}`} title="Open this set" onClick={() => onOpen(set)} />
        )}

        {/* The band: the deck's colour at full strength, with its name. */}
        <div className={h.band}>
          {/* How many cards, large and faint, running off the corner. */}
          <span aria-hidden="true" className={`h-serif ${h.motif}`}>{deck.cards}</span>
          <div className={h.bandTop}>
            {deck.tag && <span className={h.deckTag} data-testid="flashcards-deck-tag">{deck.tag}</span>}
          </div>
          {set && renaming ? (
            <RenameForm
              name={deck.name}
              onCancel={() => setRenaming(false)}
              onSubmit={async name => { if (await onRename(set, name)) setRenaming(false); }}
            />
          ) : (
            <div className={`h-serif ${h.deckName}`}>{deck.name}</div>
          )}
        </div>
        {/* Over the band's top right (outside it, so the menu is not clipped). */}
        <div className={h.corner}>
          {set && (
            <DeckMenu
              name={deck.name}
              open={menuOpen}
              onOpenChange={setMenuOpen}
              onEdit={() => { setMenuOpen(false); onOpen(set); }}
              onRename={() => { setMenuOpen(false); setRenaming(true); }}
              onDelete={() => { setMenuOpen(false); onDelete(set); }}
            />
          )}
          {mixable(deck) && (
            <input type="checkbox" className={h.deckTick} aria-label={`Select ${deck.name}`} checked={ticked} onChange={() => onTick(deck)} />
          )}
        </div>

        <DeckBody deck={deck} busy={busy} onPlay={onPlay} />
      </div>
    </li>
  );
}

/** The paper body: what is in it, how it is going, one fact, play. */
function DeckBody({ deck, busy, onPlay }: { deck: Deck; busy: boolean; onPlay: (deck: Deck) => void }) {
  const fact = deck.fact;
  return (
    <div className={h.deckBody}>
      <div className={h.deckMeta}>{deck.meta}</div>
      <Peek peek={deck.peek} />
      <Mastery counts={deck.mastery} />
      <div className={h.deckFoot}>
        <span className={`${h.deckFact}${fact?.urgent ? ` ${h.deckFactUrgent}` : ""}`} data-testid="flashcards-deck-fact">
          {fact?.text ?? ""}
        </span>
        <button type="button" className={h.play} aria-label={`Review ${deck.name}`} title="Review now" disabled={busy} onClick={() => onPlay(deck)}>
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.5v9l7.5-4.5z" fill="currentColor" /></svg>
        </button>
      </div>
    </div>
  );
}

/** A few of the deck's concepts as chips, then how many more. One line. */
function Peek({ peek }: { peek: Deck["peek"] }) {
  return (
    <div className={h.peek} data-testid="flashcards-deck-peek">
      {peek.shown.map(name => <span key={name} className={h.peekChip}>{name}</span>)}
      {peek.more > 0 && <span className={h.peekMore}>+{peek.more}</span>}
    </div>
  );
}

const pct = (count: number, total: number) => `${total ? Math.round((count / total) * 100) : 0}%`;

/** How much of the deck is mastered, being learned, struggled with, as a bar
 *  and a legend of the groups that have anything in them. What is not started
 *  leaves the track showing, and is not listed. */
function Mastery({ counts }: { counts: MasteryCounts }) {
  const legend = masteryLegend(counts);
  const said = legend.length ? legend.map(p => `${p.count} ${p.kind}`).join(", ") : "not started";
  return (
    <div className={h.masteryBlock}>
      <span className={h.mastery} role="img" aria-label={`Mastery: ${said}`} data-testid="flashcards-mastery">
        {legend.map(p => <i key={p.kind} data-kind={p.kind} style={{ width: pct(p.count, counts.total) }} />)}
      </span>
      <div className={h.legend} aria-hidden="true" data-testid="flashcards-deck-legend">
        {legend.map(p => (
          <span key={p.kind} className={h.legendItem}>
            <i className={h.legendDot} data-kind={p.kind} />{p.count} {p.kind}
          </span>
        ))}
      </div>
    </div>
  );
}

/** "..." on a set's deck: Edit, Rename, and Delete behind a second click. */
function DeckMenu({
  name, open, onOpenChange, onEdit, onRename, onDelete,
}: {
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const owner = React.useRef<HTMLDivElement | null>(null);
  const del = useConfirm(onDelete);
  // Closes on Esc (focus back on "...") or a press anywhere outside it.
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      onOpenChange(false);
      owner.current?.querySelector<HTMLElement>("button")?.focus();
    };
    const onDown = (e: Event) => {
      if (owner.current && e.target instanceof Node && owner.current.contains(e.target)) return;
      onOpenChange(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open, onOpenChange]);
  const toggle = () => { del.reset(); onOpenChange(!open); };
  return (
    <div ref={owner} className={h.deckMenuOwner}>
      <button type="button" className={h.deckMore} aria-label={`More for ${name}`} aria-haspopup="menu" aria-expanded={open} onClick={toggle}>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="currentColor"><circle cx="2.5" cy="7" r="1.3" /><circle cx="7" cy="7" r="1.3" /><circle cx="11.5" cy="7" r="1.3" /></svg>
      </button>
      {open && (
        <div role="menu" aria-label={`${name} actions`} className={h.menu}>
          <button type="button" role="menuitem" className={h.menuItem} onClick={onEdit} autoFocus>Edit</button>
          <button type="button" role="menuitem" className={h.menuItem} onClick={onRename}>Rename</button>
          <button type="button" role="menuitem" className={`${h.menuItem} ${h.menuDanger}${del.armed ? ` ${h.menuArmed}` : ""}`} onClick={del.trigger}>
            {del.armed ? "Click again to delete" : "Delete"}
          </button>
        </div>
      )}
    </div>
  );
}

function RenameForm({ name, onSubmit, onCancel }: { name: string; onSubmit: (name: string) => void; onCancel: () => void }) {
  const [value, setValue] = React.useState(name);
  const input = React.useRef<HTMLInputElement | null>(null);
  React.useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const next = value.trim();
    if (!next || next === name) onCancel();
    else onSubmit(next);
  };
  return (
    <form className={h.rename} onSubmit={submit}>
      <input
        ref={input}
        className={h.field}
        aria-label="Rename set"
        value={value}
        maxLength={SET_NAME_MAX}
        onChange={e => setValue(e.target.value)}
        onBlur={onCancel}
        onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); onCancel(); } }}
      />
    </form>
  );
}

/**
 * The bar over the bottom of the home while decks are ticked. It overlays the
 * page (the grid keeps room for it), so ticking moves nothing.
 */
export function MixBar({
  sets, cards, busy, onStudy, onMerge, onClear,
}: {
  sets: number;
  cards: number;
  busy: boolean;
  onStudy: () => void;
  /** Absent with one deck ticked: there is nothing to merge. */
  onMerge?: () => void;
  onClear: () => void;
}) {
  return (
    <div className={h.mixAnchor}>
      <div className={h.mix} role="region" aria-label="Selected sets" data-testid="flashcards-mix">
        <span role="status" className={h.mixCount}>{plural(sets, "set")} · {plural(cards, "card")}</span>
        <button type="button" className={`${h.mixBtn} ${h.mixPrimary}`} onClick={onStudy} disabled={busy}>
          {onMerge ? "Study together" : "Study"}
        </button>
        {onMerge && <button type="button" className={h.mixBtn} onClick={onMerge}>Merge into one</button>}
        <button type="button" className={h.mixBtn} onClick={onClear}>Clear</button>
      </div>
    </div>
  );
}
