"use client";
import type { Feedback } from "@/lib/studyGuide/types";

import s from "./reader.module.css";

const ANSWERS: { value: Feedback; label: string }[] = [
  { value: "yes", label: "Yes" },
  { value: "no", label: "Not really" },
];

export function FeedbackRow({ feedback, onFeedback }: { feedback: Feedback | null; onFeedback: (value: Feedback) => void }) {
  return (
    <footer className={s.feedback}>
      <span className={s.feedbackLabel} role="status">
        {feedback ? "Thanks, that shapes your next guide." : "Was this guide useful?"}
      </span>
      {ANSWERS.map(answer => (
        <button
          key={answer.value}
          type="button"
          className={s.feedbackButton}
          data-testid={`guide-feedback-${answer.value}`}
          aria-pressed={feedback === answer.value}
          onClick={() => onFeedback(answer.value)}
        >
          {answer.label}
        </button>
      ))}
    </footer>
  );
}
