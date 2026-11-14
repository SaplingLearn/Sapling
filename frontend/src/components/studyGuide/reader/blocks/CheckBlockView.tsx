"use client";
import React from "react";

import { Icon } from "@/components/Icon";
import { useToast } from "@/components/ToastProvider";
import { tierFill, tierLabel } from "@/components/studyGuide/shared/tiers";
import { AnswerOption } from "@/components/ui";
import { answerCheck } from "@/lib/studyGuide/api";
import type { CheckAnswer, CheckBlock, CheckOption, MasteryChange } from "@/lib/studyGuide/types";

import { recordAnswer } from "../guideEdits";
import { useReader } from "../ReaderContext";
import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";

/** The mastery an answer moved, kept with the pick it belongs to. */
interface Moved {
  optionId: string;
  change: MasteryChange;
}

function Result({ block, answer, moved }: { block: CheckBlock; answer: CheckAnswer; moved: MasteryChange | null }) {
  return (
    <div role="status" className={answer.correct ? s.right : s.wrong} data-testid={`guide-check-result-${block.id}`}>
      <span className={s.resultText}>
        <strong>{answer.correct ? "Correct." : "Not quite."}</strong>{" "}
        {answer.correct ? block.explain_correct : block.explain_incorrect}
      </span>
      {moved && moved.before !== moved.after && (
        <span className={s.moved}>
          <span className={s.tierDot} style={{ background: tierFill(moved.after) }} aria-hidden="true" />
          {moved.concept}: {tierLabel(moved.before)} to {tierLabel(moved.after)}
        </span>
      )}
    </div>
  );
}

/**
 * A check-yourself question. The first answer counts toward mastery.
 *
 * The pick and its explanation are read off the guide, not kept here: a
 * question that is rewritten under the same id starts unanswered.
 */
export function CheckBlockView({ block }: { block: CheckBlock }) {
  const { userId, guide, update } = useReader();
  const toast = useToast();
  const answer = guide.answers[block.id];
  const [moved, setMoved] = React.useState<Moved | null>(null);
  const [busy, setBusy] = React.useState(false);

  const pick = async (option: CheckOption) => {
    setBusy(true);
    try {
      const result = await answerCheck(userId, guide.id, block.id, option.id);
      // An uncounted pick leaves the first answer, and what it moved, shown.
      if (result.counted) setMoved(result.mastery && { optionId: option.id, change: result.mastery });
      update(current => recordAnswer(current, block.id, option.id, result));
    } catch {
      toast.error("Your answer could not be checked. Try again.");
    } finally {
      setBusy(false);
    }
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
          {block.options.map(option => {
            const picked = answer?.option_id === option.id;
            return (
              <AnswerOption
                key={option.id}
                letter={option.id.toUpperCase()}
                text={option.text}
                state={picked ? (answer.correct ? "correct" : "chosen-wrong") : "default"}
                checked={picked}
                disabled={busy}
                // Every row is a tab stop: a wrong pick can be followed by another.
                tabIndex={0}
                testid={`guide-check-option-${block.id}-${option.id}`}
                onSelect={() => pick(option)}
              />
            );
          })}
        </div>
        {answer && (
          <Result
            block={block}
            answer={answer}
            moved={moved?.optionId === answer.option_id ? moved.change : null}
          />
        )}
      </div>
    </BlockFrame>
  );
}
