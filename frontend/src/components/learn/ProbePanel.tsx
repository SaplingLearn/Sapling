"use client";
import React, { useLayoutEffect, useRef, useState } from "react";
import { type LoopProbeItem } from "@/lib/api";
import { ConfidenceControl } from "./ConfidenceControl";
import { OptionList } from "./OptionList";
import tutorStyles from "./tutor/tutor.module.css";
import { modalOpen } from "./modalOpen";
import { type Draft, focusAnswerStart } from "./loopShared";
import { AnswerField, CHECKING, DONT_KNOW, QuestionActions, QuestionCard, REASON_LABEL, SUBMIT_ANSWER } from "./question/QuestionCard";
import { TutorTurn } from "./TutorTurn";
import { HYPERCORRECTION_DWELL_COPY } from "@/lib/hypercorrectionDwell";
import styles from "./ProbePanel.module.css";

/** K02: an mc_reason answer needs its reason too (the grader judges it, never
 *  the option alone); any other format needs its typed answer. */
function draftAnswered(mc: boolean, draft: Draft): boolean {
  return mc ? draft.option !== "" && draft.reason.trim() !== "" : draft.answer.trim() !== "";
}

/** Next after the answer is shown, held (W2.5) while the feedback dwell runs. */
function ProbeNext({
  busy, nextHeld, onNext, className,
}: { busy: boolean; nextHeld: boolean; onNext: () => void; className?: string }) {
  return (
    <>
      <button data-testid="loop-probe-next" className={`btn btn--primary${className ? ` ${className}` : ""}`} disabled={busy || nextHeld} onClick={onNext}>
        Next
      </button>
      {nextHeld && (
        <span role="status" data-testid="loop-feedback-dwell" className={styles.note}>
          {HYPERCORRECTION_DWELL_COPY}
        </span>
      )}
    </>
  );
}

export function ProbePanel({
  item, count, draft, setDraft, reference, note, busy, nextHeld = false, loadFailed, greeting, onSubmit, onIdk, onNext, onRetry,
}: {
  item: LoopProbeItem | null;
  count: number;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  reference: string | null;
  note: string | null;
  busy: boolean;
  /** W2.5: high-confidence wrong — Next waits for the feedback dwell. */
  nextHeld?: boolean;
  /** The next item failed to load (not a pause): offer a retry, never an empty card. */
  loadFailed: boolean;
  /** The session opener: in the probe phase always a template — a welcome and
   *  the check-in's intro, no teaching and no question (spec §13 A121). */
  greeting: string | null;
  onSubmit: () => void;
  onIdk: () => void;
  onNext: () => void;
  onRetry: () => void;
}) {
  const mc = item?.format === "mc_reason";
  const canSubmit = !!item && !busy && draftAnswered(mc, draft);
  const cardRef = useRef<HTMLElement>(null);
  const referenceRef = useRef<HTMLDivElement>(null);
  // spec §13 A135: a new question takes focus — its answer box, described by
  // the question (or the options' tab stop, named by it) — so a screen reader
  // reads the question and the student can answer at once.
  const questionHash = item?.question_hash;
  useLayoutEffect(() => {
    if (!questionHash || modalOpen()) return;
    focusAnswerStart(cardRef.current);
  }, [questionHash]);
  // ...and the answer shown after a miss takes focus, so it is read out.
  useLayoutEffect(() => {
    if (reference === null || modalOpen()) return;
    referenceRef.current?.focus();
  }, [reference]);
  // A new question rises into place (`fadeUp`, keyed by its hash); the one on
  // screen when the panel first paints does not move.
  const [firstHash] = useState(questionHash);
  const swapped = questionHash !== firstHash;
  const referenceBlock = (
    <div
      ref={referenceRef}
      tabIndex={-1}
      data-testid="loop-probe-reference"
      className={item ? `${styles.reference} ${styles.referenceBoxed}` : styles.reference}
    >
      <div className={`label-micro ${styles.referenceLabel}`}>Here&apos;s the answer</div>
      {reference}
    </div>
  );
  return (
    <div className={styles.scroll}>
      <div className={tutorStyles.col}>
        <h2 className={tutorStyles.sr}>Quick check-in</h2>
        <TutorTurn testId="loop-probe-greeting">
          {greeting ?? "Let's start with a quick check-in so I know where you are. These answers count, and there are no hints."}
        </TutorTurn>
        {/* The coverage summary reads the check-in's results: it shows on the plan,
            once there is something to summarise, not over the first question. */}
        {!item && busy && <div className={styles.status}>Loading the next question…</div>}
        {!item && reference !== null && (
          <div className={`card ${styles.answerCard}`}>
            {referenceBlock}
            <ProbeNext busy={busy} nextHeld={nextHeld} onNext={onNext} />
          </div>
        )}
        {!item && !busy && loadFailed && (
          <div className={`${styles.status} ${styles.failed}`}>
            <span>The next question didn&apos;t load.</span>
            <button data-testid="loop-probe-retry" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}
        {item && (
          <QuestionCard
            key={item.question_hash}
            graded
            animateIn={swapped}
            sectionRef={cardRef}
            testId="loop-probe-item"
            data={{ "data-question-hash": item.question_hash, "data-difficulty": item.difficulty }}
            // The stepper says Check-in and the greeting says "no hints": the
            // card names only its question number.
            meta={`Question ${count + (reference === null ? 1 : 0)}`}
            prompt={item.prompt}
          >
            {({ promptId }) => reference === null ? (
              <>
                {mc ? (
                  <>
                    <OptionList
                      options={item.options ?? []}
                      selected={draft.option}
                      onSelect={(letter) => setDraft((d) => ({ ...d, option: letter }))}
                      testIdPrefix="loop-probe-option"
                      labelledBy={promptId}
                      disabled={busy}
                    />
                    <AnswerField label={REASON_LABEL} name="reason" testId="loop-probe-reason" singleLine describedByPrompt={false}
                      placeholder="Because…" value={draft.reason} disabled={busy}
                      onChange={(reason) => setDraft((d) => ({ ...d, reason }))} />
                  </>
                ) : (
                  <AnswerField label="Your answer" name="answer" testId="loop-probe-input" start rows={3}
                    placeholder={item.format === "teachback" ? "Explain it in your own words" : undefined}
                    value={draft.answer} disabled={busy}
                    onChange={(answer) => setDraft((d) => ({ ...d, answer }))}
                    onSubmit={() => { if (canSubmit) onSubmit(); }} />
                )}
                <ConfidenceControl
                  testIdPrefix="loop-probe-confidence"
                  value={draft.confidence}
                  onChange={(confidence) => setDraft((d) => ({ ...d, confidence }))}
                  disabled={busy}
                />
                <QuestionActions
                  submit={{ label: SUBMIT_ANSWER, busyLabel: CHECKING, busy, disabled: !canSubmit, onClick: onSubmit, testId: "loop-probe-submit" }}
                  optOut={{ label: DONT_KNOW, disabled: busy, onClick: onIdk, testId: "loop-probe-idk" }}
                />
              </>
            ) : (
              <>
                {referenceBlock}
                <ProbeNext busy={busy} nextHeld={nextHeld} onNext={onNext} className={styles.next} />
              </>
            )}
          </QuestionCard>
        )}
        {note && <div role="status" className={styles.note}>{note}</div>}
      </div>
    </div>
  );
}
