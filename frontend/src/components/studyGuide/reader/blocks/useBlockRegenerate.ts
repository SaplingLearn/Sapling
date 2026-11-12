"use client";
import React from "react";

import { useToast } from "@/components/ToastProvider";
import { regenerateBlock } from "@/lib/studyGuide/api";

import { replaceBlock } from "../guideEdits";
import type { GuideUpdate } from "../useGuide";

/**
 * Rewrite one block in place. The rest of the guide is not touched.
 *
 * One at a time, for the whole reader: the request holds the guide on the
 * server, so a second rewrite or a generation started meanwhile would be
 * turned away.
 */
export function useBlockRegenerate(userId: string, guideId: string, update: GuideUpdate) {
  const toast = useToast();
  /** The block being rewritten, or null. */
  const [rewriting, setRewriting] = React.useState<string | null>(null);

  const regenerate = async (blockId: string) => {
    setRewriting(blockId);
    try {
      const { block } = await regenerateBlock(userId, guideId, blockId);
      update(current => replaceBlock(current, blockId, block));
    } catch {
      toast.error("This block could not be regenerated. Try again.");
    } finally {
      setRewriting(null);
    }
  };

  return { rewriting, regenerate };
}
