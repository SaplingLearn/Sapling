"use client";
// The answer field of the question screen (moved out of QuizQuestion.tsx):
// multiple choice, the written formats, and the W7.2 kits on a short_answer.
import React, { useRef } from "react";
import { AnswerOption } from "@/components/ui";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuestionType, QuizItem } from "@/lib/quiz/types";
import { asBuildInteraction } from "@/lib/quiz/buildInteraction";
import { asCompareInteraction } from "@/lib/quiz/compareInteraction";
import { asDialogueInteraction } from "@/lib/quiz/dialogueInteraction";
import { asExplainInteraction } from "@/lib/quiz/explainInteraction";
import { asHighlightInteraction } from "@/lib/quiz/highlightInteraction";
import { asCalculateInteraction } from "@/lib/quiz/calculateInteraction";
import { asPositionInteraction } from "@/lib/quiz/positionInteraction";
import { asRankInteraction } from "@/lib/quiz/rankInteraction";
import { asConnectInteraction } from "@/lib/quiz/connectInteraction";
import { asLabelInteraction } from "@/lib/quiz/labelInteraction";
import { asSequenceInteraction } from "@/lib/quiz/sequenceInteraction";
import { asSortInteraction } from "@/lib/quiz/sortInteraction";
import { WrittenAnswer, type WrittenType } from "./WrittenAnswer";
import { BuildAnswer } from "./BuildAnswer";
import { CompareAnswer } from "./CompareAnswer";
import { DialogueAnswer } from "./DialogueAnswer";
import { ExplainAnswer } from "./ExplainAnswer";
import { HighlightAnswer } from "./HighlightAnswer";
import { CalculateAnswer } from "./CalculateAnswer";
import { PositionAnswer } from "./PositionAnswer";
import { RankAnswer } from "./RankAnswer";
import { ConnectAnswer } from "./ConnectAnswer";
import { LabelAnswer } from "./LabelAnswer";
import { SequenceAnswer } from "./SequenceAnswer";
import { SortAnswer } from "./SortAnswer";
import {
  arrowStep,
  formatHint,
  kitKindOf,
  nextOptionIndex,
  optionState,
  optionStatus,
  outcomeOf,
  type ItemView,
  type KitKind,
  type Outcome,
  type Primary,
  type Verdict,
} from "./questionView";

/** What every answer format is handed. `shown` is the verdict once it may be
 *  shown (always null before then, and throughout an at-end quiz). */
export interface AnswerFieldProps {
  view: ItemView;
  shown: Verdict | null;
  selectable: boolean;
  actions: QuizActions;
  primary: Primary;
}

/** Multiple choice (and any type this client doesn't know): a radiogroup of
 *  answer rows, chosen by click, A–F / 1–6 on the screen, or the arrows. */
function ChoiceAnswer({ view, shown, selectable, actions }: AnswerFieldProps) {
  const optionsRef = useRef<HTMLDivElement>(null);
  const { options, selectedIndex } = view;

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!selectable || options.length === 0) return;
    const step = arrowStep(e.key);
    if (step === 0) return;
    e.preventDefault();
    e.stopPropagation();
    const next = nextOptionIndex(selectedIndex, step, options.length);
    actions.select(next);
    optionsRef.current?.querySelectorAll<HTMLElement>('[role="radio"]')[next]?.focus();
  };

  return (
    <>
      <p className="quiz-question__hint" id="quiz-keyboard-hint" data-testid="quiz-keyboard-hint">
        Keyboard: press A to F, or 1 to 6, to choose an answer. Enter submits your answer and
        moves to the next question. Escape leaves the quiz.
      </p>
      <div
        ref={optionsRef}
        className="quiz-question__options"
        role="radiogroup"
        aria-label="Answer choices"
        aria-describedby="quiz-keyboard-hint"
        data-testid="quiz-answer-options"
        onKeyDown={onKeyDown}
      >
        {options.map((option, index) => (
          <AnswerOption
            key={option.label}
            letter={option.label}
            text={option.text}
            state={optionState(index, selectedIndex, shown)}
            status={optionStatus(index, selectedIndex, shown)}
            disabled={!selectable}
            onSelect={() => actions.select(index)}
            // The group owns one tab stop: the chosen row, or the first row
            // while nothing is chosen.
            tabIndex={index === (selectedIndex ?? 0) ? 0 : -1}
            testid={`quiz-answer-option-${option.label}`}
          />
        ))}
      </div>
    </>
  );
}

/** Short answer, numeric and algebra: one input shaped to its format, with
 *  the grader's rules for it underneath. */
