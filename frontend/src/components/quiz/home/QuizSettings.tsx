"use client";

/**
 * The three pick-one rows both quiz-home dialogs carry: Length, Difficulty,
 * Answers (§5 B1.5 / B1.6).
 *
 * One component rather than two copies because the Concept dialog and the
 * Adjust dialog render the identical control set — the design draws them
 * identically too, down to the 96px label gutter.
 *
 * NOTHING here enumerates counts or difficulties: the two option lists come
 * off `GET /api/quiz/config` (§2) and the only hardcoded list in the quiz is
 * `FEEDBACK_MODES`, which is a client concept with no server list to read
 * (R-2). While `/config` is still in flight the rows keep their labels and
 * show a skeleton where the options will land, so the dialog doesn't reflow
 * when it arrives.
 */

import React from "react";
import { SegmentedControl } from "@/components/ui";
import { Skeleton } from "@/components/Skeleton";
import { FEEDBACK_LABELS, FEEDBACK_MODES } from "@/lib/quiz/prefs";
import type { SessionConfig } from "@/lib/quiz/machine";
import type { QuizConfig } from "@/lib/quiz/types";

export interface QuizSettingsProps {
  /** `null` until `/api/quiz/config` resolves. */
  config: QuizConfig | null;
  value: SessionConfig;
  onChange: (next: SessionConfig) => void;
  /** Drops the top margin when the rows already follow a rule. */
  flush?: boolean;
}

/** Width of the placeholder that stands in for a row of options. */
const SKELETON_WIDTH = 220;
const SKELETON_HEIGHT = 14;

function Row({
  label,
  children,
}: {
  label: string;
  children: (labelId: string) => React.ReactNode;
}) {
  const labelId = React.useId();
  return (
    <div className="quiz-home-settings__row">
      <span className="label-micro quiz-home-settings__label" id={labelId}>
        {label}
      </span>
      {children(labelId)}
    </div>
  );
}

export function QuizSettings({ config, value, onChange, flush = false }: QuizSettingsProps) {
  const pending = <Skeleton width={SKELETON_WIDTH} height={SKELETON_HEIGHT} />;

  return (
    <div className={`quiz-home-settings${flush ? " quiz-home-settings--flush" : ""}`}>
      <Row label="Length">
        {labelId =>
          config ? (
            <SegmentedControl
              options={config.num_questions.options.map(n => ({
                value: n,
                label: `${n} questions`,
              }))}
              value={value.count}
              onChange={count => onChange({ ...value, count })}
              labelledBy={labelId}
              testid="quiz-seg-count"
            />
          ) : (
            pending
          )
        }
      </Row>

      <Row label="Difficulty">
        {labelId =>
          config ? (
            <SegmentedControl
              options={config.difficulties.map(d => ({ value: d, label: d }))}
              value={value.difficulty}
              onChange={difficulty => onChange({ ...value, difficulty })}
              labelledBy={labelId}
              testid="quiz-seg-difficulty"
            />
          ) : (
            pending
          )
        }
      </Row>

      <Row label="Answers">
        {labelId => (
          <SegmentedControl
            options={FEEDBACK_MODES.map(m => ({ value: m, label: FEEDBACK_LABELS[m] }))}
            value={value.feedback}
            onChange={feedback => onChange({ ...value, feedback })}
            labelledBy={labelId}
            testid="quiz-seg-feedback"
          />
        )}
      </Row>
    </div>
  );
}
