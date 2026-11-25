"use client";
/**
 * One concept on the roadmap. The tile selects the concept (the Up Next block
 * follows it); going INTO a tool for it is the "..." button's menu.
 *
 * The tile is not itself a control: it holds two, the select button (its ring
 * and name) and the "..." button, side by side. A press anywhere else on it
 * still selects, as the select button's own press does, by bubbling up to it.
 */
import React from "react";
import Link from "next/link";
import { Icon } from "../Icon";
import { tileActionsHint, tileCardsLabel, type RoadmapTile as Tile, type TileRelation } from "./hubModel";
import { Glyph, TOOL, WarnIcon, shownTools } from "./hubUi";
import rm from "./Roadmap.module.css";
import s from "./StudyHub.module.css";
import { SC, ST_LABEL, TC, ring, type Concept } from "./studyModel";
import type { SetHub } from "./useHubState";
import type { ToolKey, ToolNav } from "./useToolNav";

/* The small tags that ride a tile's top edge (Roadmap.module.css `.tag`). */
const NEXT_TAG = `${rm.tag} ${rm.tagNext}`;
const RELATION_TAG: Record<Exclude<TileRelation, "">, string> = {
  "Needed First": `${rm.tag} ${rm.tagNeeded}`,
  Unlocks: `${rm.tag} ${rm.tagUnlocks}`,
};

/* A dimmed tile (the legend's filter, or a concept the highlighted one does not
   rest on or unlock) recedes without its words losing AA (spec §13 A135: never
   an opacity dim on text; the whole tile at 30% put them near 1.5:1). Its fill
   drops to the page (.tileDim), its ring and gap mark fade, and its name and
   status go to --text-muted, AA on every tile fill and on the page. The fade
   itself (`.faded`, and the transitions) is Roadmap.module.css's. */
const DIM_TEXT = "var(--text-muted)";
/** The mastery ring's geometry, in its 28px box's units. */
const RING = { box: 28, r: 11.5, stroke: 3, core: 7.5 } as const;

/**
 * The open tile menu closes on Esc (focus returns to its "..." button) or on a
 * press anywhere outside its tile. A press on ANOTHER tile closes this one and
 * that tile's click opens its own, so at most one menu is ever open. (This
 * replaced a full-screen click-catcher inside the tile, which lived in the
 * tile's stacking context and so sat under the later tiles it was meant to
 * cover.)
 */
function useMenuDismiss(open: boolean, owner: React.RefObject<HTMLDivElement | null>, close: () => void) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const tile = owner.current;
      close();
      // Back to the "..." that opened it.
      (tile?.querySelector<HTMLElement>("[data-tile-actions]") ?? tile)?.focus();
    };
    const onDown = (e: Event) => {
      const tile = owner.current;
      if (tile && e.target instanceof Node && tile.contains(e.target)) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open, owner, close]);
}

/** The mastery ring, filled in the concept's status colour once it is started.
 *  `faded` on a dimmed tile: the ring is a picture, so it may fade (text may not). */
function TileRing({ concept, faded }: { concept: Concept; faded: boolean }) {
  const color = TC[concept.st];
  return (
    <span className={faded ? `${rm.ring} ${rm.faded}` : rm.ring}>
      <svg width={RING.box} height={RING.box} viewBox={`0 0 ${RING.box} ${RING.box}`} aria-hidden="true" className={rm.ringSvg}>
        <circle cx={RING.box / 2} cy={RING.box / 2} r={RING.r} fill="none" stroke="var(--bg-soft)" strokeWidth={RING.stroke} />
        <circle cx={RING.box / 2} cy={RING.box / 2} r={RING.r} fill="none" stroke={color} strokeWidth={RING.stroke} strokeLinecap="round" strokeDasharray={ring(concept.m, RING.r)} className={s.ring} />
        <circle cx={RING.box / 2} cy={RING.box / 2} r={RING.core} fill={concept.st === "new" ? "transparent" : color} />
      </svg>
      <span className={rm.ringCheck}>
        {concept.st === "mastered" && <Icon name="check" size={10} />}
      </span>
    </span>
  );
}

/** What rides the tile besides its name: "Next", how it relates to the hot
 *  concept, and the mark for a prerequisite that is not mastered yet. */
function TileMarks({ tile }: { tile: Tile }) {
  const { t, isSel, isNext, rel, dim } = tile;
  return (
    <>
      {isNext && !isSel && <span className={NEXT_TAG}>Next</span>}
      {rel && <span className={RELATION_TAG[rel]}>{rel}</span>}
      {!!t.gap && !rel && <span title={t.gap} className={dim ? `${rm.gapMark} ${rm.faded}` : rm.gapMark}><WarnIcon size={14} /></span>}
    </>
  );
}

