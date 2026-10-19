"use client";

import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Icon } from "../Icon";
import { BotanicalIcon, isSendKey } from "@/components/sapling";
import styles from "./ChatPanel.module.css";

// MarkdownChat statically imports mermaid, katex, highlight.js, and the
// remark/rehype stack. Static-importing it from a client component still
// pulls those modules through next.config.ts → transpilePackages, which
// bloats the OpenNext worker bundle on Cloudflare. Lazy-load with
// ssr:false so the heavy markdown stack is a separate client chunk.
const MarkdownChat = dynamic(
  () => import("./MarkdownChat").then((m) => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

export type ChatRole = "user" | "assistant";
/** Why a turn did not finish. Copy only; it never changes what Retry does. */
export type InterruptedReason = "stopped" | "failed" | "offline" | "paused";
export interface ChatMsg {
  id: string;
  role: ChatRole;
  content: string;
  loading?: boolean;
  /** ADR 0020: the turn was stopped or failed mid-stream. The partial text
   *  stays in `content` (possibly empty when stopped pre-token); the turn
   *  renders an "interrupted" block and — when `retryText` is set — a Retry
   *  action. Whether a re-send is safe is the caller's decision (`onRetry`). */
  interrupted?: boolean;
  /** The user text that produced this (interrupted) turn — what Retry re-sends. */
  retryText?: string;
  interruptedReason?: InterruptedReason;
  /** The session this turn belonged to: a Retry may only run inside it. */
  turnOwner?: string;
}

interface ChatPanelProps {
  messages: ChatMsg[];
  onSend: (text: string) => void;
  onAction?: (action: "hint" | "confused" | "skip") => void;
  disabled?: boolean;
  placeholder?: string;
  header?: React.ReactNode;
  // Optional seed for the input. Bump `draftSeedKey` to apply.
  draftSeed?: string;
  draftSeedKey?: number;
  /** Assistant text arriving token-by-token; null/undefined = not streaming.
   *  Empty string = stream open but no token yet (shows the typing affordance).
   *  Rendered as a live bubble below the settled messages, then replaced by
   *  the real message once the `done` event lands. */
  streamingText?: string | null;
  /** Abort the in-flight turn. Shown only while streaming. */
  onStop?: () => void;
  /** Re-dispatch an interrupted turn (ADR 0020). Receives the interrupted
   *  message; the caller decides whether a re-send is safe and owns dedup. */
  onRetry?: (m: ChatMsg) => void;
  /** Whether Retry may run right now (no other turn running, same session…).
   *  False renders the action disabled; defaults to always allowed. */
  canRetry?: (m: ChatMsg) => boolean;
  /** Controls between the transcript and the composer. They sit outside the
   *  scrolling transcript, so they never overlap a message. */
  beforeComposer?: React.ReactNode;
  /** Leading content in the composer's lower row (e.g. a link to the course's
   *  real materials). Never an attachment control. */
  composerLead?: React.ReactNode;
  /** Announced next to the field while sending is unavailable. */
  disabledReason?: string;
  /** Accessible name of the message field. */
  inputLabel?: string;
}

/** Within this many px of the end, the reader counts as "at the latest". */
const NEAR_BOTTOM_PX = 48;

export function ChatPanel({
  messages,
  onSend,
  onAction,
  disabled,
  placeholder = "Ask or respond…",
  header,
  draftSeed,
  draftSeedKey,
  streamingText,
  onStop,
  onRetry,
  canRetry,
  beforeComposer,
  composerLead,
  disabledReason,
  inputLabel = "Message",
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const isStreaming = streamingText !== null && streamingText !== undefined;
  // Reading position: follow new content only while the reader is at the end.
  // Scrolled up to review history, they keep their place and get "Jump to latest".
  const following = useRef(true);
  const [behind, setBehind] = useState(false);
  const lastSeen = useRef<string | null>(null);

  const toLatest = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    following.current = true;
    setBehind(false);
  }, []);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
    following.current = atEnd;
    if (atEnd) setBehind(false);
  }, []);

  const last = messages[messages.length - 1];
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // The student's own new turn always brings the conversation to the end.
    const ownTurn = last?.role === "user" && last.id !== lastSeen.current;
    lastSeen.current = last?.id ?? null;
    if (following.current || ownTurn) {
      el.scrollTop = el.scrollHeight;
      following.current = true;
    } else {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- a layout read decides it
      setBehind(true);
    }
  }, [messages, streamingText, last]);

  return (
    <div className={`fa26-chat-panel ${styles.panel}`}>
      {header && <div>{header}</div>}
      <div className={styles.logWrap}>
        <div
          ref={scrollRef}
          className={styles.log}
          data-testid="tutor-messages"
          role="region"
          aria-label="Conversation"
          tabIndex={0}
          onScroll={onScroll}
        >
          {/* Settled turns only: each finished reply is announced once. The
              streaming reply below is outside the live region, so screen
              readers are not read every token. */}
          <div role="log" aria-live="polite" aria-relevant="additions" aria-atomic="false" className={styles.turns}>
            {messages.map((m) => (
              <Message key={m.id} m={m} onRetry={onRetry} retryAllowed={canRetry ? canRetry(m) : true} />
            ))}
          </div>
          {isStreaming && (
            // Reuse Message/MarkdownChat exactly as settled assistant messages
            // do, so a streaming reply never styles differently from a
            // finished one. aria-busy marks it as in progress.
            <div aria-busy="true" className={styles.turns}>
              <Message
                key="streaming"
                m={{ id: "streaming", role: "assistant", content: streamingText ?? "", loading: streamingText === "" }}
              />
            </div>
          )}
        </div>
        {behind && (
          <div className={styles.jump}>
            <span className={styles.jumpNote}>New messages below.</span>
            <button type="button" data-testid="tutor-jump-latest" className={styles.jumpButton} onClick={toLatest}>
              Jump to latest <span aria-hidden="true">↓</span>
            </button>
          </div>
        )}
      </div>

      {beforeComposer && <div className={styles.beforeComposer}>{beforeComposer}</div>}

      <ChatInputBar
        onSend={onSend}
        onAction={onAction}
        disabled={disabled || isStreaming}
        placeholder={placeholder}
        draftSeed={draftSeed}
        draftSeedKey={draftSeedKey}
        streaming={isStreaming}
        onStop={onStop}
        lead={composerLead}
        disabledReason={!isStreaming && disabled ? disabledReason : undefined}
        label={inputLabel}
      />
    </div>
  );
}

