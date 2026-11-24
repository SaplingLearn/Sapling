"use client";
import React from "react";
import Link from "next/link";

import { Icon } from "@/components/Icon";
import { tierFill, tierLabel, tierText } from "@/components/studyGuide/shared/tiers";
import { useFlag } from "@/context/FlagsContext";
import { buildQuizHref } from "@/lib/quiz/source";
import type { ConceptMapBlock } from "@/lib/studyGuide/types";
import { studyGuideReaderHref } from "@/lib/toolHrefs";

import { useReader } from "../ReaderContext";
import { conceptTier } from "../readerModel";
import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";

/** Tutor Ask prompts only — Quiz is a tool deep link (W7.D2 / W7.9). */
const PROMPTS: { label: string; message: (concept: string) => string }[] = [
  { label: "Explain it a simpler way", message: concept => `Explain ${concept} a simpler way.` },
  { label: "Give me another example", message: concept => `Give me another example of ${concept}.` },
];

/** Guide concept-map → Quiz Practice with `start=1`. Concept maps carry names,
 *  so the href uses `topic` (fuzzy resolve); return lands back on this guide. */
export function guideConceptQuizHref(guideId: string, conceptName: string): string {
  return buildQuizHref(
    { topic: conceptName },
    { kind: "link", returnTo: studyGuideReaderHref(guideId) },
    { start: true },
  );
}

function TutorPrompts({
  blockId,
  concept,
  quizHref,
  onClose,
}: {
  blockId: string;
  concept: string;
  /** Null while `hide_quiz` is on. */
  quizHref: string | null;
  onClose: () => void;
}) {
  const { askTutor, tutorBusy } = useReader();
  return (
    <div className={s.prompts}>
      <div className={s.promptsHead}>
        <span className={s.promptsTitle}>
          <Icon name="clover" size={16} />
          Ask the tutor about {concept}
        </span>
        <button
          type="button"
          className={s.close}
          data-testid={`guide-concept-close-${blockId}`}
          aria-label="Close tutor prompts"
          onClick={onClose}
        >
          <Icon name="cross" size={13} />
        </button>
      </div>
      <div className={s.promptList}>
        {quizHref && (
          <Link
            href={quizHref}
            className={s.option}
            data-testid={`guide-concept-quiz-${blockId}`}
          >
            Quiz this concept
          </Link>
        )}
        {PROMPTS.map((prompt, i) => (
          <button
            key={prompt.label}
            type="button"
            className={s.option}
            data-testid={`guide-concept-prompt-${blockId}-${i}`}
            disabled={tutorBusy}
            onClick={() => askTutor(concept, prompt.message(concept))}
          >
            {prompt.label}
          </button>
        ))}
      </div>
      {tutorBusy && (
        <span role="status" className={s.small}>
          Opening the tutor
        </span>
      )}
    </div>
  );
}

/** What the section builds on, in learning order, with mastery as it is now. */
export function ConceptMapBlockView({ block }: { block: ConceptMapBlock }) {
  const { guide } = useReader();
  const quizShown = useFlag("hide_quiz") !== "on";
  const [picked, setPicked] = React.useState<number | null>(null);
  const selected = picked === null ? undefined : block.nodes[picked];
  const treeHref = selected ? `/tree?suggest=${encodeURIComponent(selected.concept)}` : "/tree";
  const quizHref =
    selected && quizShown ? guideConceptQuizHref(guide.id, selected.concept) : null;

  return (
    <BlockFrame
      blockId={block.id}
      tone="accent"
      icon={<Icon name="trees" size={15} />}
      label="Concept map"
      title={block.title}
      actions={
        <Link href={treeHref} className={s.treeLink}>
          Open in Tree
        </Link>
      }
      footer={
        quizShown
          ? "Left to right is the order to learn them in. Select a concept to quiz it or ask the tutor."
          : "Left to right is the order to learn them in. Select a concept to ask the tutor about it."
      }
    >
      <div className={s.concepts}>
        {block.nodes.map((node, i) => {
          const tier = conceptTier(node.concept, guide.mastery);
          return (
            <button
              key={i}
              type="button"
              className={s.concept}
              data-testid={`guide-concept-${block.id}-${i}`}
              aria-pressed={picked === i}
              onClick={() => setPicked(picked === i ? null : i)}
            >
              <span className="label-micro">{node.step}</span>
              <span className={s.conceptName}>{node.concept}</span>
              <span className={s.tier} style={{ color: tierText(tier) }}>
                <span className={s.tierDot} style={{ background: tierFill(tier) }} aria-hidden="true" />
                {tierLabel(tier)}
              </span>
            </button>
          );
        })}
      </div>
      {selected && (
        <TutorPrompts
          blockId={block.id}
          concept={selected.concept}
          quizHref={quizHref}
          onClose={() => setPicked(null)}
        />
      )}
    </BlockFrame>
  );
}
