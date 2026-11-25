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
import React, { useId, useLayoutEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

import type { LoopPrequestion, LoopPrequestionGuess } from "@/lib/api";
import { OptionList } from "./OptionList";
import { LOOP_ANSWER_MAX } from "@/lib/inputLimits";
import { FIELD_CLASS } from "./loopShared";
import { useMotionPresets } from "@/lib/motion";
import styles from "./PrequestionCard.module.css";

export const PREQUESTION_HEADING = "Take a guess first — this one isn't scored";
export const PREQUESTION_SUBLINE = "Guess before we start: the explanation comes right after.";

const modalOpen = () => typeof document !== "undefined" && document.querySelector('[aria-modal="true"]') !== null;

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
  const ids = useId();
  const headingId = `${ids}-heading`;
  const promptId = `${ids}-prompt`;
  const cardRef = useRef<HTMLElement>(null);
  const canSubmit = !busy && (mc ? option !== "" : answer.trim() !== "");
  const m = useMotionPresets();

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

  // Keyed by the question: a new one rises into place (`fadeUp`), so the swap
  // reads as a new question rather than the same card's text changing.
  return (
    <motion.section
      key={questionHash}
      {...m.fadeUp}
      ref={cardRef}
      aria-labelledby={headingId}
      data-testid="loop-prequestion"
      data-question-hash={prequestion.question_hash}
      data-format={prequestion.format}
      data-difficulty={prequestion.difficulty}
      data-answered={answered ? "true" : "false"}
      className={`card ${styles.card}`}
    >
      <div className={styles.head}>
        <h2 id={headingId} className={`label-micro ${styles.heading}`}>{PREQUESTION_HEADING}</h2>
        <p className={styles.subline}>{PREQUESTION_SUBLINE}</p>
        <p id={promptId} data-testid="loop-prequestion-prompt" className={styles.prompt}>
          {prequestion.prompt}
        </p>
      </div>
      {answered ? (
        <div className={styles.saved}>
          <span className={styles.savedNote}>Your guess is saved.</span>
          <button
            type="button"
            data-testid="loop-prequestion-explain"
            data-answer-start=""
            className="btn btn--sm btn--primary"
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
              <input
                data-testid="loop-prequestion-reason"
                maxLength={LOOP_ANSWER_MAX}
                aria-label="Why you think so (optional)"
                className={FIELD_CLASS}
                placeholder="Why? (optional)"
                value={reason}
                disabled={busy}
                onChange={(e) => setReason(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
                }}
              />
            </>
          ) : (
            <textarea
              data-testid="loop-prequestion-input"
              maxLength={LOOP_ANSWER_MAX}
              data-answer-start=""
              aria-label="Your guess"
              aria-describedby={promptId}
              className={FIELD_CLASS}
              rows={2}
              placeholder="Your guess"
              value={answer}
              disabled={busy}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
              }}
            />
          )}
          <div className={styles.actions}>
            <button
              type="button"
              data-testid="loop-prequestion-submit"
              className="btn btn--sm btn--primary"
              disabled={!canSubmit}
              onClick={submit}
            >
              {busy ? "Sending…" : "Submit guess"}
            </button>
            <button
              type="button"
              data-testid="loop-prequestion-no-idea"
              className="btn btn--sm btn--ghost"
              disabled={busy}
              onClick={() => onGuess({ no_idea: true })}
            >
              No idea
            </button>
          </div>
        </>
      )}
    </motion.section>
  );
}
