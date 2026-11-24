"use client";
// The session's learner-state chip (moved out of LoopLearn.tsx unchanged): the
// focus concept and its band, kept in the layout (hidden) while there is none.
import React from "react";
import type { LoopLearnerState } from "@/lib/api";
import { BAND_LABEL } from "./loopShared";

export function LearnerChip({ learner, names }: { learner: LoopLearnerState | undefined; names: Map<string, string> }) {
  return (
    <span
      data-testid="loop-learner-state"
      data-node-id={learner?.node_id ?? ""}
      data-p-known={learner ? String(learner.p_known) : ""}
      data-band={learner?.band ?? ""}
      className="chip"
      style={{ visibility: learner ? "visible" : "hidden" }}
    >
      {learner
        ? `${names.get(learner.node_id) ?? "This concept"} · ${BAND_LABEL[learner.band] ?? learner.band}`
        : "—"}
    </span>
  );
}
