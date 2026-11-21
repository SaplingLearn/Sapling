"use client";
/**
 * Ask Clov: the chat beside the notes.
 *
 * Each question carries the notes text AS SHOWN (the student may have unsaved
 * edits), the last few turns, and the passage they selected. A reply is plain
 * text; the panel offers to drop it into the notes or copy it.
 */
import React from "react";

import { askDocumentNotes } from "@/lib/api";
import type { NotesChatTurn } from "@/lib/types";

export interface ClovMessage {
  role: "user" | "ai";
  text: string;
  /** The passage the student had selected when they asked. */
  quote?: string | null;
  /**
   * The reply is a rewrite of that passage, so "Insert" should REPLACE the
   * selection rather than add a quote below it.
   */
  forRewrite?: boolean;
}

/** The empty state's four openers, from the design. */
export const SUGGESTIONS = [
  "Explain the difficult parts",
  "How can I improve these notes?",
  "What's missing from my notes?",
  "Quiz me on this",
];

export interface ClovChat {
  messages: ClovMessage[];
  busy: boolean;
  input: string;
  setInput: (v: string) => void;
  quote: string | null;
  setQuote: (q: string | null) => void;
  ask: (text: string, quote?: string | null, forRewrite?: boolean) => void;
  send: () => void;
  clear: () => void;
}

export interface ClovChatInput {
  documentId: string;
  userId: string;
  /** The notes text as currently shown. */
  readNotes: () => string;
  /** Opens the panel when a selection action asks a question. */
  openPanel: () => void;
}

/** How much of a reply can be acted on: an apology about the failure cannot. */
export function canAct(text: string): boolean {
  return !/^Clov couldn't answer/.test(text);
}

export function useClovChat(input: ClovChatInput): ClovChat {
  const { documentId, userId, readNotes, openPanel } = input;
  const [messages, setMessages] = React.useState<ClovMessage[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [text, setText] = React.useState("");
  const [quote, setQuote] = React.useState<string | null>(null);

  const readRef = React.useRef(readNotes);
  readRef.current = readNotes;
  const openRef = React.useRef(openPanel);
  openRef.current = openPanel;

  const ask = React.useCallback((
    message: string, withQuote?: string | null, forRewrite = false,
  ) => {
    const body = message.trim();
    if (!body || busy) return;

    const history: NotesChatTurn[] = messages.slice(-5).map(m => ({
      role: m.role, text: m.text,
    }));
    setMessages(prev => [...prev, { role: "user", text: body, quote: withQuote ?? null }]);
    setText("");
    setQuote(null);
    setBusy(true);
    openRef.current();

    void (async () => {
      try {
        const res = await askDocumentNotes(documentId, userId, {
          message: body,
          notes: readRef.current(),
          quote: withQuote ?? null,
          history,
        });
        setMessages(prev => [...prev, {
          role: "ai",
          text: res.reply,
          forRewrite: forRewrite && !!withQuote,
        }]);
      } catch (err) {
        console.error("ask clov failed", err);
        setMessages(prev => [...prev, {
          role: "ai",
          text: "Clov couldn't answer that just now. Try again in a moment.",
        }]);
      } finally {
        setBusy(false);
      }
    })();
  }, [busy, messages, documentId, userId]);

  return {
    messages,
    busy,
    input: text,
    setInput: setText,
    quote,
    setQuote,
    ask,
    send: () => ask(text, quote),
    clear: () => { setMessages([]); setQuote(null); },
  };
}
