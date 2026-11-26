"use client";
import React, { useLayoutEffect, useRef } from "react";
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import { type LoopCheckItem, type LoopReportReason } from "@/lib/api";
import { ReportQuestion } from "./ReportQuestion";
import { ConfidenceControl } from "./ConfidenceControl";
import { OptionList } from "./OptionList";
import { Icon } from "../Icon";
import styles from "./CheckCard.module.css";
import { modalOpen } from "./modalOpen";
import { type Draft, type HintView, focusAnswerStart } from "./loopShared";
import { AnswerField, QuestionActions, QuestionCard, REASON_LABEL } from "./question/QuestionCard";

/** Plain-English lines for POST /hint's denial reasons (routes/learn_loop.py::hint). */
const HINT_DENIED_COPY: Record<string, string> = {
  no_genuine_attempt: "Give it a real try first — write what you think in the answer box, then ask again.",
  // #866 K32: the student wrote an answer; only time alone with the question is missing
  too_soon: "Stay with the question a little longer on your own — what you wrote counts as a try then. Ask again in a moment.",
  dwell: "Stay with this step a little longer before the next hint.",
  ceiling: "That's all the help this question allows right now. Give it your best answer — you'll see the full answer after.",
  h6_gate: "The full worked answer isn't available for this question. Give it your best answer — you'll see the full answer after.",
  h6_attempt: "The worked answer unlocks after another real try — write what you think in the answer box, then ask again.",
  no_active_item: "There's no open question to hint on right now.",
};
const HINT_DENIED_FALLBACK = "No hint right now — keep working on it.";