interface ChatInputBarProps {
  onSend: (text: string) => void;
  onAction?: (action: "hint" | "confused" | "skip") => void;
  disabled?: boolean;
  placeholder: string;
  draftSeed?: string;
  draftSeedKey?: number;
  streaming?: boolean;
  onStop?: () => void;
  lead?: React.ReactNode;
  disabledReason?: string;
  label: string;
}

const ChatInputBar = React.memo(function ChatInputBar({
  onSend,
  onAction,
  disabled,
  placeholder,
  draftSeed,
  draftSeedKey,
  streaming,
  onStop,
  lead,
  disabledReason,
  label,
}: ChatInputBarProps) {
  const [text, setText] = useState<string>(draftSeed ?? "");
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const hintId = React.useId();
  const reasonId = React.useId();

  // Apply seed when parent bumps the key (e.g. a starter prompt): the field
  // gets the text and focus; nothing is sent until the student sends it.
  useEffect(() => {
    if (draftSeedKey === undefined) return;
    setText(draftSeed ?? "");
    if (draftSeedKey > 0) fieldRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftSeedKey]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className={`fa26-chat-input ${styles.inputBar}`}>
      {onAction && (
        <div className={`fa26-chat-actions ${styles.legacyActions}`}>
          <button data-testid="tutor-action-hint" className="btn btn--sm" onClick={() => onAction("hint")} disabled={disabled} title="Ask for a small nudge">
            <Icon name="sparkle" size={12} /> Hint
          </button>
          <button data-testid="tutor-action-confused" className="btn btn--sm" onClick={() => onAction("confused")} disabled={disabled} title="Say you're stuck">
            <Icon name="bolt" size={12} /> I&apos;m confused
          </button>
          <button data-testid="tutor-action-skip" className="btn btn--sm" onClick={() => onAction("skip")} disabled={disabled} title="Skip this concept">
            <Icon name="chev" size={12} /> Skip
          </button>
        </div>
      )}
      <div className={`fa26-chat-composer ${styles.composer}`}>
        <textarea
          ref={fieldRef}
          data-testid="tutor-input"
          aria-label={label}
          aria-describedby={[hintId, disabledReason ? reasonId : null].filter(Boolean).join(" ")}
          className={styles.field}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // Enter sends; Shift+Enter is a newline; an IME composition never sends.
            if (isSendKey(e)) {
              e.preventDefault();
              submit();
            }
          }}
          disabled={disabled}
          placeholder={placeholder}
          rows={2}
        />
        {disabledReason && <p id={reasonId} className={styles.reason}>{disabledReason}</p>}
        <div className={styles.composerRow}>
          <div className={styles.lead}>
            {lead}
            <p id={hintId} className={styles.hint}>Enter to send · Shift + Enter for a new line</p>
          </div>
          <div className={styles.sendGroup}>
            {streaming && onStop && (
              <button
                type="button"
                data-testid="tutor-stop"
                className={styles.stop}
                onClick={onStop}
              >
                Stop response
              </button>
            )}
            <button
              type="button"
              data-testid="tutor-send"
              className={styles.send}
              onClick={submit}
              disabled={disabled || !text.trim()}
              aria-label="Send"
            >
              <span aria-hidden="true">↑</span>
            </button>
          </div>
        </div>
        <p className="sapling-visually-hidden" role="status" aria-live="polite">
          {streaming ? "Clov is responding…" : ""}
        </p>
      </div>
    </div>
  );
});

