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
import { INHERIT_FONT } from "@/lib/inheritFont";
import { Icon } from "../Icon";
import { tileActionsHint, tileCardsLabel, type RoadmapTile as Tile, type TileRelation } from "./hubModel";
import { Glyph, MONO, POPOVER, TOOL, WarnIcon, shownTools } from "./hubUi";
import s from "./StudyHub.module.css";
import { SC, ST_LABEL, TC, ring, type Concept } from "./studyModel";
import type { SetHub } from "./useHubState";
import type { ToolKey, ToolNav } from "./useToolNav";

/* The small tags that ride a tile's top edge: the `.chip` voice, tile-sized. */
const TAG: React.CSSProperties = { position: "absolute", top: -7, right: 8, height: 15, padding: "0 6px", borderRadius: "var(--r-full)", fontFamily: MONO, fontSize: 9, letterSpacing: "0.06em", textTransform: "uppercase", fontWeight: 600, display: "inline-flex", alignItems: "center", boxShadow: "0 0 0 2px var(--bg)" };
const NEXT_TAG: React.CSSProperties = { ...TAG, background: "var(--brand-forest)", color: "#FFFFFF" };
const RELATION_TAG: Record<Exclude<TileRelation, "">, React.CSSProperties> = {
  "Needed First": { ...TAG, background: "var(--warn-soft)", color: "var(--warn)" },
  Unlocks: { ...TAG, background: "var(--info-soft)", color: "var(--info)" },
};

/* A dimmed tile (the legend's filter, or a concept the highlighted one does not
   rest on or unlock) recedes without its words losing AA (spec §13 A135: never
   an opacity dim on text; the whole tile at 30% put them near 1.5:1). Its fill
   drops to the page (.tileDim), its ring and gap mark fade, and its name and
   status go to --text-muted, AA on every tile fill and on the page. */
const DIM_OPACITY = 0.3;
const DIM_TEXT = "var(--text-muted)";
const DIM_FADE = "opacity 160ms ease, color 160ms ease";

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
    <span style={{ position: "relative", width: 28, height: 28, flexShrink: 0, opacity: faded ? DIM_OPACITY : 1, transition: DIM_FADE }}>
      <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" style={{ display: "block", transform: "rotate(-90deg)" }}>
        <circle cx="14" cy="14" r="11.5" fill="none" stroke="var(--bg-soft)" strokeWidth="3" />
        <circle cx="14" cy="14" r="11.5" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={ring(concept.m, 11.5)} />
        <circle cx="14" cy="14" r="7.5" fill={concept.st === "new" ? "transparent" : color} />
      </svg>
      <span style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "#FFFFFF" }}>
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
      {isNext && !isSel && <span style={NEXT_TAG}>Next</span>}
      {rel && <span style={RELATION_TAG[rel]}>{rel}</span>}
      {!!t.gap && !rel && <span title={t.gap} style={{ display: "block", lineHeight: 0, flexShrink: 0, opacity: dim ? DIM_OPACITY : 1, transition: DIM_FADE }}><WarnIcon size={14} /></span>}
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
    <div role="menu" aria-label={`${concept.name} actions`} className={s.pop} onClick={e => e.stopPropagation()}
      style={{ position: "absolute", left: 0, right: 0, top: "calc(100% + 6px)", zIndex: 21, minWidth: 200, ...POPOVER, borderRadius: "var(--r-md)", padding: 4, display: "flex", flexDirection: "column", gap: 2, cursor: "default" }}>
      {shownTools(actions, quizShown).map(ac => (
        <Link key={ac.label} role="menuitem" href={ac.href} className={s.hoverOption} onClick={follow(ac.href)}
          style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 6px", border: 0, borderRadius: "var(--r-sm)", background: "transparent", ...INHERIT_FONT, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--text)", textAlign: "left", textDecoration: "none", cursor: "pointer" }}>
          <span style={{ width: 24, height: 24, borderRadius: 6, background: TOOL[ac.key].bg, color: TOOL[ac.key].fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={TOOL[ac.key].icon} size={12} /></span>
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
    <div ref={owner} data-testid={`tile-${t.id}`} data-flip={`tile:${t.id}`} data-dim={dim || undefined} className={tileClass(isSel, isNext, dim)}
      onClick={toggle}
      onMouseEnter={() => set({ hover: t.id })} onMouseLeave={() => set({ hover: null })}
      // The tile that owns the open menu is lifted above its siblings, or the next tile paints over the menu.
      style={{ position: "relative", zIndex: menuOpen ? 2 : undefined, display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: "var(--r-md)", cursor: "pointer" }}>
      {/* No handler of its own: its click bubbles to the tile's. */}
      <button type="button" aria-pressed={isSel} className={s.tileSelect} data-testid={`study-tile-select-${t.id}`}>
        <TileRing concept={t} faded={dim} />
        <span style={{ flex: 1, minWidth: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <span style={{ fontSize: "var(--fs-md)", fontWeight: 600, lineHeight: 1.25, textWrap: "pretty", color: dim ? DIM_TEXT : undefined, transition: DIM_FADE } as React.CSSProperties}>{t.name}</span>
          <span style={{ fontSize: "var(--fs-xs)", color: dim ? DIM_TEXT : SC[t.st], whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", transition: DIM_FADE }}>{statusLine(t)}</span>
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