export function CheckCard({
  item, conceptName, draft, setDraft, busy, hint, hintBusy, hintRetry, onSubmit, onIdk, onHint, onReport, selfExplain,
}: {
  item: LoopCheckItem;
  /** The concept the check is on (the chip in the card's head). */
  conceptName?: string | null;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  busy: boolean;
  hint: HintView;
  hintBusy: boolean;
  hintRetry: boolean;
  onSubmit: () => void;
  onIdk: () => void;
  onHint: () => void;
  /** spec §13 A113: present while the `item_reports` flag is on. */
  onReport?: (reason: LoopReportReason) => Promise<boolean>;
  /** spec §13 A139: an open "why" prompt, rendered under the hint it follows. */
  selfExplain?: React.ReactNode;
}) {
  const mc = item.format === "mc_reason";
  // K02: an mc_reason answer needs its reason; K09: a loading hint (its rung already charged) is shown first
  const canSubmit = !busy && !hintBusy && (mc ? draft.option !== "" && draft.reason.trim() !== "" : draft.answer.trim() !== "");
  const cardRef = useRef<HTMLElement>(null);
  // spec §13 A135: a posed check takes focus — its answer box, described by the
  // question (or the options' tab stop, named by it): a screen reader is told a
  // question appeared, and the student can answer at once. The pose and the
  // hint also stay in the conversation log (visually hidden while the card
  // shows them), so they are announced as they arrive.
  useLayoutEffect(() => {
    if (modalOpen()) return;
    focusAnswerStart(cardRef.current);
  }, [item.question_hash]);
  // While a hint loads the Hint button keeps focus (aria-disabled, not
  // disabled: a disabled control drops focus to the page).
  const hintUnavailable = hintBusy || busy;
  const m = useMotionPresets();
  const figure = item.figure?.status === "withheld" ? (
    // W4.1a: honest empty figure slot when the pose says the item is visual but
    // no drawable asset is attached yet. Never invents SVG.
    <div
      data-testid="loop-figure-withheld"
      role="status"
      aria-label="No diagram for this check yet — the question describes it in words"
      className={`${styles.trustChrome} ${styles.figureWithheld}`}
    >
      Diagram described in words — no figure attached yet
    </div>
  ) : null;
  return (
    // Keyed on the question: the next check rises in as a new card. One plain
    // line names it (the concept), and it stays the card's heading.
    <QuestionCard
      key={item.question_hash}
      graded
      meta={conceptName || "Question"}
      prompt={item.prompt}
      afterPrompt={figure}
      head={{ testId: "loop-check-prompt", "data-question-hash": item.question_hash, "data-format": item.format }}
      sectionRef={cardRef}
    >
      {({ promptId }) => (
        <>
          {mc ? (
            <>
              <OptionList
                options={item.options ?? []}
                selected={draft.option}
                onSelect={(letter) => setDraft((d) => ({ ...d, option: letter }))}
                testIdPrefix="loop-attempt-option"
                labelledBy={promptId}
                disabled={busy}
              />
              <AnswerField label={REASON_LABEL} name="reason" testId="loop-attempt-reason" singleLine describedByPrompt={false}
                placeholder="Because…" value={draft.reason} disabled={busy}
                onChange={(reason) => setDraft((d) => ({ ...d, reason }))} />
            </>
          ) : (
            <>
              <AnswerField label="Your answer" name="answer" testId="loop-attempt-input" start
                placeholder={item.format === "teachback" ? "Explain it in your own words" : undefined}
                value={draft.answer} disabled={busy}
                onChange={(answer) => setDraft((d) => ({ ...d, answer }))}
                onSubmit={() => { if (canSubmit) onSubmit(); }} />
              {/* W2.3: never graded, never mastery: the answer above is what is checked. */}
              <AnswerField label="Your reasoning, not graded" name="reasoning" testId="loop-attempt-reasoning" describedByPrompt={false}
                placeholder="Show your thinking…" value={draft.reasoning} disabled={busy}
                onChange={(reasoning) => setDraft((d) => ({ ...d, reasoning }))} />
            </>
          )}
          <ConfidenceControl
            testIdPrefix="loop-check-confidence"
            value={draft.confidence}
            onChange={(confidence) => setDraft((d) => ({ ...d, confidence }))}
            disabled={busy}
          />
          <QuestionActions
            submit={{ label: "Submit answer", busyLabel: "Checking…", busy, disabled: !canSubmit, onClick: onSubmit, testId: "loop-attempt-submit" }}
            optOut={{ label: "I don't know", disabled: busy || hintBusy, onClick: onIdk, testId: "loop-attempt-idk" }}
          >
            <button
              type="button"
              data-testid="loop-hint-button"
              className={`btn ${styles.press}${hintUnavailable ? ` ${styles.unavailable}` : ""}`}
              aria-disabled={hintUnavailable}
              onClick={() => {
                if (!hintUnavailable) onHint();
              }}
            >
              <Icon name="sparkle" size={13} />{hintBusy ? "Hint…" : hintRetry ? "Retry earned hint" : "Hint"}
            </button>
          </QuestionActions>
          {/* Always in the DOM, so a refusal is announced when it appears. */}
          <div aria-live="polite">
            {hint && "denied" in hint && (
              <motion.div
                {...m.fade}
                data-testid="loop-hint-denied"
                data-reason={hint.denied}
                role="status"
                className={styles.hintDenied}
              >
                {HINT_DENIED_COPY[hint.denied] ?? HINT_DENIED_FALLBACK}
              </motion.div>
            )}
          </div>
          {hint && "reply" in hint && (
            // Re-keyed per hint: each rung rises in, so a new one reads as new.
            <motion.div
              key={hint.reply}
              {...m.fadeUp}
              data-testid="loop-hint-reply"
              className={styles.hintReply}
            >
              <span className={styles.hintIcon} aria-hidden><Icon name="sparkle" size={13} /></span>
              <span>{hint.reply}</span>
            </motion.div>
          )}
          {selfExplain}
          {onReport && <ReportQuestion testIdPrefix="loop-check-report" disabled={busy} onReport={onReport} />}
        </>
      )}
    </QuestionCard>
  );
}