function WrittenField({ view, shown, selectable, actions, primary }: AnswerFieldProps) {
  const type = view.item?.question.type;
  return (
    <div
      className={`quiz-question__written quiz-question__written--${view.format}`}
      data-marked={shown ? "true" : undefined}
    >
      {/* The accessible name ("Your answer, <stem>"); on screen the format
          tag and the field's own shape already say what goes here. */}
      <label htmlFor="quiz-written-answer" className="quiz-question__sr" id="quiz-written-label">Your answer</label>
      <WrittenAnswer
        type={(type ?? "short_answer") as WrittenType}
        value={view.item?.answerText ?? ""}
        disabled={!selectable}
        verdict={outcomeOf(shown) ?? null}
        onChange={text => actions.write?.(text)}
        onSubmit={() => {
          if (primary.enabled) primary.activate();
        }}
        describedBy="quiz-format-hint"
        labelledBy="quiz-written-label quiz-question-stem"
      />
      {/* Visible, unlike the keyboard hint: these are the rules the
          grader applies, so a sighted student needs them as much as a
          screen-reader user does. */}
      <p className="quiz-question__format-hint" id="quiz-format-hint" data-testid="quiz-format-hint">
        {formatHint(type)}
      </p>
    </div>
  );
}

/** What every kit's answer component is handed besides its interaction. */
interface KitAnswerProps {
  value: string;
  disabled: boolean;
  expected: string | null;
  verdict: Outcome | null;
  onChange: (text: string) => void;
}

type KitInteraction = NonNullable<QuizItem["question"]["interaction"]>;

/**
 * W7.2 kit answers on a short_answer, one per kind (Sort 7.1, Sequence 7.2,
 * Connect 7.3 match or concept map, Label 7.4, Highlight 7.10, Position 7.12,
 * Calculate 7.13 value + unit, Rank 7.15 ordered slots + why, Explain 7.16
 * tall prose, Dialogue 7.17, Build, Compare): null when the interaction is not
 * a usable payload of that kind. Check uses the encoded short_answer text.
 */
const KIT_ANSWERS: Record<KitKind, (interaction: KitInteraction | undefined, props: KitAnswerProps) => React.JSX.Element | null> = {
  sort: (i, p) => { const k = asSortInteraction(i); return k && <SortAnswer interaction={k} {...p} />; },
  sequence: (i, p) => { const k = asSequenceInteraction(i); return k && <SequenceAnswer interaction={k} {...p} />; },
  label: (i, p) => { const k = asLabelInteraction(i); return k && <LabelAnswer interaction={k} {...p} />; },
  build: (i, p) => { const k = asBuildInteraction(i); return k && <BuildAnswer interaction={k} {...p} />; },
  compare: (i, p) => { const k = asCompareInteraction(i); return k && <CompareAnswer interaction={k} {...p} />; },
  dialogue: (i, p) => { const k = asDialogueInteraction(i); return k && <DialogueAnswer interaction={k} {...p} />; },
  explain: (i, p) => { const k = asExplainInteraction(i); return k && <ExplainAnswer interaction={k} {...p} />; },
  highlight: (i, p) => { const k = asHighlightInteraction(i); return k && <HighlightAnswer interaction={k} {...p} />; },
  calculate: (i, p) => { const k = asCalculateInteraction(i); return k && <CalculateAnswer interaction={k} {...p} />; },
  position: (i, p) => { const k = asPositionInteraction(i); return k && <PositionAnswer interaction={k} {...p} />; },
  rank: (i, p) => { const k = asRankInteraction(i); return k && <RankAnswer interaction={k} {...p} />; },
  connect: (i, p) => { const k = asConnectInteraction(i); return k && <ConnectAnswer interaction={k} {...p} />; },
};

/** One kit's field: its answer component, then the kit's rules underneath. */
function KitField({ kind, ...props }: AnswerFieldProps & { kind: KitKind }) {
  const { view, shown, selectable, actions } = props;
  const answer = KIT_ANSWERS[kind](view.item?.question.interaction, {
    value: view.item?.answerText ?? "",
    disabled: !selectable,
    expected: shown?.correctAnswer ?? null,
    verdict: outcomeOf(shown) ?? null,
    onChange: text => actions.write?.(text),
  });
  if (!answer) return <WrittenField {...props} />;
  return (
    <div
      className={`quiz-question__written quiz-question__written--${kind}`}
      data-marked={shown ? "true" : undefined}
    >
      {answer}
      <p className="quiz-question__format-hint" id="quiz-format-hint" data-testid="quiz-format-hint">
        {formatHint("short_answer", { [kind]: true })}
      </p>
    </div>
  );
}

/** One answer field per wire format. */
const ANSWER_FIELDS: Record<QuestionType, (props: AnswerFieldProps) => React.JSX.Element> = {
  multiple_choice: ChoiceAnswer,
  short_answer: WrittenField,
  numeric: WrittenField,
  symbolic: WrittenField,
};

/** The open item's answer field: a short_answer carrying a kit draws the kit. */
export function AnswerFieldFor(props: AnswerFieldProps) {
  const kind = props.view.format === "short_answer" ? kitKindOf(props.view.item?.question.interaction) : null;
  if (kind) return <KitField kind={kind} {...props} />;
  const Field = ANSWER_FIELDS[props.view.format];
  return <Field {...props} />;
}
