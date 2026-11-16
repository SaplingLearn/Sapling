"use client";

import { useId, useRef, useState } from "react";
import { AnswerOption, Button } from "@/components/ui";
import { retryQuestion } from "@/lib/quiz/api";
import { isWrittenAnswerFormatValid } from "@/lib/quiz/answerFormats";
import { isWrittenType, type RetryResult, type WireQuestion } from "@/lib/quiz/types";
import { QuizMath } from "../QuizMath";

export function RetryAnswer({ attemptId, question, hint, previousAnswer, previousChoice, onPending }: {
  attemptId: string;
  question: WireQuestion;
  hint: string;
  previousAnswer?: string;
  previousChoice: number | null;
  onPending: (pending: boolean) => void;
}) {
  const answerId = useId();
  const [answer, setAnswer] = useState("");
  const [choice, setChoice] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [result, setResult] = useState<RetryResult | null>(null);
  const inFlight = useRef(false);
  const written = isWrittenType(question.type);
  const previousOption = previousChoice === null ? undefined : question.options[previousChoice];
  const valid = written ? isWrittenAnswerFormatValid(question.type, answer, question.numeric_unit) : choice !== null;
  const format = question.numeric_unit ? `Number and unit, e.g. 2.5 ${question.numeric_unit}`
    : question.type === "numeric" ? "Enter a number"
    : question.type === "symbolic" ? "Enter an expression, e.g. 2(x + 1)" : "Your answer";

  return (
    <section className="quiz-retry" aria-label="Retry for partial credit">
      {!result && (
        <p className="quiz-retry__status" role="status">
          <strong>Try again</strong>
          <span>Up to ½ point</span>
        </p>
      )}
      {result ? (
        <p role="status">{result.correct ? "Correct on retry. You earned ½ practice point." : "No points earned on retry. Review the solution at the end."}</p>
      ) : (
        <form onKeyDown={event => { if (event.key === "Enter") event.stopPropagation(); }} onSubmit={async event => {
          event.preventDefault();
          const submission = written ? { answer_text: answer } : choice === null ? null : { selected_index: choice };
          if (!submission || !valid || inFlight.current) return;
          inFlight.current = true;
          setPending(true);
          onPending(true);
          setFailed(false);
          try {
            setResult(await retryQuestion(attemptId, question.id, submission));
          } catch {
            setFailed(true);
          } finally {
            inFlight.current = false;
            setPending(false);
            onPending(false);
          }
        }}>
          {written ? (
            <>
              <label htmlFor={answerId}>{format}</label>
              <input
                id={answerId}
                className="quiz-question__written-input"
                value={answer}
                onChange={event => setAnswer(event.target.value)}
                maxLength={2000}
                disabled={pending}
              />
            </>
          ) : (
            <div
              className="quiz-question__options"
              role="radiogroup"
              aria-label="Answer choices"
              data-testid="quiz-answer-options"
              onKeyDown={event => {
                if (pending || question.options.length === 0) return;
                const forward = event.key === "ArrowRight" || event.key === "ArrowDown";
                const backward = event.key === "ArrowLeft" || event.key === "ArrowUp";
                if (!forward && !backward) return;
                event.preventDefault();
                const count = question.options.length;
                const step = forward ? 1 : -1;
                const next = ((choice ?? (forward ? -1 : 0)) + step + count) % count;
                setChoice(next);
                event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[next]?.focus();
              }}
            >
              {question.options.map((option, index) => (
                <AnswerOption
                  key={option.label}
                  letter={option.label}
                  text={option.text}
                  formattedText={<QuizMath text={option.text} />}
                  state={choice === index ? "selected" : "default"}
                  disabled={pending}
                  onSelect={() => setChoice(index)}
                  tabIndex={index === (choice ?? 0) ? 0 : -1}
                  testid={`quiz-answer-option-${option.label}`}
                />
              ))}
            </div>
          )}
          {(written ? previousAnswer : previousOption) && (
            <p className="quiz-retry__previous">
              <span>Previous answer</span>
              {written ? previousAnswer : previousOption && <QuizMath text={`${previousOption.label}. ${previousOption.text}`} />}
            </p>
          )}
          <p className="quiz-retry__hint"><strong>Hint</strong> <QuizMath text={hint} /></p>
          <Button type="submit" size="sm" disabled={!valid || pending}>{pending ? "Checking…" : "Submit retry"}</Button>
          {failed && <p role="alert">Couldn’t check your retry. Try again.</p>}
        </form>
      )}
    </section>
  );
}
