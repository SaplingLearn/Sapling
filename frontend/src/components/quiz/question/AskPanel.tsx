"use client";

/**
 * "Ask about this" — the tutor, OVER the quiz (R-6).
 *
 * This is the behavioural point of the redesign. The old screen navigated to
 * `/learn?topic=…`, which abandoned the attempt: the questions were gone, the
 * answers already given were gone, and there was no way back. Here the tutor
 * arrives in a `Sheet` on top of the question; closing it puts the student
 * back on the exact same item with the exact same verdict on screen. The panel
 * owns all of its own state and dispatches no machine events — the attempt
 * cannot notice it happened.
 *
 * SEEDING (R1 §F). `StartSessionBody` has no context field: `topic` is the
 * session's display name, it is encrypted-stored, and it is matched against
 * course codes and concept names to find the course grounding — so dumping a
 * question stem into it would produce a garbage session title AND lose the
 * grounding. The only pattern that exists is two calls: open the session on
 * the concept name (with `course_id`, which is what actually grounds the graph
 * block and RAG), then send the composed context as the first message. The
 * tutor's greeting from that first call is deliberately never rendered — the
 * student asked about a question, not for a hello.
 *
 * The session is LEFT OPEN on close (no `end-session`): it stays in the
 * tutor's session list, which is where a student who wants to keep going will
 * look for it. The accumulating-sessions cost is recorded as a seam in §8.
 *
 * Failure handling mirrors `Learn.tsx`'s ladder, minus the parts that only
 * make sense in a transcript: a stream that produced nothing falls back to the
 * JSON route transparently, a stream that failed AFTER tokens (or one the
 * backend marked non-retryable, or a 413) surfaces an inline error with Retry.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Sheet } from "@/components/ui";
import {
  sendChat,
  shouldFallBackToJson,
  startSession,
  startSessionStream,
  streamChat,
} from "@/lib/api";

// The same renderer the tutor uses, loaded the same way `ChatPanel` loads it:
// `MarkdownChat` statically imports mermaid, katex and highlight.js, and a
// static import here would pull all of that into the quiz route's bundle.
const MarkdownChat = dynamic(
  () => import("@/components/chat/MarkdownChat").then(m => m.MarkdownChat),
  { ssr: false, loading: () => null },
);

/** The tutor mode a "why was I wrong" question wants. */
const TUTOR_MODE = "socratic";

/** Everything the tutor needs to know about the item that was missed. */
export interface AskSeed {
  stem: string;
  chosenLabel: string;
  chosenText: string;
  correctLabel: string;
  correctText: string;
  explanation: string;
}

export interface AskPanelProps {
  open: boolean;
  onClose: () => void;
  userId: string;
  conceptName: string;
  courseId: string | null;
  courseLabel?: string;
  seed: AskSeed;
  /** Focused after the panel closes. `Sheet` restores focus on its own; this
   *  is the explicit target for a caller whose trigger re-renders (B3's
   *  missed-list rows), and it runs after Sheet's restore, so it wins. */
  returnFocusTo?: React.RefObject<HTMLElement | null>;
  testid?: string;
}

interface AskTurn {
  id: number;
  role: "user" | "assistant";
  text: string;
  /** ADR 0020: the stream was cut off after producing this much. The partial
   *  stays in the thread, marked; Retry drops it and starts the answer over. */
  interrupted?: boolean;
}

/**
 * The first message. Exported because it is the actual contract with the
 * tutor — a test that pins the wording is pinning what the model is told.
 */
export function composeAskMessage(seed: AskSeed): string {
  return [
    "I got this quiz question wrong and want to understand why.",
    "",
    `Question: ${seed.stem}`,
    `I chose ${seed.chosenLabel}: ${seed.chosenText}`,
    `The correct answer is ${seed.correctLabel}: ${seed.correctText}`,
    `Explanation given: ${seed.explanation}`,
    "",
    "Help me understand why.",
  ].join("\n");
}

