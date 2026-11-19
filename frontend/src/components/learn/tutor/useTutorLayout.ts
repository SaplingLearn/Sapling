"use client";
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

/** The widths tutor.module.css gives the tutor sidebar (`.side`) and the session
 *  panel (`.panel`); the conversation column takes what is left. */
export const SIDEBAR_W = 252;
export const PANEL_W = 300;
/** The narrowest conversation column that still reads as prose (about ten words
 *  a line) and shows the composer's placeholder whole. */
export const MIN_CHAT_W = 560;

/**
 * Which side columns are open in a shell `width` px wide (null: not measured
 * yet, read as wide). An explicit choice (`side` / `panel`, from the student's
 * own Show/Hide) always stands; a column with no choice opens only while the
 * conversation keeps MIN_CHAT_W beside it. The session panel gives way first;
 * the sidebar gives way to a panel the student asked for, while that panel can
 * show at all (`panelShows`: a live session on screen).
 */
export function tutorColumns(
  width: number | null,
  side: boolean | null,
  panel: boolean | null,
  panelShows = true,
): { side: boolean; panel: boolean } {
  const w = width ?? Number.POSITIVE_INFINITY;
  const sideOpen = side ?? w >= MIN_CHAT_W + SIDEBAR_W + (panel === true && panelShows ? PANEL_W : 0);
  const panelOpen = panel ?? w >= MIN_CHAT_W + PANEL_W + (sideOpen ? SIDEBAR_W : 0);
  return { side: sideOpen, panel: panelOpen };
}

/** The control each Show/Hide hands keyboard focus to: the one that undoes it. */
const FOCUS_AFTER = {
  showSide: "tutor-sidebar-hide",
  hideSide: "tutor-sidebar-show",
  showPanel: "tutor-panel-hide",
  hidePanel: "tutor-panel-toggle",
} as const;

/**
 * The Tutor shell's two side columns (wireframe "AI tutor structure layout V2").
 * On a computer the sidebar and the session panel sit beside the conversation
 * and collapse on their own when the shell is too narrow for both (U5: at about
 * 950px wide the conversation was three words a line). On a phone the sidebar is
 * a drawer, closed until asked for, and the panel is not shown.
 *
 * A Show or Hide removes the control that was pressed, so focus moves to the
 * control that undoes it (spec §13 A135), never to the page. The move runs in a
 * layout effect of the shell, after the closing drawer has given the page back
 * (its inert cleanup runs while the commit mutates the DOM).
 */
export function useTutorLayout(rootRef: RefObject<HTMLElement | null>, isMobile: boolean, panelShows: boolean) {
  const [width, setWidth] = useState<number | null>(null);
  const [sideChoice, setSideChoice] = useState<boolean | null>(null);
  const [panelChoice, setPanelChoice] = useState<boolean | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // A phone's drawer starts closed whenever the screen becomes a phone.
  const [drawerMobile, setDrawerMobile] = useState(isMobile);
  if (drawerMobile !== isMobile) {
    setDrawerMobile(isMobile);
    setDrawerOpen(false);
  }
  const focusNext = useRef<string | null>(null);

  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [rootRef]);

  useLayoutEffect(() => {
    const id = focusNext.current;
    if (!id) return;
    focusNext.current = null;
    document.querySelector<HTMLElement>(`[data-testid="${id}"]`)?.focus();
  });

  const cols = tutorColumns(width, sideChoice, panelChoice, panelShows);
  const move = (to: keyof typeof FOCUS_AFTER) => { focusNext.current = FOCUS_AFTER[to]; };
  return {
    /** The sidebar is on screen: beside the conversation, or (a phone) as the drawer. */
    sideOpen: isMobile ? drawerOpen : cols.side,
    panelOpen: cols.panel,
    showSide: () => {
      // a phone's drawer focuses its own first control as it opens
      if (isMobile) setDrawerOpen(true);
      else { move("showSide"); setSideChoice(true); }
    },
    /** Hide, Escape or the drawer's scrim: focus goes back to "Show tutor sidebar". */
    hideSide: () => {
      move("hideSide");
      if (isMobile) setDrawerOpen(false);
      else setSideChoice(false);
    },
    /** A pick in the drawer: the page it opens takes focus itself. */
    closeDrawer: () => { if (isMobile) setDrawerOpen(false); },
    showPanel: () => { move("showPanel"); setPanelChoice(true); },
    hidePanel: () => { move("hidePanel"); setPanelChoice(false); },
  };
}
