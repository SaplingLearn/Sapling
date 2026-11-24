"use client";

import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import styles from "./ChatPanel.module.css";
import { Icon } from "../Icon";
import { CHAT_MESSAGE_MAX } from "@/lib/inputLimits";
import { CrisisSupportCard } from "../safety/CrisisSupportCard";
import type { CrisisSupport } from "@/lib/crisisSupport";
import type { MarkdownProfile } from "./inertMarkdown";
import {
  MATERIALS_GROUNDED_HINT,
  MATERIALS_GROUNDED_LABEL,
  TRUST_CHROME_STYLE,
} from "@/lib/loopTrustChrome";

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
  /** Shown elsewhere on screen right now (the learning loop's check card shows
   *  its pose and hint): the row stays in the log — announced when it arrives
   *  and read in order — but is not painted, so nothing renders twice. Clearing
   *  the flag only paints it: no node is added, so nothing is announced again. */
  visuallyHidden?: boolean;
  /** W4.3: this turn's prompt included the student's course passages — calm
   *  "Grounded in your materials" chrome (no cite list; loop teach only). */
  materialsGrounded?: boolean;
}

/** The standard visually-hidden recipe: kept in the accessibility tree, painted nowhere. */
const VISUALLY_HIDDEN: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  margin: -1,
  padding: 0,
  overflow: "hidden",
  clipPath: "inset(50%)",
  whiteSpace: "nowrap",
  border: 0,
};

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
  /** The composer's textarea, for a parent that moves keyboard focus to it. */
  composerRef?: React.RefObject<HTMLTextAreaElement | null>;
  /** Wireframe T6: a "+" next to Send that opens where material is added. */
  /** Content between the conversation and the composer: the learning loop's
   *  check card and its next-step actions sit under the latest turn. */
  footer?: React.ReactNode;
  attachHref?: string;
  /** How a tutor turn is drawn: in a bubble beside its avatar (default), or
   *  on the page under the tutor's mark (`PageTurn`; the Tutor V2 layout).
   *  The student's own messages are bubbles on the right either way. */
  turnStyle?: "bubble" | "page";
  /** Which markdown a tutor turn may use (`inertMarkdown.tsx`). "rich" (the
   *  default) for every host but the learning loop, whose transcript repeats
   *  class material verbatim from code — a check pose, an H2 passage, a worked
   *  sibling, a reference — and so is drawn "inert" (Z08). */
  markdown?: MarkdownProfile;
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
  composerRef,
  attachHref,
  footer,
  turnStyle = "bubble",
  markdown = "rich",
}: ChatPanelProps) {
  const onPage = turnStyle === "page";
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const isStreaming = streamingText !== null && streamingText !== undefined;

  // Whether the student is reading the latest turn: then the log stays pinned
  // to it when its box resizes (a footer appearing or growing shrinks the log
  // after the messages rendered); scrolled up to read history, it is left alone.
  const pinned = useRef(true);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    pinned.current = true;
  }, [messages, streamingText]);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (pinned.current) el.scrollTop = el.scrollHeight;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      {header && <div>{header}</div>}
      {/* Focusable (tabIndex 0): the log scrolls on its own, and a scrolling
          region must be reachable from the keyboard (WCAG 2.1.1) — the arrow
          keys then scroll the history. */}
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 8;
        }}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-atomic="false"
        aria-label="Conversation"
        data-testid="tutor-messages"
        tabIndex={0}
        style={{
          // With a footer the log only takes the height it needs, so the
          // footer's actions sit right under the latest turn; a long
          // conversation still scrolls and the footer stays above the composer.
          flex: footer ? "0 1 auto" : 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "24px clamp(16px, 4vw, 56px)",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        {messages.map(m => <Message key={m.id} m={m} onRetry={onRetry} onPage={onPage} markdown={markdown} />)}
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
            onPage={onPage}
            markdown={markdown}
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

      {footer && (
        <div
          data-testid="chat-footer"
          style={{ padding: "0 clamp(16px, 4vw, 56px) 16px", maxHeight: "65%", overflowY: "auto", flexShrink: 0 }}
        >
          {footer}
        </div>
      )}
      {footer && <div aria-hidden style={{ flex: 1 }} />}
      <ChatInputBar
        onSend={onSend}
        onAction={onAction}
        disabled={disabled || isStreaming}
        placeholder={placeholder}
        draftSeed={draftSeed}
        draftSeedKey={draftSeedKey}
        streaming={isStreaming}
        onStop={onStop}
        composerRef={composerRef}
        attachHref={attachHref}
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
  composerRef?: React.RefObject<HTMLTextAreaElement | null>;
  attachHref?: string;
}

/** The composer's controls share one 32px square (Attach, Send; Stop is 32 tall). */
const COMPOSER_ICON: React.CSSProperties = {
  width: 32,
  height: 32,
  padding: 0,
  display: "inline-grid",
  placeItems: "center",
  alignSelf: "flex-end",
  boxSizing: "border-box",
};

const ChatInputBar = React.memo(function ChatInputBar({
  onSend,
  onAction,
  disabled,
  placeholder,
  draftSeed,
  draftSeedKey,
  streaming,
  onStop,
  composerRef,
  attachHref,
}: ChatInputBarProps) {
  const [text, setText] = useState<string>(draftSeed ?? "");
  const barRef = useRef<HTMLDivElement>(null);
  const ownInputRef = useRef<HTMLTextAreaElement>(null);
  const inputRef = composerRef ?? ownInputRef;
  // The composer is disabled while a reply streams, and a disabled control
  // loses keyboard focus to the page. A message sent from the composer (its
  // textarea or Send) puts focus back in the textarea when the reply ends —
  // unless something else (a posed check, a dialog) has taken focus by then.
  const refocus = useRef(false);

  // Apply the seed when the parent bumps the key (e.g. after a mode switch) —
  // never on mount: useState already starts from it, and a mount-time reset
  // would erase text typed before this effect ran.
  const seededKey = useRef(draftSeedKey);
  useEffect(() => {
    if (draftSeedKey === undefined || draftSeedKey === seededKey.current) return;
    seededKey.current = draftSeedKey;
    setText(draftSeed ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftSeedKey]);

  useLayoutEffect(() => {
    if (disabled || !refocus.current) return;
    refocus.current = false;
    const active = document.activeElement;
    if (!active || active === document.body) inputRef.current?.focus();
  }, [disabled, inputRef]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    refocus.current = !!barRef.current?.contains(document.activeElement);
    onSend(trimmed);
    setText("");
  };

  return (
    <div
      ref={barRef}
      style={{
        padding: "12px clamp(16px, 4vw, 56px) 20px",
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
        className={styles.composer}
      >
        <textarea
          ref={inputRef}
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
            style={{ height: 32, alignSelf: "flex-end" }}
            onClick={onStop}
            aria-label="Stop response"
          >
            Stop
          </button>
        )}
        {attachHref && (
          // Attach sits next to Send (wireframe T6): material is added in the
          // Library, where an upload is classified and indexed for the tutor.
          <Link
            href={attachHref}
            data-testid="tutor-attach"
            aria-label="Attach material"
            title="Attach material"
            className="btn btn--sm btn--ghost"
            style={COMPOSER_ICON}
          >
            <Icon name="plus" size={15} />
          </Link>
        )}
        <button
          data-testid="tutor-send"
          className="btn btn--primary btn--sm"
          style={{ ...COMPOSER_ICON, width: 40 }}
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

/** The loop tutor's turn carries a "Key idea:" paragraph the server adds
 *  (routes/learn_loop.py) — first in a teaching turn, after "The answer: …" in
 *  feedback. It shows as the design's key-idea block (a label over the idea, an
 *  accent rule beside it) where it stands; the text still reads "Key idea: …"
 *  to a screen reader and to `textContent`. */
const KEY_IDEA = /^Key idea:\s*/;

export type TurnPart = { kind: "text"; text: string } | { kind: "key"; text: string };

export function splitKeyIdea(content: string): TurnPart[] {
  const parts: TurnPart[] = [];
  let buffer: string[] = [];
  const flush = () => {
    if (buffer.length) parts.push({ kind: "text", text: buffer.join("\n\n") });
    buffer = [];
  };
  for (const para of content.split("\n\n")) {
    const idea = KEY_IDEA.test(para) ? para.replace(KEY_IDEA, "").trim() : "";
    if (idea) {
      flush();
      parts.push({ kind: "key", text: idea });
    } else {
      buffer.push(para);
    }
  }
  flush();
  return parts;
}

function AssistantBody({ content, profile }: { content: string; profile: MarkdownProfile }) {
  const parts = splitKeyIdea(content);
  if (!parts.some((p) => p.kind === "key")) return <MarkdownChat profile={profile}>{content}</MarkdownChat>;
  return (
    <>
      {parts.map((p, i) => p.kind === "key" ? (
        <div key={i} data-testid="tutor-key-idea" style={{ borderLeft: "3px solid var(--accent)", padding: "2px 0 2px 12px", margin: i === 0 ? "0 0 8px" : "8px 0" }}>
          <span className="label-micro" style={{ display: "block", color: "var(--accent)", marginBottom: 2 }}>
            Key idea<span style={VISUALLY_HIDDEN}>: </span>
          </span>
          <MarkdownChat profile={profile}>{p.text}</MarkdownChat>
        </div>
      ) : (
        <MarkdownChat key={i} profile={profile}>{p.text}</MarkdownChat>
      ))}
    </>
  );
}

/**
 * A tutor turn on the page (Tutor V2, wireframe T6: "tutor messages sit on the
 * page — no bubble, like Claude; your messages are bubbles on the right"): the
 * tutor's mark and name, then its text at a readable measure. `plain` keeps a
 * plain-text turn's own line breaks; a markdown turn lays out its own.
 */
export function PageTurn({ children, testId, plain = false }: { children: React.ReactNode; testId?: string; plain?: boolean }) {
  return (
    <div className={styles.pageTurn}>
      <div className={styles.turnMark}>
        <span className={styles.turnAvatar} aria-hidden>
          <Icon name="sparkle" size={12} />
        </span>
        Tutor<span style={VISUALLY_HIDDEN}>:</span>
      </div>
      <div className={plain ? `${styles.turnText} ${styles.turnPlain}` : styles.turnText} data-testid={testId}>
        {children}
      </div>
    </div>
  );
}

/** A message's text and its trust chrome (interrupted + Retry, "from your
 *  materials"). A plain render call, so React sees the tree the inline JSX
 *  produced. */
function renderMessageBody(m: ChatMsg, isUser: boolean, markdown: MarkdownProfile, onRetry?: (m: ChatMsg) => void) {
  return (
    <>
      {m.loading ? (
        <span style={{ opacity: 0.6, fontFamily: "var(--font-sans)" }}>{m.loadingLabel || "Thinking…"}</span>
      ) : isUser ? (
        <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
      ) : (
        // The tutor speaks in Spectral; the per-session DisclaimerModal
        // covers AI disclosure once up front so each message stays clean
        // (no "AI-Powered" pill — that anti-pattern is off the table).
        // ADR 0020: an interrupted turn keeps its partial text visible,
        // just dimmed — never blanked.
        <div style={m.interrupted ? { opacity: 0.7 } : undefined}>
          {m.content ? <AssistantBody content={m.content} profile={markdown} /> : null}
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
      {m.materialsGrounded && !isUser && !m.interrupted && (
        <div
          data-testid="loop-materials-grounded"
          role="status"
          title={MATERIALS_GROUNDED_HINT}
          aria-label={`${MATERIALS_GROUNDED_LABEL}. ${MATERIALS_GROUNDED_HINT}`}
          style={{
            marginTop: m.content ? 8 : 0,
            ...TRUST_CHROME_STYLE,
          }}
        >
          {MATERIALS_GROUNDED_LABEL}
        </div>
      )}
    </>
  );
}

const Message = React.memo(function Message({
  m,
  onRetry,
  onPage,
  markdown = "rich",
}: {
  m: ChatMsg;
  onRetry?: (m: ChatMsg) => void;
  /** A tutor turn sits on the page (`PageTurn`) rather than in a bubble. */
  onPage?: boolean;
  /** The markdown a tutor turn may use (ChatPanel's `markdown`). */
  markdown?: MarkdownProfile;
}) {
  const isUser = m.role === "user";
  if (m.crisisSupport && !isUser) {
    // Sapling speaking, not the tutor: no tutor avatar, no serif bubble.
    return (
      <div className="fade-in" style={{ alignSelf: "stretch", maxWidth: 640, width: "100%" }}>
        <CrisisSupportCard support={m.crisisSupport} />
      </div>
    );
  }
  const body = renderMessageBody(m, isUser, markdown, onRetry);
  // In the log but not painted (`visuallyHidden`): the row's own attributes.
  const hidden = m.visuallyHidden ? { attr: "true", style: VISUALLY_HIDDEN } : { attr: undefined, style: null };
  if (onPage && !isUser) {
    return (
      <div
        className="fade-in"
        data-testid="tutor-turn"
        data-visually-hidden={hidden.attr}
        style={{ alignSelf: "stretch", minWidth: 0, ...hidden.style }}
      >
        <PageTurn>{body}</PageTurn>
      </div>
    );
  }
  return (
    <div
      className="fade-in"
      data-visually-hidden={hidden.attr}
      style={{
        display: "flex",
        gap: 12,
        maxWidth: isUser ? "70%" : "85%",
        alignSelf: isUser ? "flex-end" : "flex-start",
        ...hidden.style,
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
        {body}
      </div>
    </div>
  );
});