const INTERRUPTED_COPY: Record<InterruptedReason, string> = {
  stopped: "You stopped this reply.",
  failed: "This reply was interrupted.",
  offline: "You're offline, so this reply didn't arrive.",
  paused: "Chat paused before this reply finished.",
};

const Message = React.memo(function Message({
  m,
  onRetry,
  retryAllowed = true,
}: {
  m: ChatMsg;
  onRetry?: (m: ChatMsg) => void;
  retryAllowed?: boolean;
}) {
  const isUser = m.role === "user";
  if (isUser) {
    return (
      <div className={`fade-in fa26-message fa26-message--user ${styles.userRow}`}>
        <div className={`fa26-message__bubble ${styles.userBubble}`}>
          <span className="sapling-visually-hidden">You: </span>
          <div className={styles.userText}>{m.content}</div>
        </div>
      </div>
    );
  }
  const offerRetry = !!(onRetry && m.retryText);
  return (
    <div className={`fade-in fa26-message fa26-message--assistant ${styles.assistantRow}`}>
      <span className={styles.avatar} aria-hidden="true">
        <BotanicalIcon name="clov" size={22} />
      </span>
      <div className={`fa26-message__bubble ${styles.assistantBody}`} data-interrupted={m.interrupted || undefined}>
        <span className="sapling-visually-hidden">Clov: </span>
        {m.loading ? (
          <span className={styles.thinking}>Clov is thinking…</span>
        ) : (
          // ADR 0020: an interrupted turn keeps its partial text visible — never blanked.
          m.content ? <MarkdownChat>{m.content}</MarkdownChat> : null
        )}
        {m.interrupted && (
          <div data-testid="tutor-interrupted" className={styles.interrupted}>
            <p className={styles.interruptedTitle}>{INTERRUPTED_COPY[m.interruptedReason ?? "failed"]}</p>
            {offerRetry && (
              <>
                <p className={styles.interruptedText}>
                  {m.content ? "The partial reply stays here. " : ""}
                  Your conversation is still here. Try the response again.
                </p>
                <button
                  type="button"
                  data-testid="tutor-retry"
                  className={styles.retry}
                  onClick={() => onRetry?.(m)}
                  disabled={!retryAllowed}
                >
                  Retry response
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
