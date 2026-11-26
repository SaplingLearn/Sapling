"use client";

import React, { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Icon } from "../Icon";
import { CHAT_MESSAGE_MAX } from "@/lib/inputLimits";
import { CrisisSupportCard } from "../safety/CrisisSupportCard";
import type { CrisisSupport } from "@/lib/crisisSupport";
import { cn } from "@/lib/cn";

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

/** What a tutor tool call means to the student, keyed by the tool's wire
 *  name (the stream's `progress` step; agents/chat_tutor.py registers them).
 *  null for a step with nothing worth saying, so "Thinking…" stays. */
export function tutorStepLabel(step: string): string | null {
  switch (step) {
    case "search_course_materials":
      return "Searching your course materials…";
    case "read_graph_neighborhood":
    case "read_concepts_for_user":
    case "read_user_progress_tool":
      return "Checking your progress…";
    case "read_session_history_tool":
      return "Reviewing this conversation…";
    case "update_mastery_tool":
    case "apply_graph_update_tool":
      return "Updating your knowledge graph…";
    default:
      return null;
  }
}
export interface ChatMsg {
  id: string;
  role: ChatRole;
  content: string;
  loading?: boolean;
  /** Replaces the "Thinking…" placeholder while `loading` — what the tutor
   *  is doing before its first word (see `tutorStepLabel`). */
  loadingLabel?: string;
  /** ADR 0020: the turn was stopped or failed mid-stream. The partial text
   *  stays in `content` (possibly empty when stopped pre-token); the bubble
   *  renders an "Interrupted" marker and — when `retryText` is set — a Retry
   *  action. Nothing was persisted server-side for such a turn (routes
   *  persist only on completion), so Retry is a plain re-send. */
  interrupted?: boolean;
  /** The user text that produced this (interrupted) turn — what Retry re-sends. */
  retryText?: string;
  /** docs/safety/crisis-support.md: the backend answered this turn with the
   *  crisis-support card instead of a tutor reply. Rendered as the calm card,
   *  never as a tutor bubble; `content` keeps the same copy as text. */
  crisisSupport?: CrisisSupport;
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
  /** What the tutor is doing while `streamingText` is still empty, e.g.
   *  "Searching your course materials…"; null/undefined = "Thinking…". */
  streamingStatus?: string | null;
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
  streamingStatus,
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
    <div className="flex flex-col h-full min-h-0">
      {header && <div>{header}</div>}
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-atomic="false"
        aria-label="Conversation"
        data-testid="tutor-messages"
        className="flex-1 overflow-y-auto py-6 px-8 flex flex-col gap-4"
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
            m={{
              id: "streaming",
              role: "assistant",
              content: streamingText,
              loading: streamingText === "",
              loadingLabel: streamingStatus ?? undefined,
            }}
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
      className="pt-3 px-8 pb-5 border-t border-t-border bg-bg-panel flex flex-col gap-2.5"
    >
      {onAction && (
        <div className="flex gap-1.5">
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
        className="flex gap-2.5 items-end bg-bg-subtle border border-border rounded-lg py-2.5 px-3.5"
      >
        <textarea
          data-testid="tutor-input"
          maxLength={CHAT_MESSAGE_MAX}
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
          className="flex-1 resize-none border-0 bg-transparent text-base leading-[1.5] py-1.5 px-0 font-sans max-h-40 min-h-9"
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
  if (m.crisisSupport && !isUser) {
    // Sapling speaking, not the tutor: no tutor avatar, no serif bubble.
    return (
      <div className="fade-in self-stretch max-w-160 w-full">
        <CrisisSupportCard support={m.crisisSupport} />
      </div>
    );
  }
  return (
    <div
      className={cn("fade-in", "flex gap-3", isUser ? "max-w-[70%]" : "max-w-[85%]", isUser ? "self-end" : "self-start")}
    >
      {!isUser && (
        <div
          className="w-8 h-8 rounded-[50%] bg-accent-soft text-accent flex items-center justify-center shrink-0"
        >
          <Icon name="sparkle" size={14} />
        </div>
      )}
      <div
        className={cn("py-3 px-4 rounded-lg text-base leading-[1.6] [word-break:break-word] [overflow-wrap:break-word] relative", isUser ? "bg-accent" : "bg-bg-panel", isUser ? "text-accent-fg" : "text-text", isUser ? "border-0" : "border border-border", isUser ? "font-sans" : "font-serif")}
      >
        {m.loading ? (
          <span className="opacity-60 font-sans">{m.loadingLabel || "Thinking…"}</span>
        ) : isUser ? (
          <div className="whitespace-pre-wrap">{m.content}</div>
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
            className={cn("flex items-center gap-2.5 font-sans text-sm text-text-muted", m.content ? "mt-2" : "mt-0")}
          >
            <span className="italic">Interrupted</span>
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
