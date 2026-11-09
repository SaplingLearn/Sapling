"use client";
// Spec §13 A139 (`self_explanation_prompts` on): the student's answer to the
// turn's "why does this follow?" question — asked by code at a key juncture
// (after a worked example, after a shown solution, after a first unaided
// correct answer), at most once per concept a session. The reply is stored for
// diagnosis only: it is never graded, never evidence and never moves mastery;
// Skip is always there. The prompt is the turn's own last line (already in the
// conversation log, so it is announced there); this card repeats it and takes
// the reply.
//
// Rendered inside the check card under a worked-example hint (the Hint button
// keeps focus there), or in place of the Continue / Check me row after
// feedback — where LoopLearn moves lost focus to `inputRef` (spec §13 A135).
import React, { useId, useState } from "react";

import type { LoopSelfExplain } from "@/lib/api";

const FIELD_STYLE: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  fontSize: 14,
  lineHeight: 1.45,
  border: "1px solid var(--border)",
  borderRadius: "var(--r-md)",
  background: "var(--bg-input)",
  resize: "vertical",
  boxSizing: "border-box",
};

export const SELF_EXPLAIN_HEADING = "Explain it in your own words";
export const SELF_EXPLAIN_SUBLINE = "Not scored — a sentence or two is plenty.";

export function SelfExplainCard({
  prompt,
  busy,
  onSend,
  onSkip,
  inputRef,
  nested = false,
}: {
  prompt: LoopSelfExplain;
  busy: boolean;
  onSend: (reply: string) => void;
  onSkip: () => void;
  /** The reply box, for LoopLearn's focus move after feedback. */
  inputRef?: React.Ref<HTMLTextAreaElement>;
  /** Inside the check card: a sub-section (h3) rather than its own card (h2). */
  nested?: boolean;
}) {
  const [reply, setReply] = useState("");
  const ids = useId();
  const headingId = `${ids}-heading`;
  const promptId = `${ids}-prompt`;
  const canSend = !busy && reply.trim() !== "";
  const send = () => {
    if (canSend) onSend(reply.trim());
  };
  const Heading = nested ? "h3" : "h2";
  return (
    <section
      aria-labelledby={headingId}
      data-testid="loop-self-explain"
      data-juncture={prompt.juncture}
      data-prompt-id={prompt.prompt_id}
      className={nested ? undefined : "card"}
      style={
        nested
          ? {
              display: "flex", flexDirection: "column", gap: 8, padding: "10px 12px",
              borderRadius: "var(--r-md)", border: "1px dashed var(--border)", background: "var(--bg-soft)",
            }
          : { padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8, borderColor: "var(--accent-border)" }
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Heading id={headingId} className="label-micro" style={{ margin: 0, fontWeight: 400 }}>{SELF_EXPLAIN_HEADING}</Heading>
        <p style={{ margin: 0, fontSize: 13, color: "var(--text-dim)" }}>{SELF_EXPLAIN_SUBLINE}</p>
        <p
          id={promptId}
          data-testid="loop-self-explain-prompt"
          style={{ margin: "4px 0 0", fontSize: 15, lineHeight: 1.5, whiteSpace: "pre-wrap" }}
        >
          {prompt.prompt}
        </p>
      </div>
      <textarea
        ref={inputRef}
        data-testid="loop-self-explain-input"
        aria-label="Your explanation"
        aria-describedby={promptId}
        style={FIELD_STYLE}
        rows={2}
        placeholder="Because…"
        value={reply}
        disabled={busy}
        onChange={(e) => setReply(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
        }}
      />
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <button
          type="button"
          data-testid="loop-self-explain-send"
          className="btn btn--sm btn--primary"
          disabled={!canSend}
          onClick={send}
        >
          {busy ? "Saving…" : "Send"}
        </button>
        <button type="button" data-testid="loop-self-explain-skip" className="btn btn--sm btn--ghost" disabled={busy} onClick={onSkip}>
          Skip
        </button>
      </div>
    </section>
  );
}
