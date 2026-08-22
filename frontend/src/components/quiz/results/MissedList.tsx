"use client";

/**
 * The "to look at" list on the results screen (§5 B3).
 *
 * One row per wrong answer: the stem, what was chosen against what was right, a
 * disclosure for the explanation and "Ask about this". It is a separate file
 * from `QuizResults` because the JOIN it does is the interesting part —
 * `SubmitResult.results[]` carries labels and ids but no stems, and the stems
 * only exist on the session's `items`. `buildMissedItems` is that join, exported
 * so a test can pin it without rendering.
 *
 * The explanation disclosure is the one place on this screen that changes
 * height. Everywhere else reserves its space; here the expansion IS the
 * interaction, and reserving three lines of prose per row for something most
 * students won't open would cost more than the shift does.
 */

import React from "react";
import { Button } from "@/components/ui";
import type { QuizSession } from "@/lib/quiz/types";

export interface MissedItem {
  /** `SubmitResult.results[].question_id` — a string on the wire, and the
   *  testid suffix (`quiz-missed-{id}`). */
  questionId: string;
  /** "" when the question is no longer in the session's items. */
  stem: string;
  /** "" when the item was submitted unanswered. */
  chosenLabel: string;
  chosenText: string;
  correctLabel: string;
  correctText: string;
  explanation: string;
}

/**
 * The wrong answers, in the order the server scored them, joined to their
 * stems.
 *
 * `SubmitResult.results[].question_id` is `str(q["id"])` server-side
 * (`quiz.py:1749`) while `WireQuestion.id` is a number, so the join coerces —
 * a `===` on the raw values would silently match nothing and render a list of
 * stemless rows. `selected` / `correct_answer` are option LABELS, not texts,
 * which is why the option texts are looked up here rather than read off the
 * result.
 */
export function buildMissedItems(session: QuizSession): MissedItem[] {
  const result = session.result;
  if (!result) return [];

  return result.results
    .filter(r => !r.correct)
    .map(r => {
      const question = session.items.find(
        item => String(item.question.id) === String(r.question_id),
      )?.question;
      const textFor = (label: string) =>
        question?.options.find(o => o.label === label)?.text ?? "";

      return {
        questionId: String(r.question_id),
        stem: question?.question ?? "",
        chosenLabel: r.selected,
        chosenText: textFor(r.selected),
        correctLabel: r.correct_answer,
        correctText: textFor(r.correct_answer),
        explanation: r.explanation,
      };
    });
}

/** "One to look at" / "3 to look at" — the design's own eyebrow. */
export function missedLabel(count: number): string {
  return count === 1 ? "One to look at" : `${count} to look at`;
}

export interface MissedListProps {
  items: MissedItem[];
  /** Opens the AskPanel seeded from this row. The trigger is handed back so the
   *  screen can hold it as the panel's `returnFocusTo`. */
  onAsk: (item: MissedItem, trigger: HTMLElement) => void;
  testid?: string;
}

export function MissedList({ items, onAsk, testid = "quiz-missed-list" }: MissedListProps) {
  const [expanded, setExpanded] = React.useState<Record<string, boolean>>({});

  if (items.length === 0) return null;

  return (
    <section className="quiz-missed" data-testid={testid}>
      <div className="label-micro">{missedLabel(items.length)}</div>
      {items.map(item => {
        const open = expanded[item.questionId] === true;
        const panelId = `quiz-missed-explanation-${item.questionId}`;
        return (
          <div
            key={item.questionId}
            className="quiz-missed__item"
            data-testid={`quiz-missed-${item.questionId}`}
          >
            {item.stem && <p className="h-serif quiz-missed__stem">{item.stem}</p>}
            <p className="quiz-missed__line">
              {item.chosenLabel
                ? `You chose ${item.chosenLabel} · the answer is ${item.correctLabel}`
                : `No answer · the answer is ${item.correctLabel}`}
            </p>
            <div className="quiz-missed__actions">
              {item.explanation && (
                <Button
                  variant="link"
                  aria-expanded={open}
                  aria-controls={panelId}
                  data-testid={`quiz-missed-explain-${item.questionId}`}
                  onClick={() =>
                    setExpanded(prev => ({ ...prev, [item.questionId]: !open }))
                  }
                >
                  {open ? "Hide explanation" : "Show explanation"}
                </Button>
              )}
              <Button
                size="sm"
                data-testid={`quiz-missed-ask-${item.questionId}`}
                onClick={event => onAsk(item, event.currentTarget)}
              >
                Ask about this
              </Button>
            </div>
            {item.explanation && open && (
              <p id={panelId} className="body-serif quiz-missed__explanation">
                {item.explanation}
              </p>
            )}
          </div>
        );
      })}
    </section>
  );
}
