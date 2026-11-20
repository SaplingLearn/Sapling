"use client";
import React, { useId, useLayoutEffect, useRef } from "react";
import { type LoopProbeItem } from "@/lib/api";
import { ConfidenceControl } from "./ConfidenceControl";
import { OptionList } from "./OptionList";
import tutorStyles from "./tutor/tutor.module.css";
import { modalOpen } from "./modalOpen";
import { type Draft, FIELD_STYLE, focusAnswerStart } from "./loopShared";
import { TutorTurn } from "./TutorTurn";
import { LOOP_ANSWER_MAX } from "@/lib/inputLimits";

export function ProbePanel({
  item, count, draft, setDraft, reference, note, busy, loadFailed, greeting, onSubmit, onIdk, onNext, onRetry,
}: {
  item: LoopProbeItem | null;
  count: number;
  draft: Draft;
  setDraft: React.Dispatch<React.SetStateAction<Draft>>;
  reference: string | null;
  note: string | null;
  busy: boolean;
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
  // K02: an mc_reason answer needs its reason too (the grader judges it, never the option alone)
  const canSubmit = !!item && !busy && (mc ? draft.option !== "" && draft.reason.trim() !== "" : draft.answer.trim() !== "");
  const ids = useId();
  const promptId = `${ids}-prompt`;
  const headingId = `${ids}-question`;
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
  const referenceBlock = (
    <div
      ref={referenceRef}
      tabIndex={-1}
      data-testid="loop-probe-reference"
      style={{
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        fontSize: 14,
        ...(item ? { padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--bg-soft)" } : null),
      }}
    >
      <div className="label-micro" style={{ marginBottom: 4 }}>Here&apos;s the answer</div>
      {reference}
    </div>
  );
  return (
    <div style={{ flex: 1, overflowY: "auto" }}>
      <div className={tutorStyles.col}>
        <h2 className={tutorStyles.sr}>Quick check-in</h2>
        <TutorTurn testId="loop-probe-greeting">
          {greeting ?? "Let's start with a quick check-in so I know where you are. No hints here; it just shows me what to teach."}
        </TutorTurn>
        {/* The coverage summary reads the check-in's results: it shows on the plan,
            once there is something to summarise, not over the first question. */}
        {!item && busy && <div style={{ fontSize: 14, color: "var(--text-muted)" }}>Loading the next question…</div>}
        {!item && reference !== null && (
          <div className="card" style={{ padding: "var(--pad-xl)", display: "flex", flexDirection: "column", gap: 12 }}>
            {referenceBlock}
            <button data-testid="loop-probe-next" className="btn btn--primary" disabled={busy} onClick={onNext}>
              Next
            </button>
          </div>
        )}
        {!item && !busy && loadFailed && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, color: "var(--text-muted)" }}>
            <span>The next question didn&apos;t load.</span>
            <button data-testid="loop-probe-retry" className="btn btn--sm" onClick={onRetry}>
              Try again
            </button>
          </div>
        )}
        {item && (
          <section
            ref={cardRef}
            aria-labelledby={headingId}
            data-testid="loop-probe-item"
            data-question-hash={item.question_hash}
            data-difficulty={item.difficulty}
            className={`card ${tutorStyles.qcard}`}
          >
            <div className={tutorStyles.qhead}>
              <h3 id={headingId} className={`label-micro ${tutorStyles.qlabel}`}>Check-in · Question {count + (reference === null ? 1 : 0)}</h3>
              <span className="chip">No hints</span>
            </div>
            <p id={promptId} className={tutorStyles.q}>{item.prompt}</p>
            {reference === null ? (
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
                    <label className={tutorStyles.fl} htmlFor={`${ids}-reason`} style={{ marginBottom: -8 }}>In one sentence: why?</label>
                    <input
                      id={`${ids}-reason`}
                      data-testid="loop-probe-reason"
                      maxLength={LOOP_ANSWER_MAX}
                      style={FIELD_STYLE}
                      placeholder="Because…"
                      value={draft.reason}
                      disabled={busy}
                      onChange={(e) => {
                        const reason = e.target.value;
                        setDraft((d) => ({ ...d, reason }));
                      }}
                    />
                  </>
                ) : (
                  <textarea
                    data-testid="loop-probe-input"
                    maxLength={LOOP_ANSWER_MAX}
                    data-answer-start=""
                    aria-label="Check-in answer"
                    aria-describedby={promptId}
                    style={FIELD_STYLE}
                    rows={3}
                    placeholder={item.format === "teachback" ? "Explain it in your own words" : "Your answer"}
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
                )}
                <ConfidenceControl
                  testIdPrefix="loop-probe-confidence"
                  value={draft.confidence}
                  onChange={(confidence) => setDraft((d) => ({ ...d, confidence }))}
                  disabled={busy}
                />
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button data-testid="loop-probe-submit" className="btn btn--primary" disabled={!canSubmit} onClick={onSubmit}>
                    {busy ? "Checking…" : "Submit answer"}
                  </button>
                  <button data-testid="loop-probe-idk" className="btn btn--ghost" disabled={busy} onClick={onIdk}>
                    I don&apos;t know
                  </button>
                </div>
              </>
            ) : (
              <>
                {referenceBlock}
                <button
                  data-testid="loop-probe-next"
                  className="btn btn--primary"
                  style={{ alignSelf: "flex-start" }}
                  disabled={busy}
                  onClick={onNext}
                >
                  Next
                </button>
              </>
            )}
          </section>
        )}
        {note && <div role="status" style={{ fontSize: 13, color: "var(--text-muted)" }}>{note}</div>}
      </div>
    </div>
  );
}
