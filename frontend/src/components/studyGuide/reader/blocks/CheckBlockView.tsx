"use client";
import React from "react";

import { Icon } from "@/components/Icon";
import { useToast } from "@/components/ToastProvider";
import { tierFill, tierLabel } from "@/components/studyGuide/shared/tiers";
import { AnswerOption, type AnswerState } from "@/components/ui";
import { answerCheck } from "@/lib/studyGuide/api";
import type { CheckAnswer, CheckBlock, CheckOption, MasteryChange } from "@/lib/studyGuide/types";

import { recordAnswer } from "../guideEdits";
import { useReader } from "../ReaderContext";
import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";

interface Outcome {
  correct: boolean;
  explanation: string | null;
  /** Mastery moved with this answer. Null for a restored or repeated one. */
  mastery: MasteryChange | null;
}

/** The outcome of an answer given on an earlier visit, from what the guide stores. */
function storedOutcome(block: CheckBlock, answer: CheckAnswer | undefined): Outcome | null {
  if (!answer) return null;
  const explanation = answer.correct ? block.explain_correct : block.explain_incorrect;
  return { correct: answer.correct, explanation, mastery: null };
}

function Result({ blockId, outcome }: { blockId: string; outcome: Outcome }) {
  const { mastery } = outcome;
  return (
    <div role="status" className={outcome.correct ? s.right : s.wrong} data-testid={`guide-check-result-${blockId}`}>
      <span className={s.resultText}>
        <strong>{outcome.correct ? "Correct." : "Not quite."}</strong> {outcome.explanation}
      </span>
      {mastery && mastery.before !== mastery.after && (
        <span className={s.moved}>
          <span className={s.tierDot} style={{ background: tierFill(mastery.after) }} aria-hidden="true" />
          {mastery.concept}: {tierLabel(mastery.before)} to {tierLabel(mastery.after)}
        </span>
      )}
    </div>
  );
}

/** A check-yourself question. The first answer counts toward mastery. */
export function CheckBlockView({ block }: { block: CheckBlock }) {
  const { userId, guide, update } = useReader();
  const toast = useToast();
  const stored = guide.answers[block.id];
  const [picked, setPicked] = React.useState<string | null>(stored?.option_id ?? null);
  const [outcome, setOutcome] = React.useState<Outcome | null>(() => storedOutcome(block, stored));
  const [busy, setBusy] = React.useState(false);

  const pick = async (option: CheckOption) => {
    setBusy(true);
    try {
      const result = await answerCheck(userId, guide.id, block.id, option.id);
      setPicked(option.id);
      setOutcome({ correct: result.correct, explanation: result.explanation, mastery: result.mastery });
      update(current =>
        recordAnswer(current, block.id, { option_id: option.id, correct: result.correct }, result.mastery),
      );
    } catch {
      toast.error("Your answer could not be checked. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const stateOf = (option: CheckOption): AnswerState => {
    if (option.id !== picked || !outcome) return "default";
    return outcome.correct ? "correct" : "chosen-wrong";
  };

  return (
    <BlockFrame
      blockId={block.id}
      tone="plum"
      icon={<Icon name="bulb" size={15} />}
      label="Check yourself"
      actions={<span className={s.counts}>Counts toward mastery</span>}
      regenerable={false}
    >
      <div className={s.body}>
        <p className={s.question}>{block.question}</p>
        <div role="radiogroup" aria-label="Answers" className={s.answers}>
          {block.options.map(option => (
            <AnswerOption
              key={option.id}
              letter={option.id.toUpperCase()}
              text={option.text}
              state={stateOf(option)}
              disabled={busy}
              // Every row is a tab stop: a wrong pick can be followed by another.
              tabIndex={0}
              testid={`guide-check-option-${block.id}-${option.id}`}
              onSelect={() => pick(option)}
            />
          ))}
        </div>
        {outcome && <Result blockId={block.id} outcome={outcome} />}
      </div>
    </BlockFrame>
  );
}
