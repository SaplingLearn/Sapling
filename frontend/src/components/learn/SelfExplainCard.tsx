"use client";
// Spec §13 A139 (`self_explanation_prompts` on): the student's answer to the
// turn's "why does this follow?" question — asked by code at a key juncture
// (after a worked example, after a shown solution, after a first unaided
// correct answer), at most once per concept a session. The reply is stored for
// diagnosis only: it is never graded, never evidence and never moves mastery;
// Skip is always there. The prompt is the turn's own last line (already in the
// conversation log, so it is announced there); this card repeats it and takes
// the reply.
//
// Rendered inside the check card under a worked-example hint (the Hint button
// keeps focus there), or in place of the Continue / Check me row after
// feedback — where LoopLearn moves lost focus to `inputRef` (spec §13 A135).
import React, { useEffect, useId, useState } from "react";
import { motion } from "framer-motion";

import type { LoopSelfExplain } from "@/lib/api";
import { LOOP_ANSWER_MAX } from "@/lib/inputLimits";
import { FIELD_CLASS } from "./loopShared";
import { useMotionPresets } from "@/lib/motion";
import styles from "./SelfExplainCard.module.css";

export const SELF_EXPLAIN_HEADING = "Explain it in your own words";
export const SELF_EXPLAIN_SUBLINE = "Not scored — a sentence or two is plenty.";

export function SelfExplainCard({
  prompt,
  busy,
  saving = busy,
  onSend,
  onSkip,
  onDraft,
  inputRef,
  nested = false,
}: {
  prompt: LoopSelfExplain;
  /** Nothing can be sent or skipped (this reply saving, or another turn running). */
  busy: boolean;
  /** This card's own reply is being saved: only then does Send say "Saving…". */
  saving?: boolean;
  /** Whether the card holds unsent text (false again when it goes), so
   *  LoopLearn can hold the chat: a served turn would close the card and drop
   *  the text (#866 Z60). Pass a stable callback (a state setter). */
  onDraft?: (hasText: boolean) => void;
  onSend: (reply: string) => void;
  onSkip: () => void;
  /** The reply box, for LoopLearn's focus move after feedback. */
  inputRef?: React.Ref<HTMLTextAreaElement>;
  /** Inside the check card: a sub-section (h3) rather than its own card (h2). */
  nested?: boolean;
}) {
  const [reply, setReply] = useState("");
  const hasText = reply.trim() !== "";
  useEffect(() => { onDraft?.(hasText); }, [hasText, onDraft]);
  useEffect(() => () => onDraft?.(false), [onDraft]);
  const ids = useId();
  const headingId = `${ids}-heading`;
  const promptId = `${ids}-prompt`;
  const canSend = !busy && hasText;
  const send = () => {
    if (canSend) onSend(reply.trim());
  };
  const Heading = nested ? "h3" : "h2";
  const m = useMotionPresets();
  // Keyed by the prompt: a new ask rises into place (`fadeUp`).
  return (
    <motion.section
      key={prompt.prompt_id}
      {...m.fadeUp}
      aria-labelledby={headingId}
      data-testid="loop-self-explain"
      data-juncture={prompt.juncture}
      data-prompt-id={prompt.prompt_id}
      className={nested ? `${styles.card} ${styles.nested}` : `card ${styles.card} ${styles.standalone}`}
    >
      <div className={styles.head}>
        <Heading id={headingId} className={`label-micro ${styles.heading}`}>{SELF_EXPLAIN_HEADING}</Heading>
        <p className={styles.subline}>{SELF_EXPLAIN_SUBLINE}</p>
        <p id={promptId} data-testid="loop-self-explain-prompt" className={styles.prompt}>
          {prompt.prompt}
        </p>
      </div>
      <textarea
        ref={inputRef}
        data-testid="loop-self-explain-input"
        maxLength={LOOP_ANSWER_MAX}
        aria-label="Your explanation"
        aria-describedby={promptId}
        className={FIELD_CLASS}
        rows={2}
        placeholder="Because…"
        value={reply}
        disabled={busy}
        onChange={(e) => setReply(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
        }}
      />
      <div className={styles.actions}>
        <button
          type="button"
          data-testid="loop-self-explain-send"
          className="btn btn--sm btn--primary"
          disabled={!canSend}
          onClick={send}
        >
          {saving ? "Saving…" : "Send"}
        </button>
        <button type="button" data-testid="loop-self-explain-skip" className="btn btn--sm btn--ghost" disabled={busy} onClick={onSkip}>
          Skip
        </button>
      </div>
    </motion.section>
  );
}
