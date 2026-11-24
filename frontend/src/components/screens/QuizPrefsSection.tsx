"use client";
/**
 * Preferences → Quiz: Length / Difficulty / Answers / Format, stored in the
 * same client prefs as Adjust (`lib/quiz/prefs.ts`). No `user_settings`
 * columns. Hidden when `hide_quiz` is on (W7.D2 / W7.9).
 */
import React from "react";

import { CustomSelect } from "@/components/CustomSelect";
import { useFlag } from "@/context/FlagsContext";
import { defaultConfigFor, type SessionConfig } from "@/lib/quiz/machine";
import { FEEDBACK_LABELS, FEEDBACK_MODES, loadPrefs, savePrefs } from "@/lib/quiz/prefs";
import type { QuizPrefs } from "@/lib/quiz/types";
import { useQuizConfig } from "@/lib/quiz/useQuizConfig";

const FORMAT_LABELS: Record<string, string> = {
  multiple_choice: "Multiple choice",
  short_answer: "Short answer",
  numeric: "Numeric",
  symbolic: "Algebra",
  mixed: "Mixed",
};

function storedFrom(cfg: SessionConfig): QuizPrefs {
  return {
    count: cfg.count,
    difficulty: cfg.difficulty,
    feedback: cfg.feedback,
    sessionMode: cfg.sessionMode ?? "practice",
    ...(cfg.questionFormat ? { questionFormat: cfg.questionFormat } : {}),
  };
}

const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "16px 0",
  borderBottom: "1px solid var(--border)",
  gap: 20,
};

export function QuizPrefsSection() {
  const quizShown = useFlag("hide_quiz") !== "on";
  const { config } = useQuizConfig();
  const [prefs, setPrefs] = React.useState<QuizPrefs>(() => loadPrefs());
  // Re-validate remembered values once `/config` lands (invalid counts drop).
  // Key on the option lists — object identity alone would re-render forever if
  // a caller rebuilt `config` each paint.
  const configKey = config
    ? `${config.num_questions.options.join(",")}|${config.difficulties.join(",")}|${config.question_types.join(",")}`
    : "";
  const configRef = React.useRef(config);
  configRef.current = config;
  React.useEffect(() => {
    if (configKey) setPrefs(loadPrefs(configRef.current));
  }, [configKey]);

  if (!quizShown) return null;

  const value = defaultConfigFor(config, prefs);
  const remember = (next: SessionConfig) => {
    const stored = storedFrom(next);
    savePrefs(stored);
    setPrefs(stored);
  };

  return (
    <div data-testid="settings-quiz-prefs" style={{ marginTop: 28 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Quiz</div>
      <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 8 }}>
        Defaults for new quizzes on this device. Same choices as Adjust on Quiz home.
      </div>

      <div style={rowStyle}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500 }}>Length</div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
            How many questions a new quiz starts with.
          </div>
        </div>
        <div style={{ minWidth: 180 }}>
          <CustomSelect
            ariaLabel="Quiz length"
            size="sm"
            value={String(value.count)}
            onChange={v => remember({ ...value, count: Number(v) })}
            options={(config?.num_questions.options ?? [value.count]).map(n => ({
              value: String(n),
              label: `${n} questions`,
            }))}
            testId="settings-quiz-length"
          />
        </div>
      </div>

      <div style={rowStyle}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500 }}>Difficulty</div>
        </div>
        <div style={{ minWidth: 180 }}>
          <CustomSelect
            ariaLabel="Quiz difficulty"
            size="sm"
            value={value.difficulty}
            onChange={difficulty => remember({ ...value, difficulty })}
            options={(config?.difficulties ?? [value.difficulty]).map(d => ({
              value: d,
              label: d[0].toUpperCase() + d.slice(1),
            }))}
            testId="settings-quiz-difficulty"
          />
        </div>
      </div>

      <div style={rowStyle}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 500 }}>Answers</div>
          <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
            When you see whether each answer was right.
          </div>
        </div>
        <div style={{ minWidth: 180 }}>
          <CustomSelect
            ariaLabel="Quiz answers"
            size="sm"
            value={value.feedback}
            onChange={feedback => remember({ ...value, feedback: feedback as SessionConfig["feedback"] })}
            options={FEEDBACK_MODES.map(m => ({ value: m, label: FEEDBACK_LABELS[m] }))}
            testId="settings-quiz-answers"
          />
        </div>
      </div>

      {config && config.question_types.length > 1 && (
        <div style={rowStyle}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500 }}>Format</div>
            <div style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 2 }}>
              Answer format mix — Mixed is question types, not a content style.
            </div>
          </div>
          <div style={{ minWidth: 180 }}>
            <CustomSelect
              ariaLabel="Quiz format"
              size="sm"
              value={value.questionFormat ?? "multiple_choice"}
              onChange={questionFormat => remember({ ...value, questionFormat })}
              options={config.question_types.map(format => ({
                value: format,
                label: FORMAT_LABELS[format] ?? format,
              }))}
              testId="settings-quiz-format"
            />
          </div>
        </div>
      )}
    </div>
  );
}
