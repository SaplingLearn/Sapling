"use client";
import React, { useId, useLayoutEffect, useRef } from "react";
import { type LoopCheckItem, type LoopReportReason } from "@/lib/api";
import { ReportQuestion } from "./ReportQuestion";
import { ConfidenceControl } from "./ConfidenceControl";
import { OptionList } from "./OptionList";
import { Icon } from "../Icon";
import tutorStyles from "./tutor/tutor.module.css";
import { modalOpen } from "./modalOpen";
import { type Draft, FIELD_STYLE, type HintView, focusAnswerStart } from "./loopShared";

/** Plain-English lines for POST /hint's denial reasons (routes/learn_loop.py::hint). */
const HINT_DENIED_COPY: Record<string, string> = {
  no_genuine_attempt: "Give it a real try first — write what you think in the answer box, then ask again.",
  dwell: "Stay with this step a little longer before the next hint.",
  ceiling: "That's all the help this question allows right now. Give it your best answer — you'll see the full answer after.",
  h6_gate: "The worked answer unlocks once you've tried the question yourself.",
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
  const ids = useId();
  const headingId = `${ids}-heading`;
  const promptId = `${ids}-prompt`;
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
  return (
    <section
      ref={cardRef}
      aria-labelledby={headingId}
      className={`card ${tutorStyles.qcard}`}
    >
      <div
        data-testid="loop-check-prompt"
        data-question-hash={item.question_hash}
        data-format={item.format}
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        <div className={tutorStyles.qhead}>
          <h2 id={headingId} className={`label-micro ${tutorStyles.qlabel}`}>Check your understanding</h2>
          {conceptName && <span className="chip">{conceptName}</span>}
        </div>
        <p id={promptId} className={tutorStyles.q}>{item.prompt}</p>
      </div>
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
          <label className={tutorStyles.fl} htmlFor={`${ids}-reason`} style={{ marginBottom: -8 }}>Your reasoning</label>
          <input
            id={`${ids}-reason`}
            data-testid="loop-attempt-reason"
            style={FIELD_STYLE}
            placeholder="In one sentence: why?"
            value={draft.reason}
            disabled={busy}
            onChange={(e) => {
              const reason = e.target.value;
              setDraft((d) => ({ ...d, reason }));
            }}
          />
        </>
      ) : (
        <>
        <label className={tutorStyles.fl} htmlFor={`${ids}-answer`} style={{ marginBottom: -8 }}>Your answer — this is what gets checked</label>
        <textarea
          id={`${ids}-answer`}
          data-testid="loop-attempt-input"
          data-answer-start=""
          aria-describedby={promptId}
          style={FIELD_STYLE}
          rows={2}
          placeholder={item.format === "teachback" ? "Explain it in your own words" : ""}
          value={draft.answer}
          disabled={busy}
          onChange={(e) => {
            const answer = e.target.value;
            setDraft((d) => ({ ...d, answer }));
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSubmit) onSubmit();
          }}
        />
        </>
      )}
      <ConfidenceControl
        testIdPrefix="loop-check-confidence"
        value={draft.confidence}
        onChange={(confidence) => setDraft((d) => ({ ...d, confidence }))}
        disabled={busy}
      />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button data-testid="loop-attempt-submit" className="btn btn--primary" disabled={!canSubmit} onClick={onSubmit}>
          Submit answer
        </button>
        <button
          data-testid="loop-hint-button"
          className="btn"
          aria-disabled={hintUnavailable}
          style={hintUnavailable ? { cursor: "not-allowed" } : undefined}
          onClick={() => {
            if (!hintUnavailable) onHint();
          }}
        >
          <Icon name="sparkle" size={13} />{hintBusy ? "Hint…" : hintRetry ? "Retry earned hint" : "Hint"}
        </button>
        <button data-testid="loop-attempt-idk" className="btn btn--ghost" disabled={busy || hintBusy} onClick={onIdk}>
          I don&apos;t know
        </button>
      </div>
      {/* Always in the DOM, so a refusal is announced when it appears. */}
      <div aria-live="polite">
        {hint && "denied" in hint && (
          <div
            data-testid="loop-hint-denied"
            data-reason={hint.denied}
            role="status"
            style={{ fontSize: 13, color: "var(--text-muted)" }}
          >
            {HINT_DENIED_COPY[hint.denied] ?? HINT_DENIED_FALLBACK}
          </div>
        )}
      </div>
      {hint && "reply" in hint && (
        <div
          data-testid="loop-hint-reply"
          style={{
            fontSize: 14,
            padding: "10px 12px",
            borderRadius: "var(--r-md)",
            border: "1px solid var(--accent-border)",
            background: "var(--accent-soft)",
            whiteSpace: "pre-wrap",
            display: "flex",
            gap: 8,
          }}
        >
          <span style={{ color: "var(--accent)", marginTop: 2 }} aria-hidden><Icon name="sparkle" size={13} /></span>
          <span>{hint.reply}</span>
        </div>
      )}
      {selfExplain}
      {onReport && <ReportQuestion testIdPrefix="loop-check-report" disabled={busy} onReport={onReport} />}
    </section>
  );
}
