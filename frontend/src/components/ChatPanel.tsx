"use client";

import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./Icon";
import { MarkdownChat } from "./MarkdownChat";

export type ChatRole = "user" | "assistant";
export interface ChatMsg {
  id: string;
  role: ChatRole;
  content: string;
  loading?: boolean;
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
}: ChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages]);

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
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "24px 32px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {messages.map(m => <Message key={m.id} m={m} />)}
      </div>

      <ChatInputBar
        onSend={onSend}
        onAction={onAction}
        disabled={disabled}
        placeholder={placeholder}
        draftSeed={draftSeed}
        draftSeedKey={draftSeedKey}
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
}

const ChatInputBar = React.memo(function ChatInputBar({
  onSend,
  onAction,
  disabled,
  placeholder,
  draftSeed,
  draftSeedKey,
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
          <button className="btn btn--sm" onClick={() => onAction("hint")} disabled={disabled} title="Ask for a small nudge">
            <Icon name="sparkle" size={12} /> Hint
          </button>
          <button className="btn btn--sm" onClick={() => onAction("confused")} disabled={disabled} title="Say you're stuck">
            <Icon name="bolt" size={12} /> I&apos;m confused
          </button>
          <button className="btn btn--sm" onClick={() => onAction("skip")} disabled={disabled} title="Skip this concept">
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
            outline: "none",
            padding: "6px 0",
            fontFamily: "var(--font-sans)",
            maxHeight: 160,
            minHeight: 36,
          }}
          rows={1}
        />
        <button
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

const Message = React.memo(function Message({ m }: { m: ChatMsg }) {
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
          <MarkdownChat>{m.content}</MarkdownChat>
        )}
      </div>
    </div>
  );
});
