"use client";
// Spec §13 A138 (`segment_prequestion` on): the ungraded guess that opens a
// teaching segment. A vetted check item of the concept the plan just moved to,
// asked before any teaching on it (Pan & Carpenter: a prequestion helps when the
// answer follows promptly). "No idea" is always there and costs nothing: the
// guess is never graded, writes no evidence and moves no mastery. The server
// streams the explanation right after it — the answer first, from code — so the
// card only collects the guess. On a resume after the guess was saved but its
// explanation was not served (`answered`), it offers to show the explanation.
//
// Accessibility (spec §13 A135): a region named by its heading; a new question
// takes focus (its answer box, described by the question, or the options' tab
// stop, named by it) in a layout effect, unless a modal dialog owns focus; the
// options are a radio group (`OptionList` → `useRadioGroup`).
import React, { useLayoutEffect, useRef, useState } from "react";

import type { LoopPrequestion, LoopPrequestionGuess } from "@/lib/api";
import { OptionList } from "./OptionList";
import { modalOpen } from "./modalOpen";
import { AnswerField, NOT_GRADED, QuestionActions, QuestionCard } from "./question/QuestionCard";
import styles from "./PrequestionCard.module.css";

/** The card's one meta line (its heading): a guess is never graded. */
export const PREQUESTION_HEADING = NOT_GRADED;

/** The user row the log shows for a guess — the server saves the same words. */
export function renderGuess(guess: LoopPrequestionGuess): string {
  if (guess.no_idea) return "No idea.";
  if (guess.option !== undefined) {
    const reason = (guess.reason ?? "").trim();
    return `My guess: ${guess.option}${reason ? ` — ${reason}` : ""}`;
  }
  return `My guess: ${(guess.answer ?? "").trim()}`;
}

export function PrequestionCard({
  prequestion,
  busy,
  onGuess,
  onExplain,
}: {
  prequestion: LoopPrequestion;
  busy: boolean;
  /** A guess (a choice or text), or "No idea" (`no_idea: true`). */
  onGuess: (guess: LoopPrequestionGuess) => void;
  /** The `answered` state (a resume): serve the owed explanation. */
  onExplain: () => void;
}) {
  const mc = prequestion.format === "mc_reason" && (prequestion.options?.length ?? 0) > 0;
  const [answer, setAnswer] = useState("");
  const [option, setOption] = useState("");
  const [reason, setReason] = useState("");
  const cardRef = useRef<HTMLElement>(null);
  const canSubmit = !busy && (mc ? option !== "" : answer.trim() !== "");

  // A new question takes focus — its first answer control — so a screen reader
  // reads the question and the student can answer at once (spec §13 A135).
  const questionHash = prequestion.question_hash;
  const answered = !!prequestion.answered;
  useLayoutEffect(() => {
    if (modalOpen()) return;
    cardRef.current?.querySelector<HTMLElement>("[data-answer-start]")?.focus();
  }, [questionHash, answered]);

  const submit = () => {
    if (!canSubmit) return;
    onGuess(
      mc
        ? { option, ...(reason.trim() ? { reason: reason.trim() } : {}), no_idea: false }
        : { answer: answer.trim(), no_idea: false },
    );
  };

  // Keyed by the question: a new one rises into place, so the swap reads as a
  // new question rather than the same card's text changing.
  return (
    <QuestionCard
      key={questionHash}
      graded={false}
      meta={PREQUESTION_HEADING}
      prompt={prequestion.prompt}
      promptTestId="loop-prequestion-prompt"
      testId="loop-prequestion"
      sectionRef={cardRef}
      data={{
        "data-question-hash": prequestion.question_hash,
        "data-format": prequestion.format,
        "data-difficulty": prequestion.difficulty,
        "data-answered": answered ? "true" : "false",
      }}
    >
      {({ promptId }) => answered ? (
        <div className={styles.saved}>
          <span className={styles.savedNote}>Your guess is saved.</span>
          <button
            type="button"
            data-testid="loop-prequestion-explain"
            data-answer-start=""
            className="btn btn--primary"
            disabled={busy}
            onClick={onExplain}
          >
            Show the explanation
          </button>
        </div>
      ) : (
        <>
          {mc ? (
            <>
              <OptionList
                options={prequestion.options ?? []}
                selected={option}
                onSelect={setOption}
                testIdPrefix="loop-prequestion-option"
                labelledBy={promptId}
                disabled={busy}
              />
              <AnswerField label="Why you think so" name="reason" testId="loop-prequestion-reason" singleLine
                value={reason} disabled={busy} onChange={setReason} onSubmit={submit} describedByPrompt={false} />
            </>
          ) : (
            <AnswerField label="Your guess" name="answer" testId="loop-prequestion-input" start
              value={answer} disabled={busy} onChange={setAnswer} onSubmit={submit} />
          )}
          <QuestionActions
            submit={{ label: "Save guess", busyLabel: "Saving…", busy, disabled: !canSubmit, onClick: submit, testId: "loop-prequestion-submit" }}
            optOut={{ label: "No idea", disabled: busy, onClick: () => onGuess({ no_idea: true }), testId: "loop-prequestion-no-idea" }}
          />
        </>
      )}
    </QuestionCard>
  );
}
