"use client";

import React, { useEffect, useRef } from "react";
import { Icon } from "./Icon";
import { MarkdownChat } from "./MarkdownChat";
import { AIDisclaimerChip } from "./AIDisclaimerChip";

export type ChatRole = "user" | "assistant";
export interface ChatMsg {
  id: string;
  role: ChatRole;
  content: string;
  loading?: boolean;
}

interface ChatPanelProps {
  messages: ChatMsg[];
  input: string;
  onInputChange: (v: string) => void;
  onSend: () => void;
  onAction?: (action: "hint" | "confused" | "skip") => void;
  disabled?: boolean;
  placeholder?: string;
  header?: React.ReactNode;
}

export function ChatPanel({
  messages,
  input,
  onInputChange,
  onSend,
  onAction,
  disabled,
  placeholder = "Ask or respond…",
  header,
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
            value={input}
            onChange={e => onInputChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSend();
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
            onClick={onSend}
            disabled={disabled || !input.trim()}
            aria-label="Send"
          >
            <Icon name="send" size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}

function Message({ m }: { m: ChatMsg }) {
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
          lineHeight: 1.55,
          fontFamily: "var(--font-sans)",
          wordBreak: "break-word",
          overflowWrap: "break-word",
          position: "relative",
        }}
      >
        {m.loading ? (
          <span style={{ opacity: 0.6 }}>Thinking…</span>
        ) : isUser ? (
          <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
        ) : (
          <>
            <MarkdownChat>{m.content}</MarkdownChat>
            <div style={{ position: "absolute", bottom: 4, right: 8 }}>
              <AIDisclaimerChip compact />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
