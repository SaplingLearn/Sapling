"use client";
/**
 * The Study hub's interaction state that more than one panel reads or resets:
 * what is selected, what is filtered, and which of the page's pop-ups is open.
 * (A pop-up only its own panel cares about keeps its state there.)
 */
import React from "react";
import type { Status } from "./studyModel";

export interface HubState {
  /** The selected exam tab; null follows the default (the next exam ahead). */
  exam: string | null;
  /** The clicked concept: the Up Next block follows it. */
  topic: string | null;
  /** The concept under the pointer: its prerequisites light up on the roadmap. */
  hover: string | null;
  /** The legend's status filter. */
  lvl: Status | null;
  /** The deadlines pop-up. */
  menu: "bell" | null;
  /** The concept whose "..." menu is open. */
  tileMenu: string | null;
  /** Roadmap columns opened past their fold, by course id + label. */
  openCols: Record<string, boolean>;
  /** The "all recent activity" modal. */
  recentOpen: boolean;
}

export type SetHub = (patch: Partial<HubState>) => void;

const INITIAL: HubState = {
  exam: null, topic: null, hover: null, lvl: null,
  menu: null, tileMenu: null, openCols: {}, recentOpen: false,
};

/** Selecting an exam (a tab, or one just added) starts its readiness band clean. */
export const examPicked = (id: string): Partial<HubState> => ({ exam: id, topic: null, hover: null, lvl: null });

/** A course change keeps only which roadmap columns were opened. */
export const COURSE_PICKED: Partial<HubState> = {
  exam: null, topic: null, hover: null, lvl: null, menu: null, tileMenu: null, recentOpen: false,
};

export function useHubState(): { st: HubState; set: SetHub; closeTileMenu: (id: string) => void } {
  const [st, setSt] = React.useState<HubState>(INITIAL);
  const set = React.useCallback<SetHub>(patch => setSt(prev => ({ ...prev, ...patch })), []);
  /** Closes the tile menu only if it is still `id`'s: a press on another tile
   *  has already handed it over by the time this runs. */
  const closeTileMenu = React.useCallback(
    (id: string) => setSt(prev => (prev.tileMenu === id ? { ...prev, tileMenu: null } : prev)),
    [],
  );
  return { st, set, closeTileMenu };
}