export function AskPanel({
  open,
  onClose,
  userId,
  conceptName,
  courseId,
  courseLabel,
  seed,
  returnFocusTo,
  testid = "quiz-ask-panel",
}: AskPanelProps) {
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  // The tutor session, held in a ref: nothing renders off it, and a follow-up
  // fired from a stale closure must still reach the session that was opened.
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Monotonic run token — a superseded turn's late resolution is dropped.
  const runRef = useRef(0);
  const idRef = useRef(0);
  // What Retry re-sends.
  const lastMessageRef = useRef<string>("");
  // The seed the current conversation was opened with.
  const lastSeededRef = useRef<string | null>(null);

  const seedMessage = useMemo(() => composeAskMessage(seed), [seed]);

  const nextId = () => ++idRef.current;

  const runTurn = useCallback(
    async (message: string) => {
      const token = ++runRef.current;
      // A new turn supersedes whatever was in flight; two streams writing into
      // the same partial-text state would interleave.
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      lastMessageRef.current = message;
      setBusy(true);
      setError(null);
      setStreaming("");
      let sawToken = false;
      // The partial reply so far. `streaming` state can't serve here: it is
      // cleared before the JSON leg and again in `finally`, and ADR 0020 needs
      // the text to outlive both.
      let partial = "";

      try {
        let sid = sessionIdRef.current;
        if (!sid) {
          try {
            const started = await startSessionStream(
              userId,
              conceptName,
              TUTOR_MODE,
              true,
              courseId ?? undefined,
              undefined,
              { signal: controller.signal },
            );
            sid = started.session_id ?? null;
          } catch (err) {
            if (controller.signal.aborted) return;
            if (!shouldFallBackToJson(err)) throw err;
            // The greeting is thrown away either way, so the JSON route is a
            // straight substitute here — there is no partial text to lose.
            const started = await startSession(
              userId,
              conceptName,
              TUTOR_MODE,
              courseId ?? undefined,
              true,
            );
            sid = started.session_id;
          }
          if (!sid) throw new Error("The tutor didn't open a session.");
          if (runRef.current !== token) return;
          sessionIdRef.current = sid;
        }

        let reply: string;
        try {
          // `graph_update` events are deliberately unhandled: this panel is a
          // read of the student's own mistake, not a study turn that should
          // move the graph under the quiz.
          const res = await streamChat(sid, userId, message, TUTOR_MODE, true, undefined, {
            onToken: delta => {
              if (delta.trim()) sawToken = true;
              partial += delta;
              setStreaming(prev => (prev ?? "") + delta);
            },
            signal: controller.signal,
          });
          reply = res.reply || "";
        } catch (err) {
          if (controller.signal.aborted) return;
          // Tokens already on screen, or a failure the JSON route would repeat
          // identically (#151a) — surface it rather than silently re-running.
          // The partial survives via the outer catch.
          if (sawToken || !shouldFallBackToJson(err)) throw err;
          setStreaming(null);
          const res = await sendChat(sid, userId, message, TUTOR_MODE, true);
          reply = res.reply || "";
        }

        if (runRef.current !== token) return;
        setTurns(t => [...t, { id: nextId(), role: "assistant", text: reply }]);
      } catch (err) {
        if (controller.signal.aborted || runRef.current !== token) return;
        // ADR 0020, and the whole reason `partial` exists: half an answer the
        // student was already reading must not blink out and be replaced by an
        // error strip. It stays in the thread, marked unfinished. Retry drops
        // it (`retry` below) so the second attempt doesn't read as a sequel.
        if (partial.trim()) {
          setTurns(t => [
            ...t,
            { id: nextId(), role: "assistant", text: partial, interrupted: true },
          ]);
        }
        setError(err instanceof Error ? err.message : "The tutor is unavailable.");
      } finally {
        if (runRef.current === token) {
          setBusy(false);
          setStreaming(null);
        }
      }
    },
    [userId, conceptName, courseId],
  );

  // Seed on open, and re-seed when the question changes (B3 opens the same
  // panel for each missed item). Keyed on the composed message rather than on
  // `open`, so closing and reopening the SAME question keeps the conversation.
  useEffect(() => {
    if (!open) return;
    if (lastSeededRef.current === seedMessage) return;
    lastSeededRef.current = seedMessage;
    sessionIdRef.current = null;
    setTurns([]);
    setStreaming(null);
    setError(null);
    setDraft("");
    void runTurn(seedMessage);
  }, [open, seedMessage, runTurn]);

  // Only on unmount. A stream is NOT aborted on close: the student can shut
  // the panel while the tutor is mid-sentence and find the finished answer
  // waiting when they reopen it.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Focus returns to whatever opened the panel. `Sheet`'s own restore already
  // does this for a trigger that stays mounted; this effect runs after that
  // cleanup, so an explicit target wins.
  const wasOpenRef = useRef(false);
  useEffect(() => {
    if (open) {
      wasOpenRef.current = true;
      return;
    }
    if (!wasOpenRef.current) return;
    wasOpenRef.current = false;
    returnFocusTo?.current?.focus();
  }, [open, returnFocusTo]);

  /**
   * Re-send the turn that failed. The interrupted partial is dropped first:
   * the retry produces a whole answer, and leaving the fragment above it would
   * read as the first half of the same reply.
   */
  const retry = () => {
    setTurns(t => (t.length > 0 && t[t.length - 1].interrupted ? t.slice(0, -1) : t));
    void runTurn(lastMessageRef.current);
  };

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setTurns(t => [...t, { id: nextId(), role: "user", text }]);
    void runTurn(text);
  };

  const subtitle = courseLabel ? `${conceptName} · ${courseLabel}` : conceptName;

  return (
    <Sheet open={open} onClose={onClose} title="Ask about this" testid={testid}>
      <div className="quiz-ask">
        <div className="quiz-ask__seed" data-testid="quiz-ask-seed">
          <p className="quiz-ask__seed-stem h-serif">{seed.stem}</p>
          <div className="quiz-ask__seed-card quiz-ask__seed-card--chosen">
            <span className="quiz-ask__seed-label">You chose {seed.chosenLabel} ·</span>
            {seed.chosenText}
          </div>
          <div className="quiz-ask__seed-card quiz-ask__seed-card--correct">
            <span className="quiz-ask__seed-label">The answer is {seed.correctLabel} ·</span>
            {seed.correctText}
          </div>
          {seed.explanation && (
            <p className="quiz-ask__seed-explanation body-serif">{seed.explanation}</p>
          )}
          <span className="quiz-ask__sr">Asking the tutor about {subtitle}.</span>
        </div>

        <div className="quiz-ask__thread" aria-live="polite">
          {turns.map(turn =>
            turn.role === "user" ? (
              <p key={turn.id} className="quiz-ask__turn--user">
                {turn.text}
              </p>
            ) : (
              <div key={turn.id} className="quiz-ask__turn--assistant">
                <MarkdownChat>{turn.text}</MarkdownChat>
                {turn.interrupted && (
                  <p className="quiz-ask__interrupted">Interrupted — the tutor didn&apos;t finish.</p>
                )}
              </div>
            ),
          )}
          {streaming !== null && (
            <div className="quiz-ask__turn--assistant">
              {streaming ? (
                <MarkdownChat>{streaming}</MarkdownChat>
              ) : (
                <p className="quiz-ask__pending">Thinking…</p>
              )}
            </div>
          )}
          {error && (
            <div className="quiz-ask__error" role="alert">
              <span>{error}</span>
              <button
                type="button"
                className="btn btn--sm"
                data-testid="quiz-ask-retry"
                onClick={retry}
              >
                Try again
              </button>
            </div>
          )}
        </div>

        <form className="quiz-ask__composer" onSubmit={send}>
          <input
            className="quiz-ask__input"
            type="text"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Ask a follow-up…"
            aria-label="Ask a follow-up"
            data-testid="quiz-ask-input"
          />
          <button
            type="submit"
            className="btn btn--primary"
            data-testid="quiz-ask-send"
            disabled={!draft.trim() || busy}
            aria-disabled={!draft.trim() || busy}
          >
            Send
          </button>
        </form>
      </div>
    </Sheet>
  );
}
