"use client";

/**
 * W7.2 Dialogue (design kit 7.17) under the focus SessionTop shell.
 *
 * Scripted partner open → student replies → fixed follow-up after the first
 * reply. Composer + Send; Check uses encoded short_answer text via
 * `lib/quiz/dialogueInteraction`. Generation does not emit `interaction`
 * yet — UI stub + fixture path only.
 */

import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { DialogueInteraction } from "@/lib/quiz/types";
import {
  appendDialogueReply,
  decodeDialogueAnswer,
  dialogueMaxReplies,
  dialogueMinReplies,
  encodeDialogueAnswer,
  isDialogueComplete,
} from "@/lib/quiz/dialogueInteraction";
import { toneOfVerdict, useKitMotion } from "./kitMotion";

/** The partner's follow-up lands one stagger step after the reply it answers. */
const PARTNER_REPLY_STEP = 1;

export interface DialogueAnswerProps {
  interaction: DialogueInteraction;
  value: string;
  disabled: boolean;
  /** Once the verdict may show: tone the thread root. */
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

export function DialogueAnswer({
  interaction,
  value,
  disabled,
  verdict,
  onChange,
}: DialogueAnswerProps) {
  const replies = useMemo(() => decodeDialogueAnswer(value), [value]);
  const [draft, setDraft] = useState("");
  const kit = useKitMotion();
  // Replies already sent when the kit appeared: those don't animate in.
  const [repliesAtMount] = useState(replies.length);
  const complete = isDialogueComplete(interaction, value);
  const done = Boolean(verdict);
  const max = dialogueMaxReplies(interaction);
  const min = dialogueMinReplies(interaction);
  const canSend = !disabled && !done && replies.length < max && Boolean(draft.trim());
  const placeholder =
    interaction.placeholder?.trim() || `Reply to ${interaction.role}`;

  const send = () => {
    if (!canSend) return;
    const next = appendDialogueReply(interaction, replies, draft);
    if (next === replies) return;
    setDraft("");
    onChange(encodeDialogueAnswer(next));
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div
      className="quiz-dialogue"
      data-testid="quiz-dialogue"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
      data-replies={String(replies.length)}
    >
      <p className="quiz-dialogue__role label-micro" data-testid="quiz-dialogue-role">
        {interaction.role}
      </p>

      <div
        className="quiz-dialogue__thread"
        data-testid="quiz-dialogue-thread"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
      >
        <div
          className="quiz-dialogue__bubble quiz-dialogue__bubble--partner"
          data-testid="quiz-dialogue-open"
          data-from="partner"
        >
          {interaction.open}
        </div>

        {replies.map((text, i) => (
          <React.Fragment key={`r-${i}`}>
            <motion.div
              {...(verdict ? kit.mark(toneOfVerdict(verdict)) : kit.arrive(i >= repliesAtMount))}
              className="quiz-dialogue__bubble quiz-dialogue__bubble--me"
              data-testid={`quiz-dialogue-reply-${i}`}
              data-from="me"
            >
              {text}
            </motion.div>
            {i === 0 ? (
              <motion.div
                {...kit.arrive(i >= repliesAtMount, PARTNER_REPLY_STEP)}
                className="quiz-dialogue__bubble quiz-dialogue__bubble--partner"
                data-testid="quiz-dialogue-follow"
                data-from="partner"
              >
                {interaction.follow}
              </motion.div>
            ) : null}
          </React.Fragment>
        ))}
      </div>

      {!done && replies.length < max ? (
        <div className="quiz-dialogue__composer" data-testid="quiz-dialogue-composer">
          <textarea
            className="quiz-dialogue__input field"
            data-testid="quiz-dialogue-input"
            value={draft}
            disabled={disabled}
            placeholder={placeholder}
            rows={2}
            aria-label={placeholder}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <div className="quiz-dialogue__composer-row">
            <p className="quiz-dialogue__count label-micro" data-testid="quiz-dialogue-count">
              {replies.length} of {max} messages sent
              {replies.length < min
                ? ` · ${min - replies.length} more before Check`
                : " · Check unlocked"}
            </p>
            <button
              type="button"
              className="quiz-dialogue__send"
              data-testid="quiz-dialogue-send"
              disabled={!canSend}
              onClick={send}
            >
              Send
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
