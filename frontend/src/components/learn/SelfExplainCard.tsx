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
import React, { useEffect, useState } from "react";
import type { LoopSelfExplain } from "@/lib/api";
import { AnswerField, NOT_GRADED, QuestionActions, QuestionCard } from "./question/QuestionCard";

/** The card's one meta line (its heading): the reply is never graded. */
export const SELF_EXPLAIN_HEADING = NOT_GRADED;

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
  const canSend = !busy && hasText;
  const send = () => {
    if (canSend) onSend(reply.trim());
  };
  // Keyed by the prompt: a new ask rises into place.
  return (
    <QuestionCard
      key={prompt.prompt_id}
      graded={false}
      nested={nested}
      meta={SELF_EXPLAIN_HEADING}
      prompt={prompt.prompt}
      promptTestId="loop-self-explain-prompt"
      testId="loop-self-explain"
      data={{ "data-juncture": prompt.juncture, "data-prompt-id": prompt.prompt_id }}
    >
      <AnswerField
        label="Your explanation"
        name="reply"
        testId="loop-self-explain-input"
        inputRef={inputRef}
        placeholder="Because…"
        value={reply}
        disabled={busy}
        onChange={setReply}
        onSubmit={send}
      />
      <QuestionActions
        size="sm"
        submit={{ label: "Send", busyLabel: "Saving…", busy: saving, disabled: !canSend, onClick: send, testId: "loop-self-explain-send" }}
        optOut={{ label: "Skip", disabled: busy, onClick: onSkip, testId: "loop-self-explain-skip" }}
      />
    </QuestionCard>
  );
}
