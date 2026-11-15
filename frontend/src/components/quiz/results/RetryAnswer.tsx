"use client";

import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui";
import { retryQuestion } from "@/lib/quiz/api";
import { isWrittenAnswerFormatValid } from "@/lib/quiz/answerFormats";
import { isWrittenType, type RetryResult, type WireQuestion } from "@/lib/quiz/types";
import { QuizMath } from "../QuizMath";

export function RetryAnswer({ attemptId, question, onScored }: {
  attemptId: string;
  question: WireQuestion;
  onScored: (points: number) => void;
}) {
  const answerId = useId();
  const [answer, setAnswer] = useState("");
  const [choice, setChoice] = useState<number | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const [result, setResult] = useState<RetryResult | null>(null);
  const inFlight = useRef(false);
  const written = isWrittenType(question.type);
  const valid = written ? isWrittenAnswerFormatValid(question.type, answer, question.numeric_unit) : choice !== null;
  const format = question.numeric_unit ? `Number and unit, e.g. 2.5 ${question.numeric_unit}`
    : question.type === "numeric" ? "Enter a number"
    : question.type === "symbolic" ? "Enter an expression, e.g. 2(x + 1)" : "Enter a brief answer";

  return (
    <details>
      <summary>Retry for up to ½ practice point</summary>
      {result ? (
        <p role="status">{result.correct ? "Correct on retry. You earned ½ practice point." : "No practice points earned. Review the worked solution below."}</p>
      ) : (
        <form onSubmit={async event => {
          event.preventDefault();
          const submission = written ? { answer_text: answer } : choice === null ? null : { selected_index: choice };
          if (!submission || !valid || inFlight.current) return;
          inFlight.current = true;
          setPending(true);
          setFailed(false);
          try {
            const scored = await retryQuestion(attemptId, question.id, submission);
            setResult(scored);
            onScored(scored.points);
          } catch {
            setFailed(true);
          } finally {
            inFlight.current = false;
            setPending(false);
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
            <fieldset disabled={pending}>
              <legend>Choose an answer</legend>
              {question.options.map((option, index) => (
                <label key={option.label} className="quiz-retry__choice">
                  <input type="radio" name={answerId} checked={choice === index} onChange={() => setChoice(index)} />
                  <QuizMath text={option.text} />
                </label>
              ))}
            </fieldset>
          )}
          <Button type="submit" size="sm" disabled={!valid || pending}>{pending ? "Checking…" : "Submit retry"}</Button>
          {failed && <p role="alert">Couldn’t check your retry. Try again.</p>}
        </form>
      )}
    </details>
  );
}
