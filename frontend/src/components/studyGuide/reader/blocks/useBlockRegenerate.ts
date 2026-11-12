"use client";
import React from "react";

import { useToast } from "@/components/ToastProvider";
import { regenerateBlock } from "@/lib/studyGuide/api";

import { replaceBlock } from "../guideEdits";
import { useReader } from "../ReaderContext";

/** Rewrite one block in place. The rest of the guide is not touched. */
export function useBlockRegenerate(blockId: string) {
  const { userId, guide, update } = useReader();
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);

  const regenerate = async () => {
    setBusy(true);
    try {
      const { block } = await regenerateBlock(userId, guide.id, blockId);
      update(current => replaceBlock(current, blockId, block));
    } catch {
      toast.error("This block could not be regenerated. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return { busy, regenerate };
}
