"use client";

/**
 * The Adjust dialog (§5 B1.6) — "adjust" on the proposal card.
 *
 * Same three settings rows as the Concept dialog, but about the quiz already
 * on offer rather than a different concept: no neighbourhood, no definition,
 * and two ways out. `Done` keeps the choices and closes (`SET_CONFIG`, which
 * also persists them to prefs); `Start` runs the quiz with them.
 *
 * The note under the rows says what the Answers choice actually changes, since
 * "as you go / at the end" is otherwise a setting whose effect you only
 * discover mid-quiz.
 */

import React from "react";
import Dialog from "@/components/Dialog";
import { Button } from "@/components/ui";
import type { SessionConfig } from "@/lib/quiz/machine";
import type { QuizConfig } from "@/lib/quiz/types";
import { QuizSettings } from "./QuizSettings";
import { accentStyle } from "./accent";

const NOTES = {
  "as-you-go":
    "After each answer you'll see whether it was right and which answer was correct, before moving on.",
  "at-end": "Answers stay hidden while you work — you'll review everything on the results screen.",
} as const;

export interface AdjustDialogProps {
  open: boolean;
  /** "{concept} · {CODE}" — the quiz these settings apply to. */
  subtitle: string;
  accent: string | null;
  config: QuizConfig | null;
  initialConfig: SessionConfig;
  /** Keep the choices, don't start. */
  onDone: (config: SessionConfig) => void;
  /** Close without keeping anything (Escape, backdrop, the × ). */
  onClose: () => void;
  onStart: (config: SessionConfig) => void;
}

export function AdjustDialog({
  open,
  subtitle,
  accent,
  config,
  initialConfig,
  onDone,
  onClose,
  onStart,
}: AdjustDialogProps) {
  const titleId = React.useId();
  const [draft, setDraft] = React.useState<SessionConfig>(initialConfig);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="md"
      labelledBy={titleId}
      // No × in the design: Done is the way out, and Escape and the backdrop
      // still close it.
      showCloseButton={false}
    >
      <div className="quiz-home-dialog" style={accentStyle(accent)} data-testid="quiz-adjust-dialog">
        <h2 className="quiz-home-dialog__title" id={titleId}>
          Adjust this quiz
        </h2>
        <p className="quiz-home-dialog__subtitle">{subtitle}</p>

        <QuizSettings config={config} value={draft} onChange={setDraft} flush />

        <p className="quiz-home-dialog__note">{NOTES[draft.feedback]}</p>

        <div className="quiz-home-dialog__footer">
          <Button data-testid="quiz-adjust-done" onClick={() => onDone(draft)}>
            Done
          </Button>
          <Button variant="primary" data-testid="quiz-adjust-start" onClick={() => onStart(draft)}>
            {`Start · ${draft.count} ${draft.difficulty}`}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
