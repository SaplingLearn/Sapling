"use client";

import React, { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Icon } from "./Icon";

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
export interface ChatMsg {
  id: string;
  role: ChatRole;
  content: string;
  loading?: boolean;
  /** ADR 0020: the turn was stopped or failed mid-stream. The partial text
   *  stays in `content` (possibly empty when stopped pre-token); the bubble
   *  renders an "Interrupted" marker and — when `retryText` is set — a Retry
   *  action. Nothing was persisted server-side for such a turn (routes
   *  persist only on completion), so Retry is a plain re-send. */
  interrupted?: boolean;
  /** The user text that produced this (interrupted) turn — what Retry re-sends. */
  retryText?: string;
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
   *  message; Learn re-sends its `retryText` after dropping the failed pair. */
  onRetry?: (m: ChatMsg) => void;
}

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
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const isStreaming = streamingText !== null && streamingText !== undefined;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, streamingText]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {header && <div>{header}</div>}
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-atomic="false"
        aria-label="Conversation"
        data-testid="tutor-messages"
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "24px 32px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {messages.map(m => <Message key={m.id} m={m} onRetry={onRetry} />)}
        {streamingText !== null && streamingText !== undefined && (
          // Reuse Message/MarkdownChat exactly as settled assistant messages
          // do, so a streaming reply never styles differently from a
          // finished one. The `loading` flag reuses the same "Thinking…"
          // affordance Learn.tsx already shows for in-flight assistant
          // turns (see ChatMsg loading: true) rather than inventing a new
          // typing indicator. The scroll container above already declares
          // role="log" aria-live="polite" aria-relevant="additions", so this
          // bubble's appearance is announced without a second, nested
          // aria-live region on the bubble itself.
          <Message
            key="streaming"
            m={{ id: "streaming", role: "assistant", content: streamingText, loading: streamingText === "" }}
          />
        )}
      </div>

      <ChatInputBar
        onSend={onSend}
        onAction={onAction}
        disabled={disabled || isStreaming}
        placeholder={placeholder}
        draftSeed={draftSeed}
        draftSeedKey={draftSeedKey}
        streaming={isStreaming}
        onStop={onStop}
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
}: ChatInputBarProps) {
  const [text, setText] = useState<string>(draftSeed ?? "");

  // Apply seed when parent bumps the key (e.g. after a mode switch).
  useEffect(() => {
    if (draftSeedKey === undefined) return;
    setText(draftSeed ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftSeedKey]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div
      style={{
        padding: "12px 32px 20px",
        borderTop: "1px solid var(--border)",
        background: "var(--bg-panel)",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {onAction && (
        <div style={{ display: "flex", gap: 6 }}>
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
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "flex-end",
          background: "var(--bg-subtle)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-lg)",
          padding: "10px 14px",
        }}
      >
        <textarea
          data-testid="tutor-input"
          aria-label="Message"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          disabled={disabled}
          placeholder={placeholder}
          style={{
            flex: 1,
            resize: "none",
            border: 0,
            background: "transparent",
            fontSize: 14,
            lineHeight: 1.5,
            padding: "6px 0",
            fontFamily: "var(--font-sans)",
            maxHeight: 160,
            minHeight: 36,
          }}
          rows={1}
        />
        {streaming && onStop && (
          <button
            data-testid="tutor-stop"
            className="btn btn--sm"
            onClick={onStop}
            aria-label="Stop response"
          >
            Stop
          </button>
        )}
        <button
          data-testid="tutor-send"
          className="btn btn--primary btn--sm"
          onClick={submit}
          disabled={disabled || !text.trim()}
          aria-label="Send"
        >
          <Icon name="send" size={14} />
        </button>
      </div>
    </div>
  );
});

const Message = React.memo(function Message({
  m,
  onRetry,
}: {
  m: ChatMsg;
  onRetry?: (m: ChatMsg) => void;
}) {
  const isUser = m.role === "user";
  return (
    <div
      className="fade-in"
      style={{
        display: "flex",
        gap: 12,
        maxWidth: isUser ? "70%" : "85%",
        alignSelf: isUser ? "flex-end" : "flex-start",
      }}
    >
      {!isUser && (
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "var(--accent-soft)",
            color: "var(--accent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <Icon name="sparkle" size={14} />
        </div>
      )}
      <div
        style={{
          background: isUser ? "var(--accent)" : "var(--bg-panel)",
          color: isUser ? "var(--accent-fg)" : "var(--text)",
          padding: "12px 16px",
          borderRadius: "var(--r-lg)",
          border: isUser ? "none" : "1px solid var(--border)",
          fontSize: 14,
          lineHeight: 1.6,
          // Assistant voice is Spectral (body-serif) — "serif for soul,
          // sans for function". User messages keep the sans UI voice.
          fontFamily: isUser ? "var(--font-sans)" : "var(--font-serif)",
          wordBreak: "break-word",
          overflowWrap: "break-word",
          position: "relative",
        }}
      >
        {m.loading ? (
          <span style={{ opacity: 0.6, fontFamily: "var(--font-sans)" }}>Thinking…</span>
        ) : isUser ? (
          <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
        ) : (
          // The tutor speaks in Spectral; the per-session DisclaimerModal
          // covers AI disclosure once up front so each message stays clean
          // (no "AI-Powered" pill — that anti-pattern is off the table).
          // ADR 0020: an interrupted turn keeps its partial text visible,
          // just dimmed — never blanked.
          <div style={m.interrupted ? { opacity: 0.7 } : undefined}>
            {m.content ? <MarkdownChat>{m.content}</MarkdownChat> : null}
          </div>
        )}
        {m.interrupted && !isUser && (
          <div
            data-testid="tutor-interrupted"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginTop: m.content ? 8 : 0,
              fontFamily: "var(--font-sans)",
              fontSize: 12,
              color: "var(--text-muted)",
            }}
          >
            <span style={{ fontStyle: "italic" }}>Interrupted</span>
            {onRetry && m.retryText && (
              <button
                data-testid="tutor-retry"
                className="btn btn--sm"
                onClick={() => onRetry(m)}
                aria-label="Retry this turn"
              >
                Retry
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