function TileMenu({ concept, cardCount, quizShown, nav, onClose }: {
  concept: Concept;
  cardCount: number;
  quizShown: boolean;
  nav: ToolNav;
  onClose: () => void;
}) {
  const actions: { key: ToolKey; label: string; href: string }[] = [
    { key: "quiz", label: "Quiz Me", href: nav.quizHref(concept.id) },
    { key: "cards", label: tileCardsLabel(cardCount), href: nav.cardsHref([concept.name]) },
  ];
  const follow = (href: string) => (e: React.MouseEvent) => {
    e.stopPropagation();
    onClose();
    // A Cmd/Ctrl-click is the browser's (a new tab); a plain one leaves through the hub's fade.
    if (e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    nav.leaveTo(href);
  };
  return (
    // A press on an item follows the link; it must not also reach the tile's select.
    <div role="menu" aria-label={`${concept.name} actions`} className={`${s.pop} ${s.popover} ${rm.menu}`} onClick={e => e.stopPropagation()}>
      {shownTools(actions, quizShown).map(ac => (
        <Link key={ac.label} role="menuitem" href={ac.href} className={`${rm.menuItem} ${s.hoverOption}`} onClick={follow(ac.href)}>
          <span className={rm.menuGlyph} style={{ background: TOOL[ac.key].bg, color: TOOL[ac.key].fg }}><Glyph name={TOOL[ac.key].icon} size={12} /></span>
          {ac.label}
        </Link>
      ))}
    </div>
  );
}

const tileClass = (isSel: boolean, isNext: boolean, dim: boolean) => {
  const dimmed = dim ? ` ${s.tileDim}` : "";
  if (isSel) return `${s.tile} ${s.tileSel}${dimmed}`;
  return isNext ? `${s.tile} ${s.tileNext}${dimmed}` : `${s.tile}${dimmed}`;
};

const statusLine = (t: Concept) => (t.st === "new" ? "Not Started" : `${ST_LABEL[t.st]} · ${t.m}%`);

export function RoadmapTile({ tile, menuOpen, cardCount, quizShown, nav, set, closeTileMenu }: {
  tile: Tile;
  menuOpen: boolean;
  /** Flashcards the student already has on this concept. */
  cardCount: number;
  quizShown: boolean;
  nav: ToolNav;
  set: SetHub;
  closeTileMenu: (conceptId: string) => void;
}) {
  const { t, isSel, isNext, dim } = tile;
  const owner = React.useRef<HTMLDivElement | null>(null);
  const closeMenu = React.useCallback(() => closeTileMenu(t.id), [closeTileMenu, t.id]);
  useMenuDismiss(menuOpen, owner, closeMenu);
  const toggle = () => set({ topic: isSel ? null : t.id, tileMenu: null });
  return (
    // Every press on the tile that a control inside it does not keep (the
    // "..." and its menu stop theirs) selects: the select button's click,
    // Enter or Space on it (its own click), or a click on the padding or marks.
    // The tile that owns the open menu is lifted above its siblings, or the next tile paints over the menu.
    <div ref={owner} data-testid={`tile-${t.id}`} data-flip={`tile:${t.id}`} data-dim={dim || undefined} className={`${tileClass(isSel, isNext, dim)} ${rm.tileBox}${menuOpen ? ` ${s.lifted}` : ""}`}
      onClick={toggle}
      onMouseEnter={() => set({ hover: t.id })} onMouseLeave={() => set({ hover: null })}>
      {/* No handler of its own: its click bubbles to the tile's. */}
      <button type="button" aria-pressed={isSel} className={s.tileSelect} data-testid={`study-tile-select-${t.id}`}>
        <TileRing concept={t} faded={dim} />
        <span className={rm.tileText}>
          <span className={rm.tileName} style={{ color: dim ? DIM_TEXT : undefined }}>{t.name}</span>
          <span className={rm.tileStatus} style={{ color: dim ? DIM_TEXT : SC[t.st] }}>{statusLine(t)}</span>
        </span>
      </button>
      <TileMarks tile={tile} />
      <button type="button" className={s.tileMore} data-testid={`tile-actions-${t.id}`} data-tile-actions=""
        aria-label={`Actions for ${t.name}`} title={tileActionsHint(quizShown)} aria-haspopup="menu" aria-expanded={menuOpen}
        onClick={e => { e.stopPropagation(); set({ topic: t.id, tileMenu: menuOpen ? null : t.id }); }}>
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true" fill="currentColor"><circle cx="2.5" cy="7" r="1.3" /><circle cx="7" cy="7" r="1.3" /><circle cx="11.5" cy="7" r="1.3" /></svg>
      </button>
      {menuOpen && <TileMenu concept={t} cardCount={cardCount} quizShown={quizShown} nav={nav} onClose={() => set({ tileMenu: null })} />}
    </div>
  );
}
