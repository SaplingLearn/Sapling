"use client";
/**
 * What every part of the reader needs from the screen: the guide, who is
 * reading it, and the things a block can ask for (an edit to the guide, its
 * own rewrite, a question to the tutor).
 */
import React from "react";

import type { GuideDetail } from "@/lib/studyGuide/types";

import type { ViewMode } from "./readerModel";
import type { GuideUpdate } from "./useGuide";
import type { AskTutor } from "./useTutorHandoff";

export interface Reader {
  userId: string;
  guide: GuideDetail;
  mode: ViewMode;
  /** The guide is being written: sections fill in and blocks stay as they are. */
  generating: boolean;
  /** The block being regenerated, or null. */
  rewriting: string | null;
  update: GuideUpdate;
  regenerateBlock: (blockId: string) => void;
  askTutor: AskTutor;
  /** A question is on its way to the tutor. */
  tutorBusy: boolean;
}

const ReaderContext = React.createContext<Reader | null>(null);

export const ReaderProvider = ReaderContext.Provider;

export function useReader(): Reader {
  const reader = React.useContext(ReaderContext);
  if (!reader) throw new Error("useReader must be used inside the guide reader");
  return reader;
}

/**
 * The guide, or one of its blocks, is being written. The server lets one
 * such request hold a guide at a time, so nothing else that writes may start.
 */
export function useWriting(): boolean {
  const { generating, rewriting } = useReader();
  return generating || rewriting !== null;
}
