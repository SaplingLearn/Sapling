"use client";
// One question card for every answer the Tutor asks for (Tutor redesign phase
// 2; the audit's "Eight answer forms"). Its five uses — the check-in, a check
// (free text or multiple choice), the prequestion and the self-explanation —
// differ only in their words and in whether the answer counts:
//
// - graded: a plain card; the action is "Submit answer".
// - not graded: an accent-bordered card whose meta line says "Not graded"
//   and whose verb is its own ("Save guess", "Send"); nested inside another
//   card it is a dashed sub-section.
//
// The card names itself with ONE small line (`meta`, its heading for screen
// readers), then the question, then the answer: every field has a visible
// label (never a placeholder or an aria-label alone), and ⌘/Ctrl+Enter submits.
import React, { createContext, useContext, useId } from "react";
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import { LOOP_ANSWER_MAX } from "@/lib/inputLimits";
import { FIELD_CLASS } from "../loopShared";
import tutorStyles from "../tutor/tutor.module.css";
import styles from "./QuestionCard.module.css";

/** The meta line of a card whose answer never counts. */
export const NOT_GRADED = "Not graded";
/** The one-sentence "why" a multiple-choice answer needs (check-in and check alike). */
export const REASON_LABEL = "In one sentence: why?";

type QuestionIds = { headingId: string; promptId: string; fieldId: (name: string) => string };
const IdsContext = createContext<QuestionIds | null>(null);

/** The card's ids: its heading, its question (which fields are described by)
 *  and a stable id per field. */
export function useQuestionIds(): QuestionIds {
  const ids = useContext(IdsContext);
  if (!ids) throw new Error("useQuestionIds is for a QuestionCard's children");
  return ids;
}

type DataAttrs = { [key: `data-${string}`]: string | number | undefined };

export type QuestionCardProps = {
  graded: boolean;
  /** Inside another card: a sub-section with an h3, not a card with an h2. */
  nested?: boolean;
  /** The one line that names the card ("Question 2", the concept, "Not graded"). */
  meta: React.ReactNode;
  /** The question. */
  prompt: React.ReactNode;
  promptTestId?: string;
  /** Under the question, before the answer (e.g. the withheld-figure line). */
  afterPrompt?: React.ReactNode;
  /** The head (meta, question, afterPrompt) as one element with its own
   *  test id and data, for a surface whose tests find the question by it. */
  head?: { testId: string } & DataAttrs;
  testId?: string;
  data?: DataAttrs;
  /** False: appear without the rise-in (a card already on screen). */
  animateIn?: boolean;
  sectionRef?: React.Ref<HTMLElement>;
  className?: string;
  /** The answer; a function gets the card's ids (an option list is
   *  labelled by the question: `ids.promptId`). */
  children: React.ReactNode | ((ids: QuestionIds) => React.ReactNode);
};

export function QuestionCard({
  graded, nested = false, meta, prompt, promptTestId, afterPrompt, head, testId, data, animateIn = true, sectionRef, className, children,
}: QuestionCardProps) {
  const base = useId();
  const ids: QuestionIds = {
    headingId: `${base}-heading`,
    promptId: `${base}-prompt`,
    fieldId: (name) => `${base}-${name}`,
  };
  const m = useMotionPresets();
  const Heading = nested ? "h3" : "h2";
  const { testId: headTestId, ...headData } = head ?? { testId: undefined };
  const shape = nested
    ? styles.nested
    : `card ${tutorStyles.qcard}${graded ? "" : ` ${styles.ungraded}`}`;
  return (
    <IdsContext.Provider value={ids}>
      <motion.section
        {...m.fadeUp}
        initial={animateIn ? m.fadeUp.initial : false}
        ref={sectionRef}
        aria-labelledby={ids.headingId}
        data-testid={testId}
        data-graded={graded ? "true" : "false"}
        {...data}
        className={[shape, className].filter(Boolean).join(" ")}
      >
        <div className={styles.head} data-testid={headTestId} {...(head ? headData : {})}>
          <Heading id={ids.headingId} className={tutorStyles.qmeta}>{meta}</Heading>
          <p id={ids.promptId} data-testid={promptTestId} className={nested ? styles.nestedPrompt : tutorStyles.q}>{prompt}</p>
          {afterPrompt}
        </div>
        {typeof children === "function" ? children(ids) : children}
      </motion.section>
    </IdsContext.Provider>
  );
}

export type AnswerFieldProps = {
  /** The visible label, which is also the field's accessible name. */
  label: string;
  /** A stable name for the field's id within the card. */
  name: string;
  testId: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** A one-line input (a reason) rather than a textarea. */
  singleLine?: boolean;
  rows?: number;
  /** The field a new question focuses (`data-answer-start`). */
  start?: boolean;
  /** Described by the question (default), so a screen reader reads it on focus. */
  describedByPrompt?: boolean;
  placeholder?: string;
  /** ⌘/Ctrl+Enter. */
  onSubmit?: () => void;
  inputRef?: React.Ref<HTMLTextAreaElement>;
};

export function AnswerField({
  label, name, testId, value, onChange, disabled, singleLine = false, rows = 2, start = false, describedByPrompt = true, placeholder, onSubmit, inputRef,
}: AnswerFieldProps) {
  const { promptId, fieldId } = useQuestionIds();
  const id = fieldId(name);
  const common = {
    id,
    "data-testid": testId,
    maxLength: LOOP_ANSWER_MAX,
    ...(start ? { "data-answer-start": "" } : {}),
    "aria-describedby": describedByPrompt ? promptId : undefined,
    className: FIELD_CLASS,
    placeholder,
    value,
    disabled,
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onSubmit?.();
    },
  };
  return (
    <div className={styles.field}>
      <label className={tutorStyles.fl} htmlFor={id}>{label}</label>
      {singleLine
        ? <input {...common} onChange={(e) => onChange(e.target.value)} />
        : <textarea {...common} ref={inputRef} rows={rows} onChange={(e) => onChange(e.target.value)} />}
    </div>
  );
}

export type QuestionActionsProps = {
  /** The card's one primary action. */
  submit: { label: string; busyLabel?: string; busy?: boolean; disabled: boolean; onClick: () => void; testId: string; answerStart?: boolean };
  /** "I don't know", "No idea", "Skip": always there, never graded as wrong. */
  optOut?: { label: string; disabled?: boolean; onClick: () => void; testId: string };
  /** Between the two (the Hint button). */
  children?: React.ReactNode;
  size?: "md" | "sm";
};

export function QuestionActions({ submit, optOut, children, size = "md" }: QuestionActionsProps) {
  const sm = size === "sm" ? " btn--sm" : "";
  return (
    <div className={styles.actions}>
      <button
        type="button"
        data-testid={submit.testId}
        {...(submit.answerStart ? { "data-answer-start": "" } : {})}
        className={`btn btn--primary${sm} ${styles.press}`}
        disabled={submit.disabled}
        onClick={submit.onClick}
      >
        {submit.busy && submit.busyLabel ? submit.busyLabel : submit.label}
      </button>
      {children}
      {optOut && (
        <button
          type="button"
          data-testid={optOut.testId}
          className={`btn btn--ghost${sm} ${styles.press}`}
          disabled={optOut.disabled}
          onClick={optOut.onClick}
        >
          {optOut.label}
        </button>
      )}
    </div>
  );
}
