"use client";
/**
 * Ask Clov: the 440px panel on the right, and the round button that brings it
 * back once it is closed.
 *
 * The panel does not unmount when it closes — its width animates to zero and
 * its contents fade, so the toolbar beside it can be squeezed on the same
 * curve. Its collapsed state is remembered across visits.
 */
import React from "react";

import { Glyph } from "../library/primitives";
import { SQUEEZE } from "./toolbarModel";
import { canAct, SUGGESTIONS, type ClovMessage } from "@/lib/notes/useClovChat";

export const CLOV_WIDTH = 440;

export interface ClovPanelProps {
  open: boolean;
  onToggle: () => void;
  docTitle: string;
  messages: ClovMessage[];
  busy: boolean;
  input: string;
  onInput: (v: string) => void;
  quote: string | null;
  onClearQuote: () => void;
  onSend: () => void;
  onAsk: (text: string) => void;
  onClear: () => void;
  /** Put a reply into the notes; `forRewrite` replaces the quoted passage. */
  onInsert: (m: ClovMessage) => void;
  /** Which message was just copied, so its button can say so. */
  copied: number | null;
  onCopy: (index: number, text: string) => void;
}

/** Clov's mark, the one glyph this panel repeats. */
function ClovMark({ size }: { size: number }) {
  return <Glyph name="clov" size={size} fill="#445D22" />;
}

/** The three bouncing dots shown while a reply is on its way. */
function Typing() {
  return (
    <span style={{ display: "inline-flex", gap: 5, padding: "8px 0" }}>
      {[0, 1, 2].map(i => (
        <span key={i} style={{
          width: 7, height: 7, borderRadius: "50%", background: "#597536",
          animation: `sapDot 1.2s ${i * 0.15}s infinite ease-in-out`,
        }} />
      ))}
    </span>
  );
}

