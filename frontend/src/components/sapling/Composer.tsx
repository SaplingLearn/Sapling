"use client";
import React from "react";
import { SaplingAction } from "./primitives";

/**
 * Enter sends; Shift+Enter is a newline; an IME composition (and the
 * keyCode-229 events some browsers emit while composing) never sends.
 * Exported so ChatPanel and any other composer apply the same rule.
 */
export function isSendKey(event: Pick<React.KeyboardEvent, "key" | "shiftKey" | "nativeEvent"> & { keyCode?: number }): boolean {
  if (event.key !== "Enter" || event.shiftKey) return false;
  const native = event.nativeEvent as KeyboardEvent | undefined;
  if (native?.isComposing) return false;
  if ((event.keyCode ?? native?.keyCode) === 229) return false;
  return true;
}

export type ComposerState = "idle" | "sending" | "streaming";

export interface SaplingComposerProps {
  value: string;
  onChange: (value: string) => void;
  /**
   * Called with the trimmed text. The caller owns sending, duplicate
   * protection, errors and whether the draft clears — this view never clears
   * it, so a failed send cannot silently lose the student's words.
   */
  onSend: (text: string) => void;
  state?: ComposerState;
  /** Shown while a reply streams. Must cancel the real request/stream. */
  onStop?: () => void;
  /** False when the current phase/budget does not allow a conversational
   *  turn; the reason is announced next to the field. */
  canSend?: boolean;
  disabledReason?: string;
  /** Visually hidden field label (the accessible name). */
  label?: string;
  placeholder?: string;
  /** Leading row content, e.g. a link to the course's real materials. */
  lead?: React.ReactNode;
  testid?: string;
}

/** The redesign's composer surface (prompt 01). A conversation input only:
 *  it is never the knowledge-check answer form and never grades anything. */
export function SaplingComposer({
  value,
  onChange,
  onSend,
  state = "idle",
  onStop,
  canSend = true,
  disabledReason,
  label = "Message Clov",
  placeholder = "Ask Clov, or think out loud…",
  lead,
  testid = "sapling-composer",
}: SaplingComposerProps) {
  const fieldId = React.useId();
  const hintId = `${fieldId}-hint`;
  const reasonId = `${fieldId}-reason`;
  const busy = state !== "idle";
  const sendable = canSend && !busy && value.trim().length > 0;

  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    if (sendable) onSend(value.trim());
  };

  return (
    <form className="sapling-composer" onSubmit={submit} aria-label={label} data-testid={testid}>
      <label className="sapling-visually-hidden" htmlFor={fieldId}>{label}</label>
      <textarea
        id={fieldId}
        className="sapling-composer__field"
        value={value}
        rows={2}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (isSendKey(e)) {
            e.preventDefault();
            submit();
          }
        }}
        aria-describedby={[hintId, !canSend && disabledReason ? reasonId : null].filter(Boolean).join(" ")}
        data-testid={`${testid}-input`}
      />
      {!canSend && disabledReason && (
        <p id={reasonId} className="sapling-composer__status">{disabledReason}</p>
      )}
      <div className="sapling-composer__row">
        <div className="sapling-composer__lead">
          {lead}
          <p id={hintId} className="sapling-composer__hint">Enter to send · Shift + Enter for a new line</p>
        </div>
        {busy && onStop ? (
          <SaplingAction tone="secondary" onClick={onStop} data-testid={`${testid}-stop`}>Stop</SaplingAction>
        ) : (
          <SaplingAction type="submit" disabled={!sendable} data-testid={`${testid}-send`}>Send</SaplingAction>
        )}
      </div>
      <p className="sapling-composer__status" role="status" aria-live="polite">
        {state === "sending" ? "Sending…" : state === "streaming" ? "Clov is responding…" : ""}
      </p>
    </form>
  );
}