function EmptyState({
  docTitle, onAsk,
}: {
  docTitle: string;
  onAsk: (text: string) => void;
}) {
  return (
    <div style={{
      margin: "auto 0", display: "flex", flexDirection: "column", alignItems: "center",
      gap: 14, textAlign: "center",
    }}>
      <span style={{
        width: 64, height: 64, borderRadius: "50%", background: "#EBF0E1",
        display: "grid", placeItems: "center",
      }}>
        <ClovMark size={32} />
      </span>
      <span style={{ fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600 }}>
        Hi, I&apos;m Clov. How can I help?
      </span>
      <span style={{
        maxWidth: 320, fontSize: 14, color: "#6F6857", textWrap: "pretty",
      }}>
        Ask about anything in {docTitle}, or select text in your notes to ask about that part.
      </span>
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "stretch", gap: 8,
        width: "100%", marginTop: 8,
      }}>
        {SUGGESTIONS.map(s => (
          <button
            key={s}
            className="sapHoverSuggest"
            onClick={() => onAsk(s)}
            style={{
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
              height: 46, padding: "0 16px", border: "1px solid rgba(42,39,31,0.12)",
              borderRadius: 12, background: "#FFFFFF", color: "#1A1814", font: "inherit",
              fontSize: 15, fontWeight: 600, textAlign: "left", cursor: "pointer",
            }}
          >
            <span>{s}</span>
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
              <path
                d="M4 2l4 4-4 4" fill="none" stroke="#6F6857" strokeWidth="1.8"
                strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}

function Message({
  m, index, onInsert, copied, onCopy,
}: {
  m: ClovMessage;
  index: number;
  onInsert: (m: ClovMessage) => void;
  copied: number | null;
  onCopy: (index: number, text: string) => void;
}) {
  if (m.role === "user") {
    return (
      <div style={{
        alignSelf: "flex-end", maxWidth: "86%", display: "flex",
        flexDirection: "column", alignItems: "flex-end", gap: 6,
      }}>
        {m.quote && (
          <span style={{
            maxWidth: "100%", padding: "6px 10px", borderLeft: "3px solid #A9C48A",
            fontFamily: "var(--font-serif)", fontSize: 14, fontStyle: "italic",
            color: "#3F3B31", display: "-webkit-box", WebkitLineClamp: 3,
            WebkitBoxOrient: "vertical", overflow: "hidden",
          }}>“{m.quote}”</span>
        )}
        <span style={{
          padding: "10px 14px", borderRadius: "14px 14px 4px 14px", background: "#EBF0E1",
          color: "#1A1814", fontSize: 15, whiteSpace: "pre-wrap", textWrap: "pretty",
        }}>{m.text}</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
      <span style={{
        width: 30, height: 30, flexShrink: 0, borderRadius: "50%", background: "#EBF0E1",
        display: "grid", placeItems: "center",
      }}>
        <ClovMark size={16} />
      </span>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={{
          fontSize: 15, lineHeight: 1.6, color: "#1A1814",
          whiteSpace: "pre-wrap", textWrap: "pretty",
        }}>{m.text}</span>
        {canAct(m.text) && (
          <div style={{ display: "flex", gap: 6 }}>
            <button
              className="sapHoverTint"
              onClick={() => onInsert(m)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 6, height: 32,
                padding: "0 12px", border: "1px solid #C9D9B4", borderRadius: 9,
                background: "#F7FAF3", color: "#445D22", font: "inherit", fontSize: 13,
                fontWeight: 700, cursor: "pointer",
              }}
            >{m.forRewrite ? "Replace Selection" : "Add to Notes"}</button>
            <button
              className="sapHoverWarmerInk"
              onClick={() => onCopy(index, m.text)}
              style={{
                height: 32, padding: "0 12px", border: 0, borderRadius: 9,
                background: "transparent", color: "#6F6857", font: "inherit", fontSize: 13,
                fontWeight: 600, cursor: "pointer",
              }}
            >{copied === index ? "Copied" : "Copy"}</button>
          </div>
        )}
      </div>
    </div>
  );
}

/** The round button that reopens the panel, shown only while it is closed. */
export function ClovButton({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      title="Ask Clov"
      aria-label="Show Ask Clov"
      aria-expanded={open}
      data-testid="notes-clov-open"
      style={{
        position: "absolute", top: 86, right: 20, zIndex: 6, width: 40, height: 40,
        display: "grid", placeItems: "center", border: 0, borderRadius: "50%",
        background: "#EBF0E1", cursor: "pointer",
        opacity: open ? 0 : 1,
        pointerEvents: open ? "none" : "auto",
        transform: `scale(${open ? 0.6 : 1})`,
        transition: `opacity 200ms ease ${open ? "0ms" : "240ms"}, `
          + `transform 260ms cubic-bezier(0.2, 0.7, 0.2, 1) ${open ? "0ms" : "240ms"}, `
          + "background 120ms",
      }}
      className="sapHoverTintStrong"
    >
      <Glyph name="clov" size={22} fill="#445D22" />
    </button>
  );
}

export function ClovPanel(props: ClovPanelProps) {
  const {
    open, onToggle, docTitle, messages, busy, input, onInput, quote, onClearQuote,
    onSend, onAsk, onClear, onInsert, copied, onCopy,
  } = props;

  const listRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);

  // Every new turn scrolls to the bottom, as a chat should.
  React.useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, busy]);

  // A selection sent from the editor lands here with the caret in the box.
  React.useEffect(() => {
    if (quote) inputRef.current?.focus();
  }, [quote]);

  return (
    <aside
      aria-label="Ask Clov"
      aria-hidden={!open}
      data-testid="notes-clov"
      style={{
        animation: "sapFadeIn 420ms cubic-bezier(0.2, 0.7, 0.2, 1) 920ms both",
        width: open ? CLOV_WIDTH : 0,
        flexShrink: 0,
        overflow: "hidden",
        borderLeft: `1px solid ${open ? "rgba(42,39,31,0.10)" : "transparent"}`,
        background: "#FDFCF9",
        transition: `width ${SQUEEZE}, border-color 380ms`,
      }}
    >
      <div style={{
        width: CLOV_WIDTH, height: "100%", display: "flex", flexDirection: "column",
        opacity: open ? 1 : 0,
        transition: `opacity 220ms ease ${open ? "160ms" : "0ms"}`,
      }}>
        <div style={{
          height: 60, flexShrink: 0, display: "flex", alignItems: "center",
          justifyContent: "space-between", padding: "0 20px 0 12px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <button
              className="sapHoverClov"
              onClick={onToggle}
              title="Hide Ask Clov"
              aria-label="Hide Ask Clov"
              aria-expanded={open}
              style={{
                width: 36, height: 36, display: "grid", placeItems: "center", border: 0,
                borderRadius: 9, background: "transparent", color: "#3F3B31", cursor: "pointer",
              }}
            >
              <svg
                width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor"
                strokeWidth="1.6" aria-hidden="true"
              >
                <rect x="2.5" y="3" width="15" height="14" rx="2.5" />
                <path d="M12.5 3v14" />
                <path d="M6 7.5L8.5 10 6 12.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            <span style={{ fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 600 }}>
              Ask Clov
            </span>
          </div>
          {messages.length > 0 && (
            <button
              className="sapHoverWarmerInk"
              onClick={onClear}
              style={{
                height: 32, padding: "0 10px", border: 0, borderRadius: 8,
                background: "transparent", color: "#6F6857", font: "inherit", fontSize: 13,
                fontWeight: 600, cursor: "pointer",
              }}
            >New Chat</button>
          )}
        </div>

        <div
          ref={listRef}
          data-chatlist=""
          style={{
            flex: 1, minHeight: 0, overflowY: "auto", padding: "4px 24px 16px",
            display: "flex", flexDirection: "column", gap: 18,
          }}
        >
          {messages.length === 0 && !busy
            ? <EmptyState docTitle={docTitle} onAsk={onAsk} />
            : messages.map((m, i) => (
              <Message
                key={i}
                m={m}
                index={i}
                onInsert={onInsert}
                copied={copied}
                onCopy={onCopy}
              />
            ))}
          {busy && (
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <span style={{
                width: 30, height: 30, flexShrink: 0, borderRadius: "50%",
                background: "#EBF0E1", display: "grid", placeItems: "center",
              }}>
                <ClovMark size={16} />
              </span>
              <Typing />
            </div>
          )}
        </div>

        <div style={{ flexShrink: 0, padding: "8px 20px 14px" }}>
          <div style={{
            display: "flex", flexDirection: "column", gap: 8, padding: "6px 6px 6px 14px",
            border: "1px solid rgba(42,39,31,0.16)", borderRadius: 16, background: "#FFFFFF",
            boxShadow: "0 2px 8px rgba(25,37,11,0.05)",
          }}>
            {quote && (
              <div style={{
                display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 10px",
                borderRadius: 10, background: "#F4F1EA",
              }}>
                <span style={{
                  flex: 1, minWidth: 0, fontFamily: "var(--font-serif)", fontSize: 14,
                  fontStyle: "italic", color: "#3F3B31", display: "-webkit-box",
                  WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                }}>“{quote}”</span>
                <button
                  className="sapHoverAsh"
                  onClick={onClearQuote}
                  aria-label="Remove selected text"
                  style={{
                    width: 22, height: 22, flexShrink: 0, display: "grid", placeItems: "center",
                    border: 0, borderRadius: 6, background: "transparent", color: "#6F6857",
                    cursor: "pointer",
                  }}
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
                    <path
                      d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.6"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </div>
            )}
            <div style={{ display: "flex", alignItems: "flex-end", gap: 10 }}>
              <textarea
                ref={inputRef}
                data-testid="notes-clov-input"
                value={input}
                onChange={e => onInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSend(); }
                }}
                rows={1}
                placeholder={quote
                  ? "Ask about the selected text…"
                  : "Ask about these notes, or how to improve them…"}
                aria-label="Ask Clov about your notes"
                style={{
                  flex: 1, minWidth: 0, resize: "none", border: 0, outline: "none",
                  background: "transparent", font: "inherit", fontSize: 15, lineHeight: 1.5,
                  color: "#1A1814", padding: "7px 0", maxHeight: 140,
                  // Grows the box with what is typed, up to maxHeight, with no
                  // scroll-height measuring. Ignored where unsupported, which
                  // leaves the design's one-row default.
                  fieldSizing: "content",
                }}
              />
              <button
                onClick={onSend}
                aria-label="Send"
                data-testid="notes-clov-send"
                style={{
                  width: 36, height: 36, flexShrink: 0, display: "grid", placeItems: "center",
                  border: 0, borderRadius: 12,
                  background: input.trim() && !busy ? "#445D22" : "#B9C4A8",
                  color: "#FFFFFF", cursor: "pointer",
                }}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                  <path
                    d="M8 13V3M3.5 7.5L8 3l4.5 4.5" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>
  );
}
